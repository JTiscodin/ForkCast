"""Nutrition ("stomach database") — dish -> per-serving nutrients + daily/weekly gaps.

Lookup order: canonical table below (keyword match on the dish name) ->
nutrition_ref cache -> one Gemini estimate (cached) -> kind default.
Every result carries `source` + `confidence`; the UI shows values as "~".

Units: kcal; protein/carbs/fat/fibre/sugar g; iron/calcium/sodium mg; b12/vitd mcg.
"""
import csv
import difflib
import pathlib
import json
import re

import gemini

KEYS = ("kcal", "protein", "carbs", "fat", "fibre",
        "iron", "b12", "vitd", "calcium", "sodium", "sugar")
MACROS = ("kcal", "protein", "carbs", "fat", "fibre")
MICROS = ("iron", "b12", "vitd", "calcium", "sodium", "sugar")
LIMITS = ("sodium", "sugar")   # targets are ceilings, not floors

# ICMR-NIN 2020 RDA, sedentary adult (rounded). sodium/sugar are upper limits.
RDA = {"kcal": 2000, "protein": 54, "carbs": 260, "fat": 55, "fibre": 30,
       "iron": 19, "b12": 2.5, "vitd": 15, "calcium": 1000,
       "sodium": 2000, "sugar": 25}

