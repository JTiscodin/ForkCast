"""Conversational blueprint builder — the "Claude-style" chat that gathers meal-plan
requirements before any plan is generated.

Design goals:
  - ONE Gemini call per user turn (extract + reply + next question together).
  - TOKEN-FRUGAL: we send the compact blueprint STATE + the last few messages, not
    the whole transcript. State is echoed back to the client each turn, so context
    stays small and constant regardless of conversation length. This keeps us well
    inside Gemini's free tier (~15 RPM, ~1500 req/day; a full blueprint chat is
    ~6 requests, so ~250 conversations/day free).
  - The LLM ONLY fills the blueprint + phrases questions. It NEVER builds a plan —
    the deterministic optimizer does that when the user hits "Generate Plan".
  - Deterministic fallback when GEMINI_API_KEY is missing, so it always works.

Blueprint schema (what we need before planning):
  budget            (required)  int INR
  appetite_level    (required)  light|moderate|heavy|very_heavy
  veg_only          bool
  constraints       [{dish_tag, min_count}]   must-have dishes
  cuisines          [str]        liked cuisines (north_indian, south_indian, ...)
  meals             [str]        which slots: breakfast|lunch|dinner (default all 3)
  days              int          default 30
"""
import json
import gemini
from intake import fallback_parse

REQUIRED = ("budget", "appetite_level")

EMPTY_BLUEPRINT = {
    "budget": None,
    "appetite_level": None,
    "veg_only": False,
    "constraints": [],
    "cuisines": [],
    "meals": ["breakfast", "lunch", "dinner"],
    "days": 30,
}

# Fields we proactively ask about (rich, Claude-style context gathering), in order.
# Required ones first; then nice-to-haves that tailor the plan.
CLARIFY_ORDER = [
    ("budget", "What's your monthly food budget?"),
    ("appetite_level", "How big is your appetite — light, moderate, heavy, or very heavy?"),
    ("veg_pref", "Do you want veg-only, or a mix of veg and non-veg?"),
    ("cuisines", "Any cuisines you especially like — North Indian, South Indian, Chinese?"),
    ("constraints", "Any must-have dishes you want regularly (e.g. paneer, biryani)?"),
    ("meals", "Should I plan all three meals a day, or just some of them?"),
]

_SYSTEM = """You are a warm, concise meal-planning assistant (like a helpful human planner).
Your job is ONLY to gather requirements into a blueprint and ask for what's missing.
You NEVER write a meal plan, dish list, or calendar — a separate engine does that later.

You will receive the current blueprint (JSON) and the user's latest message.
Return ONLY valid JSON with this shape:
{
  "blueprint": {
    "budget": <int INR or null>,
    "appetite_level": "light|moderate|heavy|very_heavy" or null,
    "veg_only": <bool>,
    "constraints": [{"dish_tag": "<lowercase>", "min_count": <int>}],
    "cuisines": [<lowercase cuisine>],
    "meals": [<"breakfast"|"lunch"|"dinner">],
    "days": <int>
  },
  "reply": "<one to two friendly sentences: acknowledge what they said, then ask for ONE missing/next thing. If everything needed is present, warmly say the plan is ready to generate.>",
  "ready": <true only if budget AND appetite_level are both set>
}
Merge new info into the existing blueprint; never drop already-known fields.
Ask about at most ONE thing per reply. Prefer asking required fields (budget, appetite) first,
then diet, cuisines, must-have dishes. Use "Rs" not the rupee symbol. Keep it human and short."""


def _merge_blueprint(prev, patch):
    """Merge an LLM/heuristic patch over the previous blueprint (new non-empty wins)."""
    bp = {**EMPTY_BLUEPRINT, **(prev or {})}
    if not patch:
        return bp
    for k in ("budget", "appetite_level", "days"):
        if patch.get(k) not in (None, ""):
            bp[k] = patch[k]
    if "veg_only" in patch and patch["veg_only"]:
        bp["veg_only"] = True
    for k in ("constraints", "cuisines", "meals"):
        v = patch.get(k)
        if v:
            bp[k] = v
    return bp


def _first_missing(bp):
    """Return the next field to ask about (rich clarify), or None if fully gathered."""
    if bp.get("budget") is None:
        return "budget"
    if bp.get("appetite_level") is None:
        return "appetite_level"
    # nice-to-haves: only ask each once — treat 'asked' as 'has a value or explicitly empty'
    if not bp.get("_asked_veg"):
        return "veg_pref"
    if not bp.get("cuisines") and not bp.get("_asked_cuisines"):
        return "cuisines"
    if not bp.get("constraints") and not bp.get("_asked_constraints"):
        return "constraints"
    return None


def _ready(bp):
    return bp.get("budget") is not None and bp.get("appetite_level") is not None


