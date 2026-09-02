"""Intake Agent (Docs section 5 step 5). NL -> structured MonthlyPlanRequest.

The LLM ONLY extracts constraints + asks appetite. It never plans the month
(Docs section 3 architectural rule).

Two paths:
  - LLM path: Gemini 2.5 Flash if GEMINI_API_KEY set. Returns strict JSON.
  - Fallback: deterministic regex parser. Zero-dependency, works offline so the
    demo never dies on a missing key or network. Covers the common phrasings
    ("10k budget", "at least 10 paneer meals", "veg only", "heavy eater").

Improvement over doc: doc assumes LLM. We make LLM optional. Demo is deterministic
and reproducible; prototype flips on the key for free-form parsing.
"""
import os
import re
import json
from dataclasses import dataclass, field

APPETITE_LEVELS = ("light", "moderate", "heavy", "very_heavy")


@dataclass
class ParsedIntake:
    budget: float = None
    constraints: list = field(default_factory=list)   # [{"dish_tag","min_count"}]
    veg_only: bool = False
    appetite_level: str = None                         # may be None -> ask user
    days: int = 30
    source: str = "fallback"                           # "llm" | "fallback"
    needs_appetite: bool = False


# ---------- deterministic fallback parser ----------
_BUDGET_RE = re.compile(r"(?:budget|₹|rs\.?|inr)?\s*([\d,]+)\s*(k|thousand)?", re.I)
_COUNT_DISH_RE = re.compile(
    r"(?:at\s*least\s*|min(?:imum)?\s*)?(\d+)\s*([a-z]+)\s*meals?", re.I)
_KNOWN_TAGS = ("paneer", "chicken", "egg", "dal", "rajma", "chole", "biryani",
               "veg", "dosa", "idli", "thali", "rice")

# NEW: pairing patterns for "dessert with dinner always" etc
_PAIRING_PATTERN = re.compile(
    r"\b(dessert|sweet|drink|beverage|juice|lassi|coffee|tea)\s+"
    r"(?:with|after|for)\s+"
    r"(breakfast|lunch|dinner)\s+"
    r"(always|every\s*day|daily|must)",
    re.I
)

# Also catch "drinks with lunch" without "always" - assume they mean always
_PAIRING_RELAXED = re.compile(
    r"\b(dessert|sweet|drink|beverage|juice|lassi|coffee|tea)s?\s+"
    r"(?:with|after|for)\s+"
    r"(breakfast|lunch|dinner)",
    re.I
)

# Map user words to dish_kind constants
_KIND_MAP = {
    "dessert": "sweet",
    "sweet": "sweet",
    "drink": "beverage",
    "beverage": "beverage",
    "juice": "beverage",
    "lassi": "beverage",
    "coffee": "beverage",
    "tea": "beverage",
}


def _parse_budget(text):
    # find explicit budget: prefer number followed by k, else largest plain number
    best = None
    for m in re.finditer(r"(\d[\d,]*)\s*(k|thousand)?", text, re.I):
        num = float(m.group(1).replace(",", ""))
        if m.group(2):
            num *= 1000
        if num >= 500:  # ignore tiny numbers like counts
            best = max(best or 0, num)
    return best


