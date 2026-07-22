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
