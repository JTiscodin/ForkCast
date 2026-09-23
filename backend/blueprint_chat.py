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
    # Steers the catalog SEARCH toward protein-rich dishes. The base seed
    # queries are ordinary meals, so "I need to hit my protein intake" has to
    # change what we fetch — filtering afterwards can't add dishes that were
    # never searched for.
    "high_protein": False,
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
    "veg_only": <true ONLY if they want vegetarian food; false if they eat non-veg / eggs / a mix>,
    "high_protein": <true if they mention protein, gym, muscle, fitness or a high-protein diet>,
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
    # veg_only is explicitly three-state on the wire: True (veg), False
    # (non-veg / mixed), or absent (unknown, keep what we had). Treating a
    # present-and-False as "no information" meant a user saying "non-veg"
    # could never clear a veg_only that had been set earlier.
    if patch.get("veg_only") is not None:
        bp["veg_only"] = bool(patch["veg_only"])
    if patch.get("high_protein") is not None:
        bp["high_protein"] = bool(patch["high_protein"])
    if patch.get("constraints"):
        bp["constraints"] = _normalize_constraints(patch["constraints"])
    for k in ("cuisines", "meals"):
        v = patch.get(k)
        if v:
            bp[k] = [str(x).strip().lower() for x in v if str(x).strip()]
    return bp


# Filler words an LLM wraps around a dish name when it treats dish_tag as a
# sentence ("include egg bhurji with roti"). A tag is matched as a substring of
# dish names, so anything wordy can never match and the constraint is dead.
_TAG_STOPWORDS = {
    "include", "add", "want", "need", "with", "and", "or", "some", "more",
    "less", "the", "a", "an", "of", "for", "please", "also", "atleast",
    "at", "least", "every", "each", "day", "meal", "meals", "times", "per",
    "week", "month", "my", "me", "i", "it", "just", "not", "only", "get",
}
_MAX_TAG_WORDS = 3


def _clean_tags(tag):
    """Split a possibly-wordy tag into searchable dish tags.

    Guards the failure the prompt now warns about: the model returned
    dish_tag="include egg bhurji with roti", which matches no dish name and
    leaves a permanently unmet constraint. That is really TWO dishes, so it
    becomes ["egg bhurji", "roti"] rather than one dead tag.
    """
    text = str(tag).strip().lower().replace("-", " ")
    # "and"/"with"/"+"/"," all separate dishes in this phrasing.
    for sep in (" and ", " with ", ",", "+", "&", " plus "):
        text = text.replace(sep, "|")

    tags = []
    for part in text.split("|"):
        words = [w for w in part.split() if any(ch.isalpha() for ch in w)]
        kept = [w for w in words if w not in _TAG_STOPWORDS]
        if not kept:
            continue
        # Keep the tail — qualifiers lead, the dish name trails
        # ("include egg bhurji" -> "egg bhurji").
        tags.append(" ".join(kept[-_MAX_TAG_WORDS:]))
    return tags