def _parse_constraints(text):
    out = []
    # Original pattern: "N dish_tag meals"
    for m in _COUNT_DISH_RE.finditer(text):
        count = int(m.group(1))
        word = m.group(2).lower()
        if word in _KNOWN_TAGS:
            out.append({"dish_tag": word, "min_count": count})
    # also "10 paneer" without "meals"
    for m in re.finditer(r"(\d+)\s*(" + "|".join(_KNOWN_TAGS) + r")\b", text, re.I):
        tag = m.group(2).lower()
        cnt = int(m.group(1))
        if not any(c["dish_tag"] == tag for c in out) and tag not in ("veg",):
            out.append({"dish_tag": tag, "min_count": cnt})

    # NEW: pairing patterns like "dessert with dinner always"
    for m in _PAIRING_PATTERN.finditer(text):
        item_type = m.group(1).lower()
        meal_slot = m.group(2).lower()
        frequency_word = m.group(3).lower()

        dish_kind = _KIND_MAP.get(item_type, item_type)
        frequency = "always" if frequency_word in ("always", "daily", "must") else "always"

        # Pairing constraint has empty dish_tag, min_count=0, but sets kind+slot+freq
        out.append({
            "dish_tag": "",
            "min_count": 0,
            "dish_kind": dish_kind,
            "slot_type": meal_slot,
            "frequency": frequency,
        })

    # Also catch relaxed patterns without explicit "always"
    for m in _PAIRING_RELAXED.finditer(text):
        item_type = m.group(1).lower()
        meal_slot = m.group(2).lower()

        dish_kind = _KIND_MAP.get(item_type, item_type)

        # Check if already added by strict pattern
        if not any(c.get("dish_kind") == dish_kind and c.get("slot_type") == meal_slot
                   for c in out):
            out.append({
                "dish_tag": "",
                "min_count": 0,
                "dish_kind": dish_kind,
                "slot_type": meal_slot,
                "frequency": "always",
            })

    return out


def _parse_appetite(text):
    t = text.lower()
    if "very heavy" in t or "very-heavy" in t:
        return "very_heavy"
    for lvl in ("heavy", "moderate", "light"):
        if lvl in t:
            return lvl
    if "big eater" in t or "large appetite" in t:
        return "heavy"
    return None


def fallback_parse(text) -> ParsedIntake:
    veg = bool(re.search(r"\bveg(?:etarian)?\s*only\b|\bpure\s*veg\b|\bonly\s*veg\b", text, re.I))
    budget = _parse_budget(text)
    constraints = _parse_constraints(text)
    appetite = _parse_appetite(text)
    return ParsedIntake(
        budget=budget,
        constraints=constraints,
        veg_only=veg,
        appetite_level=appetite,
        source="fallback",
        needs_appetite=appetite is None,
    )


# ---------- LLM path (Gemini 2.5 Flash) ----------
_SYSTEM = """You extract structured meal-plan constraints from a user message.
Return ONLY valid JSON, no prose. Schema:
{
  "budget": <number INR or null>,
  "constraints": [{"dish_tag": "<lowercase keyword>", "min_count": <int>}],
  "veg_only": <bool>,
  "appetite_level": "light|moderate|heavy|very_heavy" or null,
  "days": <int, default 30>
}
Do NOT plan meals. Only extract. If appetite not stated, use null."""


GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")


def llm_parse(text) -> ParsedIntake:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return fallback_parse(text)
    try:
        import urllib.request
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_MODEL}:generateContent")
        body = {
            "system_instruction": {"parts": [{"text": _SYSTEM}]},
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"response_mime_type": "application/json"},
        }
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "X-goog-api-key": key})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(raw)
        return ParsedIntake(
            budget=parsed.get("budget"),
            constraints=parsed.get("constraints", []),
            veg_only=bool(parsed.get("veg_only", False)),
            appetite_level=parsed.get("appetite_level"),
            days=parsed.get("days", 30),
            source="llm",
            needs_appetite=parsed.get("appetite_level") is None,
        )
    except Exception:
        # any LLM failure -> deterministic fallback, demo never blocks
        return fallback_parse(text)


def parse_intake(text) -> ParsedIntake:
    """Entry point. LLM if key present, else fallback."""
    return llm_parse(text)


if __name__ == "__main__":
    for s in [
        "I have 10k budget, at least 10 paneer meals, veg only, I'm a heavy eater",
        "budget 15000, 8 chicken meals and 5 biryani",
        "₹12,000 monthly, moderate appetite",
    ]:
        p = fallback_parse(s)
        print(s, "\n ->", p, "\n")