# shortcut: ~35 hand-compiled per-serving approximations in the spirit of
# IFCT 2017 / INDB, not a licensed import; replace with the INDB CSV when available.
# (kcal, protein, carbs, fat, fibre, iron, b12, vitd, calcium, sodium, sugar)
_T = {
    "masala dosa":   (390, 8, 55, 15, 4, 2.0, 0, 0, 40, 650, 3),
    "dosa":          (170, 4, 29, 4, 1, 1.0, 0, 0, 20, 300, 1),
    "idli":          (240, 8, 48, 1, 3, 1.5, 0, 0, 30, 450, 1),
    "vada":          (290, 9, 28, 16, 4, 1.8, 0, 0, 40, 450, 1),
    "upma":          (250, 6, 38, 8, 3, 1.5, 0, 0, 25, 450, 2),
    "poha":          (270, 5, 45, 8, 2, 4.0, 0, 0, 20, 400, 3),
    "paratha":       (330, 7, 42, 15, 5, 2.5, 0, 0, 40, 450, 1),
    "aloo paratha":  (360, 8, 50, 15, 5, 2.5, 0, 0, 40, 550, 2),
    "omelette":      (190, 13, 2, 14, 0, 1.8, 1.1, 1.8, 60, 350, 1),
    "egg bhurji":    (230, 14, 5, 17, 1, 2.0, 1.2, 2.0, 70, 450, 2),
    "boiled egg":    (155, 13, 1, 11, 0, 1.8, 1.1, 2.0, 55, 140, 1),
    "dal makhani":   (380, 14, 38, 19, 9, 4.0, 0.2, 0.1, 120, 750, 3),
    "dal tadka":     (260, 13, 34, 8, 8, 3.5, 0, 0, 60, 650, 2),
    "dal":           (230, 12, 32, 6, 8, 3.0, 0, 0, 50, 600, 2),
    "rajma":         (330, 15, 48, 9, 12, 5.0, 0, 0, 90, 700, 3),
    "chole":         (360, 14, 50, 12, 12, 4.5, 0, 0, 90, 750, 4),
    "khichdi":       (330, 12, 55, 7, 6, 2.5, 0, 0, 40, 550, 1),
    "paneer butter masala": (480, 18, 18, 38, 3, 1.5, 0.4, 0.2, 400, 850, 8),
    "palak paneer":  (360, 17, 14, 26, 5, 4.0, 0.4, 0.2, 420, 700, 4),
    "paneer":        (400, 18, 15, 30, 3, 1.5, 0.4, 0.2, 380, 750, 5),
    "chicken biryani": (650, 30, 75, 24, 3, 3.0, 0.6, 0.3, 60, 1100, 4),
    "veg biryani":   (520, 11, 80, 17, 5, 2.5, 0, 0, 60, 950, 4),
    "biryani":       (600, 22, 78, 21, 4, 2.8, 0.4, 0.2, 60, 1050, 4),
    "butter chicken": (520, 32, 14, 37, 2, 2.0, 0.6, 0.4, 80, 950, 7),
    "chicken curry": (400, 30, 10, 26, 2, 2.0, 0.5, 0.3, 50, 850, 4),
    "fish curry":    (330, 28, 8, 20, 2, 1.5, 2.5, 5.0, 90, 800, 3),
    "egg curry":     (330, 16, 10, 24, 2, 2.5, 1.2, 2.0, 80, 750, 4),
    "thali":         (750, 22, 105, 26, 12, 5.0, 0.3, 0.1, 250, 1400, 8),
    "roti":          (240, 8, 46, 3, 7, 2.6, 0, 0, 30, 300, 1),
    "naan":          (320, 9, 55, 7, 2, 2.5, 0.1, 0, 60, 550, 3),
    "rice":          (260, 5, 57, 1, 1, 0.5, 0, 0, 10, 10, 0),
    "curd":          (100, 5, 7, 5, 0, 0.2, 0.5, 0.1, 180, 60, 7),
    "lassi":         (220, 7, 30, 8, 0, 0.2, 0.6, 0.1, 250, 120, 26),
    "chaas":         (60, 3, 5, 2, 0, 0.1, 0.3, 0.1, 120, 300, 4),
    "fruit":         (90, 1, 22, 0, 3, 0.5, 0, 0, 20, 2, 16),
    "sprouts":       (150, 11, 22, 1, 7, 2.5, 0, 0, 40, 200, 2),
    "salad":         (80, 3, 12, 2, 4, 1.0, 0, 0, 40, 200, 6),
    "samosa":        (310, 5, 32, 18, 3, 1.5, 0, 0, 25, 450, 2),
    "pav bhaji":     (480, 11, 65, 19, 8, 3.0, 0.1, 0, 90, 1100, 9),
    "chaat":         (280, 7, 40, 10, 5, 2.0, 0, 0, 60, 800, 9),
    "milk":          (150, 8, 12, 8, 0, 0.1, 1.1, 0.1, 280, 110, 12),
    "makhana":       (120, 4, 20, 1, 3, 0.5, 0, 0, 20, 5, 0),
    "sambar":        (140, 7, 20, 4, 5, 2.0, 0, 0, 50, 600, 3),
    "rasam":         (70, 2, 10, 2, 2, 1.0, 0, 0, 20, 550, 2),
    "pongal":        (320, 9, 48, 10, 3, 1.5, 0.1, 0, 30, 500, 1),
    "uttapam":       (280, 8, 45, 8, 3, 1.5, 0, 0, 40, 450, 3),
    "aloo gobi":     (210, 5, 22, 12, 6, 1.5, 0, 0, 40, 550, 4),
    "bhindi":        (180, 4, 14, 12, 6, 1.0, 0, 0, 90, 450, 3),
    "mix veg":       (200, 5, 18, 12, 6, 1.5, 0, 0, 60, 600, 5),
    "baingan":       (190, 3, 16, 13, 7, 0.8, 0, 0, 30, 500, 6),
    "kadhi":         (220, 8, 18, 13, 2, 1.0, 0.3, 0.1, 180, 600, 5),
    "pulao":         (330, 6, 55, 9, 2, 1.0, 0, 0, 30, 450, 2),
    "curd rice":     (300, 8, 50, 7, 1, 0.6, 0.4, 0.1, 200, 400, 5),
    "fried rice":    (420, 9, 62, 15, 3, 1.5, 0.1, 0, 35, 900, 3),
    "noodles":       (450, 10, 65, 16, 3, 2.0, 0.1, 0, 30, 1100, 4),
    "momos":         (300, 10, 42, 9, 2, 1.5, 0.2, 0, 30, 700, 2),
    "chicken tikka": (280, 34, 6, 13, 1, 1.5, 0.4, 0.2, 40, 750, 2),
    "tandoori chicken": (380, 42, 6, 20, 1, 2.0, 0.6, 0.3, 40, 900, 2),
    "mutton curry":  (450, 30, 10, 32, 2, 3.5, 2.0, 0.1, 40, 900, 3),
    "keema":         (420, 28, 10, 30, 2, 3.5, 1.8, 0.1, 40, 850, 3),
    "prawn curry":   (320, 26, 10, 19, 2, 2.0, 1.0, 0.2, 120, 950, 3),
    "kulcha":        (300, 8, 50, 7, 2, 2.0, 0.1, 0, 50, 500, 3),
    "bhature":       (400, 8, 50, 19, 2, 2.0, 0, 0, 30, 450, 2),
    "pav":           (260, 8, 46, 4, 2, 2.0, 0, 0, 50, 450, 4),
    "oats":          (250, 9, 40, 6, 6, 3.0, 0, 0, 60, 350, 4),
    "sandwich":      (330, 11, 40, 14, 4, 2.0, 0.2, 0.1, 150, 750, 5),
    "dhokla":        (220, 8, 30, 7, 3, 1.5, 0, 0, 40, 650, 6),
    "tofu":          (180, 18, 4, 11, 1, 2.7, 0, 0, 350, 15, 1),
}

