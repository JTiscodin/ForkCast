"""Dish profiles — one structured description per dish name, the single source of
truth the daily planner's rules read instead of per-rule keyword lists.

A profile says what a dish IS, not what its name contains:
  canonical    plain standard name ("Kadchi Plain Rajma-Chawal" -> "rajma chawal")
  kind         meal | curry | bread | rice | side | snack | sweet | drink
               (curry = sabzi/dal/gravy: eaten WITH roti or rice)
  slots        meals it suits: breakfast | lunch | snack | dinner
  diet         veg | egg | nonveg
  onion_garlic True if it is likely NOT Jain-safe: onion, garlic, potato or other
               root vegetables (name kept for the stored schema)
  serves       people one portion feeds
  kcal, protein  rough per-portion estimate

Filled by Gemini in batches the first time a name is seen and stored forever in
SQLite, so a name costs one lookup ever. When Gemini is unavailable, a profile is
derived from the keyword rules (course.py) and NOT stored, so Gemini fills it later.
"""
import json
import re

import gemini

KINDS = ("meal", "curry", "bread", "rice", "side", "snack", "sweet", "drink")
SLOTS = ("breakfast", "lunch", "snack", "dinner")
DIETS = ("veg", "egg", "nonveg")
BATCH = 40

SCHEMA = """CREATE TABLE IF NOT EXISTS dish_profile (
    key        TEXT PRIMARY KEY,
    profile    TEXT NOT NULL,
    source     TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
)"""

_PROMPT = """You classify Indian food-delivery menu items for a single person's meal planner.
For EACH numbered item return one JSON object, in order, inside one JSON array. Keys:
"canonical": plain standard dish name, lowercase, no restaurant/size/count words (e.g. "rajma chawal", "chole bhature", "masala dosa").
"kind": one of meal|curry|bread|rice|side|snack|sweet|drink.
  meal = complete on its own (thali, biryani, dosa, rajma chawal, khichdi, combo with roti/rice, pav bhaji, sandwich, wrap, pizza).
  curry = sabzi, dal, gravy or kadhi that Indians eat WITH roti or rice (paneer butter masala, aloo gobi, dal makhani, chole, bhindi).
  bread = roti/naan/paratha/kulcha/puri sold alone. rice = plain/jeera rice alone.
  side = raita, salad, papad, chutney, salan, extra gravy. snack = samosa, maggi, fries, chaat, pakoda, momos plate.
"slots": meals it suits as a list from breakfast, lunch, snack, dinner (maggi -> ["snack"]; poha -> ["breakfast","snack"]; dal makhani -> ["lunch","dinner"]).
"diet": veg|egg|nonveg.
"onion_garlic": true if a normal restaurant version is NOT Jain-safe: contains onion, garlic, potato or another root vegetable (carrot, beetroot, ginger) — most gravies, sambar, biryani, pav bhaji, masala dosa (potato filling); false if plain (idli, plain dosa, curd rice, khakhra) or labelled Jain.
"serves": number of people one portion feeds (1 unless it says serves 2, family, party, bucket).
"kcal": rough integer per portion. "protein": rough grams integer per portion.
Reply with ONLY the JSON array.
Items:
"""


def key_of(name):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())).strip()[:120]


def ensure_table(conn):
    conn.execute(SCHEMA)


def profiles(conn, names, llm=True):
    """name -> profile for every name (stored, freshly profiled, or rule-derived)."""
    ensure_table(conn)
    keys = {n: key_of(n) for n in names if n}
    uniq = sorted(set(keys.values()))
    found = {}
    for i in range(0, len(uniq), 500):
        chunk = uniq[i:i + 500]
        q = "SELECT key, profile FROM dish_profile WHERE key IN (%s)" % ",".join("?" * len(chunk))
        found.update({r["key"]: json.loads(r["profile"]) for r in conn.execute(q, chunk)})
    missing = [k for k in uniq if k not in found]
    if missing and llm and gemini.has_key():
        by_key = {k: n for n, k in keys.items()}
        for i in range(0, len(missing), BATCH):
            batch = missing[i:i + BATCH]
            for k, prof in zip(batch, _ask([by_key[k] for k in batch])):
                if prof:
                    found[k] = prof
                    conn.execute("INSERT OR REPLACE INTO dish_profile (key, profile, source) VALUES (?,?,?)",
                                  (k, json.dumps(prof), "llm"))
        conn.commit()
    return {n: found.get(k) or rule_profile(n) for n, k in keys.items()}


def _ask(names):
    """One Gemini call for a batch -> list aligned with names (None where unusable)."""
    prompt = _PROMPT + "\n".join(f"{i + 1}. {n}" for i, n in enumerate(names))
    text = gemini.chat(prompt, system="You are a precise Indian cuisine classifier. Output JSON only.", timeout=45)
    m = re.search(r"\[.*\]", text or "", re.S)
    try:
        rows = json.loads(m.group(0)) if m else []
    except ValueError:
        rows = []
    out = [validate(r) for r in rows[:len(names)]]
    return out + [None] * (len(names) - len(out))


def validate(r):
    """Clamp a model row to the schema; None when it can't be trusted."""
    if not isinstance(r, dict) or r.get("kind") not in KINDS:
        return None
    slots = [s for s in (r.get("slots") or []) if s in SLOTS]
    try:
        return {
            "canonical": key_of(r.get("canonical") or "") or None,
            "kind": r["kind"],
            "slots": slots or (["lunch", "dinner"] if r["kind"] in ("meal", "curry") else ["snack"]),
            "diet": r.get("diet") if r.get("diet") in DIETS else "veg",
            "onion_garlic": bool(r.get("onion_garlic", True)),
            "serves": max(1, int(r.get("serves") or 1)),
            "kcal": max(0, int(r.get("kcal") or 0)),
            "protein": max(0, int(r.get("protein") or 0)),
        }
    except (TypeError, ValueError):
        return None


_COURSE_TO_KIND = {"complete": "meal", "curry": "curry", "bread": "bread", "staple": "rice", "side": "side"}


def rule_profile(name):
    """Keyword-rule fallback (course.py) when no stored or model profile exists."""
    from course import classify
    c = classify(name)
    kind = _COURSE_TO_KIND.get(c.course, "meal")
    if kind in ("meal", "side") and c.dish_kind in ("snack", "sweet"):
        kind = c.dish_kind
    elif c.dish_kind == "beverage":
        kind = "drink"
    n = name.lower()
    breakfast = any(w in n for w in ("poha", "upma", "idli", "dosa", "paratha", "uttapam", "chilla", "sandwich"))
    slots = (["breakfast", "snack"] if breakfast else ["lunch", "dinner"]) if kind in ("meal", "curry") else ["snack"]
    return {"canonical": None, "kind": kind, "slots": slots, "diet": "veg",
            "onion_garlic": "jain" not in n, "serves": 2 if re.search(r"serves\s*[2-9]|family|party|bucket", n) else 1,
            "kcal": 0, "protein": 0, "source": "rules"}