def _normalize_constraints(raw):
    """Coerce whatever the LLM emitted into [{"dish_tag": str, "min_count": int}].

    The model is prompted for that shape but is not bound to it, and it happily
    returns a bare list of strings (["egg bhurji", "roti"]) instead. That reached
    the optimizer as `c["dish_tag"]` on a str and crashed /plan with
    "string indices must be integers". Anything unrecognisable is dropped rather
    than passed through — a missing constraint is recoverable, a 500 is not.
    """
    if isinstance(raw, (str, dict)):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []

    out, seen = [], set()
    for item in raw:
        tag, count = None, 1
        pairing = None
        if isinstance(item, str):
            tag = item
        elif isinstance(item, dict):
            tag = item.get("dish_tag") or item.get("tag") or item.get("dish") \
                or item.get("name")
            count = item.get("min_count") or item.get("count") or item.get("min") or 1
            # Pairing constraints ("dessert with dinner always"): kind + slot
            # + frequency carry the actual intent, the tag is empty. Preserve
            # them — stripping the keys here turned every pairing request into
            # a no-op the optimizer never saw.
            if (item.get("dish_kind") and item.get("slot_type")):
                pairing = {
                    "dish_tag": "",
                    "min_count": 0,
                    "dish_kind": str(item["dish_kind"]),
                    "slot_type": str(item["slot_type"]),
                    "frequency": item.get("frequency") or "always",
                }
        if pairing is not None:
            key = (pairing["dish_kind"], pairing["slot_type"])
            if key not in seen:
                seen.add(key)
                out.append(pairing)
            continue
        if not tag or not str(tag).strip():
            continue
        try:
            count = max(1, int(count))
        except (TypeError, ValueError):
            count = 1
        # One entry may name several dishes ("egg bhurji and roti"); each is a
        # separate constraint, otherwise neither can ever match a dish name.
        for piece in _clean_tags(tag):
            if piece in seen:
                continue
            seen.add(piece)
            out.append({"dish_tag": piece, "min_count": count})
    return out


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
    low = message.lower()

    # Diet: an explicit non-veg signal must be able to CLEAR veg_only, not just
    # fail to set it. "non-veg" contains "veg" as a substring, so check the
    # negative forms first.
    nonveg_words = ("non-veg", "nonveg", "non veg", "chicken", "mutton", "egg",
                    "fish", "prawn", "meat", "keema")
    veg_signal = None
    if any(w in low for w in nonveg_words):
        veg_signal = False
    elif parsed.veg_only:
        veg_signal = True

    patch = {
        "budget": parsed.budget,
        "appetite_level": parsed.appetite_level,
        "veg_only": veg_signal,
        # "protien" is a very common transposition and appeared in the real
        # message that surfaced this bug — match it explicitly rather than
        # silently ignoring the user's intent over a typo.
        "high_protein": True if any(
            w in low for w in ("protein", "protien", "protine", "gym", "muscle",
                               "workout", "fitness", "bulking", "macros",
                               "high-protein", "hi protein")) else None,
        "constraints": parsed.constraints or None,
        "days": parsed.days if parsed.days != 30 else None,
    }
    bp = _merge_blueprint(prev_bp, patch)

    # crude cuisine capture
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
switch to veg-only). Keep all other fields. Use the same blueprint schema. "Rs" not the rupee symbol.

"constraints" must be [{"dish_tag": "<ONE or TWO lowercase words>", "min_count": <int>}].
A dish_tag is a SEARCHABLE INGREDIENT OR DISH NAME - "paneer", "egg bhurji", "biryani".
It is matched against dish names, so it must never be a sentence or an instruction.
  GOOD: [{"dish_tag": "egg bhurji", "min_count": 8}, {"dish_tag": "roti", "min_count": 8}]
  BAD:  [{"dish_tag": "include egg bhurji with roti", "min_count": 1}]
Split a request naming several dishes into one entry per dish."""


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
    # Deterministic fallback. Reached whenever Gemini is unavailable — a dead
    # key, a network blip, or (routinely) a 429 once the free-tier quota is
    # spent. It must still honour "add X" / "more Y", or an adjust silently
    # does nothing and the user is told "Updated your plan."
    bp, _, _ = _fallback_turn(prev_bp, message)
    added = _extract_added_dishes(message)
    if added:
        existing = {c["dish_tag"] for c in bp.get("constraints", [])}
        bp["constraints"] = bp.get("constraints", []) + [
            c for c in added if c["dish_tag"] not in existing]
        names = ", ".join(c["dish_tag"] for c in added)
        return bp, f"Added {names} to your plan."
    return bp, "Updated your plan."


# "add paneer", "include egg bhurji", "more roti", "with dal"
_ADD_VERBS = ("add ", "include ", "more ", "want ", "need ", "put ", "with ")


def _extract_added_dishes(message):
    """Pull dish names out of an 'add X and Y' tweak, without an LLM."""
    low = str(message or "").lower()
    for verb in _ADD_VERBS:
        idx = low.find(verb)
        if idx == -1:
            continue
        tail = low[idx + len(verb):]
        # Stop at a clause boundary so "add roti, not just egg" doesn't swallow
        # the negation.
        for stop in (" not ", " instead", " but ", ".", ";"):
            cut = tail.find(stop)
            if cut != -1:
                tail = tail[:cut]
        found = _normalize_constraints([{"dish_tag": tail, "min_count": 8}])
        if found:
            return found
    return []