# Indian-menu spelling variants -> canonical word, applied before matching
_SYNONYMS = {"biriyani": "biryani", "briyani": "biryani", "panner": "paneer", "chana": "chole",
             "channa": "chole", "chapati": "roti", "chapathi": "roti", "phulka": "roti",
             "dahi": "curd", "yogurt": "curd", "yoghurt": "curd", "daal": "dal", "dhal": "dal",
             "makhni": "makhani", "murg": "chicken", "murgh": "chicken", "gosht": "mutton",
             "anda": "egg", "chawal": "rice", "subzi": "mix veg", "sabzi": "mix veg",
             "bhaji": "mix veg", "khichri": "khichdi", "parantha": "paratha", "poori": "bhature",
             "biriani": "biryani"}
# whole-dish aliases; before fuzzy match so "makhani" can't drift to "makhana"
_PHRASES = (("chicken makhani", "butter chicken"), ("paneer makhani", "paneer butter masala"),
            ("chole bhature", "chole"))

# fallback by dish_kind when nothing matches and Gemini is unavailable
_KIND_DEFAULT = {"meal": (450, 14, 60, 17, 5, 2.5, 0.2, 0.1, 80, 800, 4),
                 "snack": (250, 5, 30, 12, 3, 1.5, 0, 0, 30, 400, 4),
                 "sweet": (300, 4, 45, 12, 1, 1.0, 0.2, 0, 80, 80, 30),
                 "beverage": (120, 3, 18, 3, 0, 0.2, 0.2, 0, 100, 60, 15)}

# keyword -> canonical, longest first so "masala dosa" beats "dosa"
_CANON = sorted(_T, key=len, reverse=True)


def _vec(t):
    return dict(zip(KEYS, t))


def _canon_text(name):
    words = re.sub(r"[^a-z ]", " ", (name or "").lower()).split()
    t = " ".join(_SYNONYMS.get(w, w) for w in words)
    for a, b in _PHRASES:
        t = t.replace(a, b)
    return t


def retrieve(text, threshold=0.75):
    """Best canonical dish for a name that didn't substring-match, or None.

    Per canonical: share of its words found in the name, where a word counts if a
    name word is a close spelling (difflib >= 0.8, catches 'biriani', 'tadkaa').
    Every canonical word must be (fuzzily) present, so 'chicken' alone never
    pulls 'chicken biryani'.
    """
    words = text.split()
    if not words:
        return None
    best, best_s = None, 0.0
    for c in _CANON:
        cw = c.split()
        hits = sum(1 for w in cw if any(difflib.SequenceMatcher(None, w, x).ratio() >= 0.8 for x in words))
        s = hits / len(cw)
        # prefer the more specific (longer) canonical on ties
        if s >= threshold and (s > best_s or (s == best_s and len(c) > len(best or ""))):
            best, best_s = c, s
    return best if best_s == 1.0 else None


# Indian Nutrient Databank (INDB, 2024; github.com/lindsayjaacks/Indian-Nutrient-Databank-INDB-):
# 1,014 Indian recipes, per standard serving. Converted to data/indb.csv; no B12 column.
_INDB_PATH = pathlib.Path(__file__).parent / "data" / "indb.csv"
_STOP = {"with", "and", "of", "the", "a", "in", "style", "recipe", "home", "made"}
_PIECE_UNITS = {"idli", "dosa", "piece", "pieces", "roti", "chapati", "paratha", "puri", "poori",
                "vada", "samosa", "kachori", "slice", "bhatura", "naan", "kulcha", "pav", "laddu", "cutlet"}


def _words(text):
    return set(_canon_text(text).split()) - _STOP