def _fallback_turn(prev_bp, message):
    """Deterministic turn: regex-extract, merge, ask next question. No LLM."""
    parsed = fallback_parse(message)
    patch = {
        "budget": parsed.budget,
        "appetite_level": parsed.appetite_level,
        "veg_only": parsed.veg_only,
        "constraints": parsed.constraints or None,
        "days": parsed.days if parsed.days != 30 else None,
    }
    bp = _merge_blueprint(prev_bp, patch)

    # crude cuisine capture
    low = message.lower()
    cuisines = [c for c in ("north_indian", "south_indian", "chinese", "hyderabadi")
                if c.replace("_", " ") in low or c.split("_")[0] in low]
    if cuisines:
        bp["cuisines"] = sorted(set(bp.get("cuisines", []) + cuisines))

    # A nice-to-have counts as "answered" once its value is present OR the user's
    # message clearly addressed it — so we don't re-ask what they already told us.
    if bp.get("veg_only") or any(w in low for w in
                                 ("veg", "non-veg", "nonveg", "chicken", "egg", "both", "mix")):
        bp["_asked_veg"] = True
    if bp.get("cuisines"):
        bp["_asked_cuisines"] = True
    if bp.get("constraints"):
        bp["_asked_constraints"] = True

    # READY is decided by the REQUIRED fields only — nice-to-haves never block it.
    ready = _ready(bp)
    ask = _first_missing(bp)

    if ask == "budget":
        reply = "Happy to plan your month! First, what's your monthly food budget?"
    elif ask == "appetite_level":
        reply = "Got it. How big is your appetite — light, moderate, heavy, or very heavy?"
    elif ask == "veg_pref":
        bp["_asked_veg"] = True
        reply = "Great. Do you want veg-only, or a mix of veg and non-veg?"
    elif ask == "cuisines":
        bp["_asked_cuisines"] = True
        reply = "Any cuisines you especially like — North Indian, South Indian, Chinese?"
    elif ask == "constraints":
        bp["_asked_constraints"] = True
        reply = "Any must-have dishes you'd want regularly, like paneer or biryani?"
    else:
        reply = "Perfect — I have what I need. Hit Generate Plan and I'll build your month."
    return bp, reply, ready


def turn(prev_bp, message, history=None):
    """Process one user message. Returns (blueprint, reply, ready).

    history: optional list of {"role","text"} — we only pass the LAST FEW to Gemini
    to keep tokens tiny. Blueprint state carries the real memory.
    """
    prev_bp = {**EMPTY_BLUEPRINT, **(prev_bp or {})}

    if not gemini.has_key():
        return _fallback_turn(prev_bp, message)

    tail = (history or [])[-4:]
    convo = "\n".join(f"{m.get('role','user')}: {m.get('text','')}" for m in tail)
    prompt = (
        f"Current blueprint:\n{json.dumps({k: v for k, v in prev_bp.items() if not k.startswith('_')})}\n\n"
        f"Recent conversation:\n{convo}\n\n"
        f"User's latest message:\n{message}\n\n"
        f"Return the updated JSON."
    )
    text = gemini.chat(prompt, system=_SYSTEM)
    if not text:
        return _fallback_turn(prev_bp, message)
    try:
        # tolerate ```json fences
        raw = text.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        patch = data.get("blueprint", {})
        bp = _merge_blueprint(prev_bp, patch)
        # preserve any _asked_* flags across turns
        for k in prev_bp:
            if k.startswith("_asked"):
                bp[k] = prev_bp[k]
        reply = data.get("reply") or "Tell me a bit more about what you'd like."
        ready = bool(data.get("ready")) and _ready(bp)
        return bp, reply, ready
    except Exception:
        return _fallback_turn(prev_bp, message)


def public_blueprint(bp):
    """Strip internal _asked_* flags before sending to the client."""
    return {k: v for k, v in bp.items() if not k.startswith("_")}


# ---- plan adjustment: NL tweak on an existing blueprint -> new blueprint ----
_ADJUST_SYSTEM = """You adjust an existing meal-plan blueprint based on a user's tweak.
Return ONLY JSON: {"blueprint": {...full updated blueprint...}, "reply": "<one short sentence confirming the change>"}.
Apply the change to the given blueprint (e.g. lower budget, fewer paneer meals, add a cuisine,
switch to veg-only). Keep all other fields. Use the same blueprint schema. "Rs" not the rupee symbol."""


def adjust(prev_bp, message):
    """Apply an NL tweak to an existing blueprint. Returns (blueprint, reply)."""
    prev_bp = {**EMPTY_BLUEPRINT, **(prev_bp or {})}
    if gemini.has_key():
        prompt = (f"Current blueprint:\n{json.dumps(public_blueprint(prev_bp))}\n\n"
                  f"User's change request:\n{message}\n\nReturn updated JSON.")
        text = gemini.chat(prompt, system=_ADJUST_SYSTEM)
        if text:
            try:
                raw = text.strip()
                if raw.startswith("```"):
                    raw = raw.split("```", 2)[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                data = json.loads(raw)
                bp = _merge_blueprint(prev_bp, data.get("blueprint", {}))
                return bp, data.get("reply") or "Updated your plan."
            except Exception:
                pass
    # fallback: re-extract from the tweak and merge
    bp, _, _ = _fallback_turn(prev_bp, message)
    return bp, "Updated your plan."