def _load_indb():
    out = []
    try:
        with open(_INDB_PATH, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                vals = {k: float(r[k] or 0) for k in KEYS if k in r}
                if not vals.get("kcal"):
                    continue   # rows the source left without serving data
                vals.setdefault("b12", 0.0)
                name = r["food_name"]
                main = re.sub(r"\(.*?\)", " ", name)
                for alias in [main] + re.findall(r"\((.*?)\)", name):
                    w = _words(alias)
                    # a bracket note like "(with chicken)" is too generic to name a dish alone
                    if w and (alias is main or len(w) >= 2):
                        out.append((w, name, vals, (r.get("serving") or "").lower()))
    except OSError:
        pass   # data file missing: fall back to the built-in table
    return out


_INDB = None


def _indb_match(name):
    """Most specific INDB recipe whose every word appears in the dish name."""
    global _INDB
    if _INDB is None:
        _INDB = _load_indb()
    dish = _words(name)
    best = max((e for e in _INDB if e[0] <= dish), key=lambda e: len(e[0]), default=None)
    return best


def _pieces(name, unit):
    """Per-piece INDB rows ("1 idli") scale by the count in the menu name ("Idli (4 Pcs)")."""
    if unit not in _PIECE_UNITS:
        return 1
    m = re.search(r"(\d+)\s*(?:pcs|pc|pieces|nos|no|pav|piece)\b", name.lower()) or re.search(r"\((\d+)\)", name)
    return max(1, min(int(m.group(1)), 12)) if m else 1   # sides carry their own quantity


def lookup(conn, name, kind="meal", llm=True):
    """Per-serving nutrients for a dish name -> {nutrients, source, confidence}."""
    m = _indb_match(name)
    if m:
        k = _pieces(name, m[3])
        # shortcut: INDB is a home serving; restaurant portions run larger, upgrade with a per-kind factor
        return {"nutrients": {key: round(v * k, 2) for key, v in m[2].items()}, "source": "indb",
                "confidence": 0.8, "canonical": m[1].lower()}
    n = _canon_text(name)
    for c in _CANON:
        if c in n:
            return {"nutrients": _vec(_T[c]), "source": "ifct", "confidence": 0.7,
                    "canonical": c}
    c = retrieve(n)
    if c:
        return {"nutrients": _vec(_T[c]), "source": "ifct", "confidence": 0.55,
                "canonical": c}
    key = re.sub(r"[^a-z ]", "", n).strip()[:80]
    if conn is not None and key:
        row = conn.execute("SELECT * FROM nutrition_ref WHERE canonical=?", (key,)).fetchone()
        if row:
            return {"nutrients": json.loads(row["nutrients"]), "source": row["source"],
                    "confidence": row["confidence"], "canonical": key}
    est = _llm_estimate(name) if llm else None
    if est:
        res = {"nutrients": est, "source": "llm", "confidence": 0.4, "canonical": key}
    else:
        res = {"nutrients": _vec(_KIND_DEFAULT.get(kind, _KIND_DEFAULT["meal"])),
               "source": "default", "confidence": 0.2, "canonical": key}
    if conn is not None and key and res["source"] != "default":
        conn.execute("INSERT OR REPLACE INTO nutrition_ref VALUES (?,?,?,?)",
                     (key, json.dumps(res["nutrients"]), res["source"], res["confidence"]))
        conn.commit()
    return res


def _llm_estimate(name):
    if not gemini.has_key():
        return None
    txt = gemini.chat(
        f"Estimate nutrients for ONE typical Indian restaurant serving of: {name}. "
        f"Reply ONLY JSON with numeric keys {list(KEYS)} "
        "(kcal; g for protein/carbs/fat/fibre/sugar; mg iron/calcium/sodium; mcg b12/vitd).")
    m = re.search(r"\{.*\}", txt or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else None
        return {k: float(d[k]) for k in KEYS} if d else None
    except (ValueError, KeyError, TypeError):
        return None


def add(*vecs):
    return {k: round(sum(v.get(k, 0) for v in vecs), 1) for k in KEYS}


def targets(goal):
    t = dict(RDA)
    if goal == "lose":
        t["kcal"] = round(t["kcal"] * 0.85)
    elif goal == "gain":
        t["kcal"] = round(t["kcal"] * 1.15)
    elif goal == "high_protein":
        t["protein"] = round(t["protein"] * 1.5)
    return t


def gaps(today, week_avg, goal, remaining_slots):
    """Nutrient -> 0..1 shortfall still open.

    Macros steer by TODAY's running total, spread over the slots still ahead;
    micros by the 7-day rolling daily average. Limits never count as gaps.
    """
    t = targets(goal)
    out = {}
    for k in MACROS:
        out[k] = max(0.0, 1 - today.get(k, 0) / t[k]) if remaining_slots else 0.0
    for k in MICROS:
        if k not in LIMITS:
            out[k] = max(0.0, 1 - week_avg.get(k, 0) / t[k])
    return out


def gap_fit(nutrients, gap, goal, remaining_slots=1):
    """0..1: how much of the open gap one serving would close, minus limit overshoot."""
    t = targets(goal)
    share = 1 / max(1, remaining_slots)
    score, n = 0.0, 0
    for k, g in gap.items():
        if g <= 0 or k == "kcal":
            continue
        need = g * t[k] * (share if k in MACROS else 1 / 3)
        score += min(1.0, nutrients.get(k, 0) / need) * g
        n += 1
    penalty = sum(max(0.0, nutrients.get(k, 0) / t[k] - 0.4) for k in LIMITS)
    return max(0.0, score / max(1, n) - penalty)


def top_gap(gap):
    k = max((k for k in gap if k != "kcal"), key=lambda k: gap[k], default=None)
    return k if k and gap[k] > 0.25 else None
