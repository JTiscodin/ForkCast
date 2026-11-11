"""Daily personalized meals — docs/SPEC-daily-personalization.md.

One module, plain functions over a sqlite3 connection. app.py injects the two
live dependencies so this stays testable with fakes:
  dishes_fn(veg_only) -> [catalog.Dish]        restaurant candidates
  im_fn(query)        -> [normalized IM rows]  Instamart search (instamart.search)

Pipeline per slot (§3.2): candidates -> hard filters (weekday diet, allergies ->
excluded bucket, never-show, guardrail price, repetition) -> weighted score ->
role picks (usual / gap / new / budget, restaurant once per day) -> Instamart
gap add-on -> persist daily_menu + menu_card + excluded_card.
"""
import json
import math
import re
import threading
import urllib.parse
import urllib.request
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path

import dish_profile
import nutrition
import taste_profile as tp

_BUILD_LOCK = threading.RLock()   # re-entrant: today() holds it while calling build_day

SLOTS = ("breakfast", "lunch", "snack", "dinner")
DIETS = ("veg", "eggetarian", "nonveg", "jain", "vegan")
GOALS = ("lose", "maintain", "gain", "high_protein")
DEFAULT_WINDOWS = {"breakfast": ["07:00", "10:00"], "lunch": ["12:00", "15:00"],
                   "snack": ["16:30", "18:30"], "dinner": ["19:30", "22:30"]}
ROLES = ("usual", "gap", "new", "budget")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MAX_ORDER = 1000          # Swiggy guardrail: cart total must stay below this
REPEAT_DAYS = 3
HALF_LIFE_DAYS = 14       # signals fade over ~4 weeks
MOOD_HALF_LIFE_DAYS = 2   # "not today" is a mood, not a taste
# score = a*preference + b*gap_fit + c*weather_season + d*budget_fit + e*novelty
WEIGHTS = {"pref": 0.35, "gap": 0.25, "weather": 0.10, "budget": 0.15, "novelty": 0.15}
MEMORY_DIR = Path(__file__).parent / "data" / "taste"

# §3.4 starting values
EVENT_DELTAS = {"ordered": 3, "up": 3, "down": -3, "skip": -0.3,
                "not_today": -0.5, "off_plan": 2, "quiz": 3, "history": 2,
                "no_reorder": -0.5}   # passed over a dish you ordered before (spec 1.7 implicit)

# ---------------------------------------------------------------- profile

def _j(v, default):
    try:
        return json.loads(v) if isinstance(v, str) else (v if v is not None else default)
    except ValueError:
        return default


def get_profile(conn, user_id):
    r = conn.execute("SELECT * FROM user_profile WHERE user_id=?", (user_id,)).fetchone()
    if not r:
        return None
    p = dict(r)
    p["weekday_overrides"] = _j(p["weekday_overrides"], {})
    p["allergies"] = _j(p["allergies"], [])
    p["slots"] = _j(p["slots"], ["breakfast", "lunch", "dinner"])
    p["windows"] = {**DEFAULT_WINDOWS, **_j(p["windows"], {})}
    return p


def save_profile(conn, user_id, data):
    """Validate + upsert. Unknown values are rejected (trust boundary)."""
    cur = get_profile(conn, user_id) or {}
    p = {**{"diet_type": "veg", "weekday_overrides": {}, "allergies": [],
            "goal": "maintain", "slots": ["breakfast", "lunch", "dinner"],
            "windows": {}, "monthly_budget": 6000, "city": None, "mode": "dry_run"},
         **{k: v for k, v in cur.items() if k != "windows"},
         **{k: v for k, v in data.items() if v is not None}}
    if p["diet_type"] not in DIETS:
        raise ValueError(f"diet_type must be one of {DIETS}")
    if any(str(k) not in "0123456" or len(str(k)) != 1 or v not in DIETS
           for k, v in p["weekday_overrides"].items()):
        raise ValueError("weekday_overrides: {'0'..'6': diet_type}")
    if p["goal"] not in GOALS:
        raise ValueError(f"goal must be one of {GOALS}")
    if not p["slots"] or any(s not in SLOTS for s in p["slots"]):
        raise ValueError(f"slots must be a non-empty subset of {SLOTS}")
    if p["mode"] not in ("live", "dry_run"):
        raise ValueError("mode must be live or dry_run")
    if float(p["monthly_budget"]) <= 0:
        raise ValueError("monthly_budget must be positive")
    allergies = []
    for a in p["allergies"]:
        a = a if isinstance(a, dict) else {"name": str(a)}
        name = str(a.get("name", "")).strip().lower()
        if name:
            allergies.append({"name": name, "severe": bool(a.get("severe"))})
    windows = {k: v for k, v in {**(cur.get("windows") or {}), **(data.get("windows") or {})}.items()
               if k in SLOTS and DEFAULT_WINDOWS.get(k) != v}
    conn.execute(
        "INSERT OR REPLACE INTO user_profile (user_id, diet_type, weekday_overrides, "
        "allergies, goal, slots, windows, monthly_budget, city, mode, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))",
        (user_id, p["diet_type"], json.dumps({str(k): v for k, v in p["weekday_overrides"].items()}),
         json.dumps(allergies), p["goal"],
         json.dumps([s for s in SLOTS if s in p["slots"]]), json.dumps(windows),
         float(p["monthly_budget"]), p["city"], p["mode"]))
    conn.commit()
    return get_profile(conn, user_id)


def diet_on(profile, day):
    return profile["weekday_overrides"].get(str(day.weekday()), profile["diet_type"])


def _taste(profile, day, with_allergies):
    return tp.build_profile(profile["user_id"], {
        "veg_level": diet_on(profile, day),
        # goal is NOT a health_goal here: that hard-requires tags most dishes lack;
        # the goal steers through nutrient targets / gap_fit instead
        "allergies": [a["name"] for a in profile["allergies"]] if with_allergies else [],
    })

# ---------------------------------------------------------------- learning

def record(conn, user_id, type_, dimension, key, card_id=None, position=None, value=None):
    """Store one feedback event and apply it to pref_weight instantly."""
    if value is None:
        value = EVENT_DELTAS.get(type_, 0)
    conn.execute("INSERT INTO feedback_event (user_id, type, dimension, key, card_id, "
                 "position, value) VALUES (?,?,?,?,?,?,?)",
                 (user_id, type_, dimension, _norm(key), card_id, position, value))
    conn.commit()
    recompute(conn, user_id)


def record_card(conn, user_id, card, type_, position=None):
    """Fan a card-level signal out to dish (+full), cuisine + restaurant (+1/3)."""
    main = card["items"][0]
    base = EVENT_DELTAS.get(type_, 0)
    small = base / 3 if type_ in ("ordered", "off_plan") else base
    # learn on the standard dish name so one restaurant's rajma chawal teaches all of them
    record(conn, user_id, type_, "dish", main.get("canonical") or main["name"], card["id"], position, base)
    if type_ in ("ordered", "up", "down", "off_plan"):
        if main.get("cuisine"):
            record(conn, user_id, type_, "cuisine", main["cuisine"], card["id"], position, small)
        record(conn, user_id, type_, "restaurant", main.get("restaurant_name", ""),
               card["id"], position, small)


def recompute(conn, user_id, now=None):
    """Rebuild pref_weight from the event log with exponential decay.

    'never' is a permanent hard block; memory edits are explicit and don't decay.
    """
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)  # sqlite stores naive UTC
    acc, blocks = {}, set()
    for e in conn.execute("SELECT * FROM feedback_event WHERE user_id=?", (user_id,)):
        k = (e["dimension"], e["key"])
        if e["type"] == "never":
            blocks.add(k)
            continue
        if e["type"] == "unblock":
            blocks.discard(k)
            continue
        age = (now - datetime.fromisoformat(e["ts"])).total_seconds() / 86400
        hl = MOOD_HALF_LIFE_DAYS if e["type"] == "not_today" else HALF_LIFE_DAYS
        decay = 1.0 if e["type"] == "memory_edit" else 0.5 ** (max(0.0, age) / hl)
        acc[k] = acc.get(k, 0.0) + e["value"] * decay
    conn.execute("DELETE FROM pref_weight WHERE user_id=?", (user_id,))
    for k in set(acc) | blocks:
        conn.execute("INSERT INTO pref_weight VALUES (?,?,?,?,datetime('now'),?)",
                     (user_id, k[0], k[1], round(acc.get(k, 0.0), 3), int(k in blocks)))
    conn.commit()


def weights(conn, user_id):
    w, blocks = {}, set()
    for r in conn.execute("SELECT * FROM pref_weight WHERE user_id=?", (user_id,)):
        w[(r["dimension"], r["key"])] = r["weight"]
        if r["hard_block"]:
            blocks.add((r["dimension"], r["key"]))
    return w, blocks


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").lower()).strip()

# ---------------------------------------------------------------- memory

MEMORY_WHY = (("never", "You said never"), ("diet_plan", "From your diet plan"), ("memory_edit", "You set this"), ("ordered", "You ordered it here"),
              ("up", "You liked it"), ("down", "You disliked it"), ("quiz", "You picked it at setup"),
              ("history", "From your Swiggy orders"), ("off_plan", "You logged eating it"),
              ("not_today", "You said not today"), ("no_reorder", "You stopped ordering it"),
              ("skip", "You skipped it"))


def memory(conn, user_id):
    """'What we know about you' bullets, strongest first."""
    p = get_profile(conn, user_id)
    w, blocks = weights(conn, user_id)
    out = []
    # why we think so, in the user's terms (strongest source first)
    seen = {}
    for e in conn.execute("SELECT dimension, key, type FROM feedback_event WHERE user_id=?", (user_id,)):
        seen.setdefault((e["dimension"], e["key"]), set()).add(e["type"])
    for (dim, key), val in sorted(w.items(), key=lambda kv: -abs(kv[1])):
        if (dim, key) in blocks:
            text = f"Never show {key} ({dim})"
        elif abs(val) < 0.5:
            continue
        else:
            text = f"{'Likes' if val > 0 else 'Not keen on'} {key} ({dim})"
        out.append({"id": f"{dim}:{key}", "dimension": dim, "key": key,
                    "weight": round(val, 2), "blocked": (dim, key) in blocks, "text": text,
                    "why": next((label for t, label in MEMORY_WHY if t in seen.get((dim, key), ())), "")})
    facts = []
    if p:
        facts.append(f"Diet: {p['diet_type']}" + (
            " with weekday overrides " + ", ".join(
                f"{WEEKDAYS[int(d)]}={v}" for d, v in sorted(p["weekday_overrides"].items()))
            if p["weekday_overrides"] else ""))
        if p["allergies"]:
            facts.append("Allergies: " + ", ".join(
                a["name"] + (" (severe)" if a["severe"] else "") for a in p["allergies"]))
        facts.append(f"Goal: {p['goal']}; budget Rs {p['monthly_budget']:.0f}/month")
    return {"facts": facts, "bullets": out[:40]}


def edit_memory(conn, user_id, dimension, key, weight=None, delete=False, block=None):
    """Edits write back to weights as non-decaying events, so they round-trip."""
    w, blocks = weights(conn, user_id)
    k = (dimension, _norm(key))
    cur = w.get(k, 0.0)
    if delete:
        if k in blocks:
            record(conn, user_id, "unblock", *k, value=0)
        record(conn, user_id, "memory_edit", *k, value=-cur)
    elif block is True:
        record(conn, user_id, "never", *k, value=0)
    elif block is False:
        record(conn, user_id, "unblock", *k, value=0)
    elif weight is not None:
        record(conn, user_id, "memory_edit", *k, value=float(weight) - cur)
    write_memory_md(conn, user_id)
    return memory(conn, user_id)


def write_memory_md(conn, user_id):
    m = memory(conn, user_id)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"# Taste memory — user {user_id}", ""] + [f"- {f}" for f in m["facts"]]
    lines += [f"- {b['text']} [{b['weight']:+}]" for b in m["bullets"]]
    path = MEMORY_DIR / f"{int(user_id)}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

# ---------------------------------------------------------------- weather & season

COOLING = ("curd", "dahi", "raita", "lassi", "chaas", "buttermilk", "coconut", "cucumber",
           "kulfi", "fruit", "sattu", "salad")
WARM = ("soup", "dal", "khichdi", "paratha", "halwa", "biryani", "curry", "rasam",
        "thukpa", "makki", "tea", "pongal")
RAW_STREET = ("salad", "chaat", "pani puri", "golgappa", "bhel", "sev puri", "cut fruit")
# Rainy-day cravings: chai-pakora weather. Fried, hot, eaten with tea.
RAINY = ("pakora", "pakoda", "pakode", "bhajiya", "bhajji", "bhaji", "fritter", "samosa", "kachori", "vada",
         "bonda", "maggi", "momo", "soup", "bhutta", "corn", "chai", "tea")
_WEATHER_CACHE = {}


def _has(name, words):
    n = name.lower()
    return any(re.search(rf"\b{re.escape(w)}", n) for w in words)


def weather_reason(name, day, wx):
    """Plain-words reason shown on the card when the weather is why it ranks high."""
    s = season(day)
    if wx.get("rain") and _has(name, RAINY):
        return "Raining today: chai and pakora weather"
    if s == "monsoon" and _has(name, RAINY):
        return "Monsoon favourite, served hot"
    if (wx.get("hot") or s == "summer") and _has(name, COOLING):
        return "Hot day: something cooling"
    if s == "winter" and _has(name, WARM):
        return "Cold day: warm and filling"
    return None


def season(day):
    m = day.month
    return ("summer" if 3 <= m <= 6 else "monsoon" if 7 <= m <= 9
            else "winter" if m in (12, 1, 2) else "mild")


def weather(city, day):
    """{'hot': bool, 'rain': bool} from open-meteo (free, no key). {} on any failure."""
    if not city:
        return {}
    ck = (city.lower(), day.isoformat())
    if ck in _WEATHER_CACHE:
        return _WEATHER_CACHE[ck]
    out = {}
    try:
        g = _get("https://geocoding-api.open-meteo.com/v1/search?count=1&name="
                 + urllib.parse.quote(city))["results"][0]
        f = _get("https://api.open-meteo.com/v1/forecast?daily=temperature_2m_max,"
                 f"precipitation_sum&timezone=auto&latitude={g['latitude']}"
                 f"&longitude={g['longitude']}&start_date={day}&end_date={day}")["daily"]
        out = {"hot": f["temperature_2m_max"][0] >= 38, "rain": f["precipitation_sum"][0] >= 5}
    except Exception as e:  # noqa: BLE001 — weather is a soft signal only
        print(f"[daily] weather unavailable for {city}: {e}")
    _WEATHER_CACHE[ck] = out
    return out


def _get(url):
    with urllib.request.urlopen(url, timeout=6) as r:
        return json.loads(r.read())


def weather_score(name, day, wx):
    """-1..1 soft re-rank. Never a hard filter."""
    n = name.lower()
    s = season(day)
    cool, warm, raw = (any(w in n for w in ws) for ws in (COOLING, WARM, RAW_STREET))
    x = 0.0
    if s == "summer" or wx.get("hot"):
        x += cool - 0.5 * warm
    if s == "monsoon" or wx.get("rain"):
        x += 0.5 * warm - raw + (1.0 if _has(n, RAINY) else 0.0)
    if s == "winter":
        x += warm - 0.5 * cool
    return max(-1.0, min(1.0, x))

# ---------------------------------------------------------------- budget

def budget(conn, user_id, profile, day):
    """Daily soft cap = (monthly budget + last month's rollover - spent) / days left.

    Rollover: whatever last month's budget didn't spend carries into this month,
    if the user was on Forkcast that month. A virtual ledger: no money is held.
    """
    def spent_in(month):
        return conn.execute(
            "SELECT COALESCE(SUM(o.amount),0) FROM order_record o JOIN menu_card c ON c.id=o.card_id "
            "JOIN daily_menu m ON m.id=c.menu_id WHERE m.user_id=? AND substr(m.date,1,7)=? "
            "AND o.status='placed'", (user_id, month)).fetchone()[0]

    monthly = profile["monthly_budget"]
    spent = spent_in(day.strftime("%Y-%m"))
    prev = (day.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    was_here = conn.execute("SELECT 1 FROM daily_menu WHERE user_id=? AND substr(date,1,7)=? LIMIT 1",
                            (user_id, prev)).fetchone()
    rollover = max(0.0, monthly - spent_in(prev)) if was_here else 0.0
    nxt = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    days_left = (nxt - day).days
    days_in_month = (nxt - day.replace(day=1)).days
    remaining = monthly + rollover - spent
    return {"monthly": monthly, "spent": round(spent, 2), "rollover": round(rollover, 2),
            "remaining": round(remaining, 2), "days_left": days_left,
            # unspent so far = budget for the days already gone, minus what was spent
            "saved_so_far": round(max(0.0, monthly / days_in_month * (day.day - 1) - spent), 2),
            "daily_cap": round(max(0.0, remaining) / days_left, 2)}

# ---------------------------------------------------------------- nutrition state

def _logs(conn, user_id, start, end):
    return conn.execute("SELECT * FROM consumption_log WHERE user_id=? AND date>=? AND date<=?",
                        (user_id, start.isoformat(), end.isoformat())).fetchall()


def nutrition_state(conn, user_id, profile, day):
    today = nutrition.add(*[_j(r["nutrients"], {}) for r in _logs(conn, user_id, day, day)])
    week_rows = _logs(conn, user_id, day - timedelta(days=6), day)
    by_day = {}
    for r in week_rows:
        by_day.setdefault(r["date"], []).append(_j(r["nutrients"], {}))
    # unlogged days are unknown, not zero: average over logged days only
    week_avg = {k: round(sum(nutrition.add(*v)[k] for v in by_day.values()) / len(by_day), 1)
                for k in nutrition.KEYS} if by_day else {}
    logged = {r["slot"] for r in _logs(conn, user_id, day, day)}
    remaining = [s for s in profile["slots"] if s not in logged]
    gap = nutrition.gaps(today, week_avg, profile["goal"], len(remaining))
    return {"today": today, "week_avg": week_avg, "days_logged": len(by_day),
            "targets": nutrition.targets(profile["goal"]), "gap": gap,
            "remaining_slots": remaining}

# ---------------------------------------------------------------- candidates

IM_BUNDLES = {"breakfast": [("curd", "banana"), ("eggs", "bread"), ("poha", "fruit")],
              "snack": [("makhana", "chaas"), ("fruit", "curd"), ("sprouts", "lassi")]}
# What actually goes WITH a meal, per slot. An Indian lunch/dinner takes dahi or a
# kachumber salad on the side, never a milk carton; a gap no sensible side can
# close (vitamin D at dinner) gets no add-on rather than an odd one.
GAP_ADDON = {
    "breakfast": {"protein": "eggs", "calcium": "milk", "vitd": "milk", "b12": "milk",
                  "fibre": "banana", "iron": "dates"},
    "lunch": {"protein": "curd", "calcium": "curd", "b12": "curd", "fibre": "cucumber"},
    "dinner": {"protein": "curd", "calcium": "curd", "b12": "curd", "fibre": "cucumber"},
    "snack": {"fibre": "fruit", "iron": "dates", "protein": "roasted chana"},
}
GAP_LABEL = {"protein": "protein", "calcium": "calcium", "b12": "vitamin B12", "vitd": "vitamin D",
             "fibre": "fibre", "iron": "iron"}
ADDON_LABEL = {"curd": "dahi", "cucumber": "cucumber for a salad", "roasted chana": "roasted chana"}
_NON_VEG_WORDS = ("chicken", "mutton", "fish", "egg", "meat", "prawn", "keema", "omelette")
_ANIMAL = ("curd", "milk", "paneer", "ghee", "butter", "lassi", "chaas", "dahi", "cheese",
           "egg", "honey") + _NON_VEG_WORDS


def _dish_item(d):
    return {"source": "food", "id": d.dish_id, "name": d.name,
            "restaurant_id": d.restaurant_id, "restaurant_name": d.restaurant_name,
            "price": float(d.price), "image_url": d.image_url, "veg": bool(d.veg),
            "cuisine": d.cuisine, "kind": d.dish_kind, "rating": d.rating,
            "raw_variant": (d.variants or {}).get("_raw")}


def _im_item(r):
    name = r.get("name") or ""
    return {"source": "instamart", "id": r["id"], "name": name,
            "restaurant_id": "instamart", "restaurant_name": "Instamart",
            "price": float(r.get("price") or 0), "image_url": r.get("image_url") or "",
            "veg": not any(w in name.lower() for w in _NON_VEG_WORDS),
            "cuisine": "grocery", "kind": "snack", "rating": r.get("rating") or 4.0,
            "raw_variant": None}


ACC_QTY = {"bread": 2, "staple": 1}   # a curry comes with 2 roti or 1 rice (course.py)


def _qty(i):
    return i.get("quantity", 1)


def _total(items):
    return round(sum(i["price"] * _qty(i) for i in items), 2)


def _card_nutrition(conn, items, llm=True):
    """-> (nutrients, min confidence, sources) for a card, quantity-scaled."""
    def look(i):   # raw name keeps the piece count; the profiled standard name rescues odd menu names
        r = nutrition.lookup(conn, i["name"], i.get("kind", "meal"), llm=False)
        if r["source"] == "default" and i.get("canonical"):
            r = nutrition.lookup(conn, i["canonical"], i.get("kind", "meal"), llm=False)
        return r if r["source"] != "default" or not llm else nutrition.lookup(conn, i["name"], i.get("kind", "meal"))
    looks = [(look(i), _qty(i)) for i in items]
    nut = nutrition.add(*[{k: v * q for k, v in l["nutrients"].items()} for l, q in looks])
    return nut, min(l["confidence"] for l, _ in looks), sorted({l["source"] for l, _ in looks})


# live menus list sides as their own items (a Rs 9 "Biryani Raita"); never a card
SIDE_WORDS = ("raita", "salan", "chutney", "papad", "pickle", "achar", "extra ", "add on", "add-on",
              "addon", "dip", "sauce", "mayo", "plain curd", "onion salad", "green salad")
MIN_PRICE = {"snack": 30}   # meal slots default to MEAL_MIN_PRICE
MEAL_MIN_PRICE = 60


MIN_MEAL_KCAL = {"breakfast": 150, "lunch": 250, "dinner": 250}   # INDB home servings run small
from course import _DRINK_WORDS as SODA_WORDS, _contains_word  # noqa: E402  (one shared soda list)

# Instant noodles are a snack in an Indian day, never lunch or dinner.
SNACK_ONLY_WORDS = ("maggi", "instant noodles", "cup noodles")
# What an Indian breakfast usually is; nudged ahead of sandwiches/pastries.
INDIAN_BREAKFAST_WORDS = ("poha", "upma", "paratha", "idli", "dosa", "uttapam", "chilla", "cheela",
                          "thepla", "puri", "poori", "sabudana", "dhokla", "pongal", "appam",
                          "vada", "aloo", "bhurji", "omelette", "chole kulche", "besan")
INDIAN_BREAKFAST_BONUS = 0.12
# Restaurant gravies/masalas almost always carry onion and garlic, which names
# rarely mention. On a Jain day a restaurant main must be labelled "Jain" or be
# naturally Jain-safe; the roti/rice side is fine either way.
JAIN_SAFE_WORDS = ("jain", "idli", "plain dosa", "curd rice", "dahi chawal", "steamed rice",
                   "plain rice", "sabudana", "khakhra", "dhokla")
JAIN_LABEL_BONUS = 0.15
# a safe word doesn't vouch for a gravy riding along ("Rajma [Steamed Rice] Bowl")
GRAVY_WORDS = ("rajma", "chole", "chhole", "chana", "dal", "masala", "curry", "gravy", "makhani",
               "kadai", "kadhai", "paneer", "sabzi", "biryani", "kofta", "korma", "manchurian", "sambar")


_ALLERGY_ALIASES = {"tree nut": "tree_nut", "nuts": "tree_nut", "cashew": "tree_nut", "almond": "tree_nut",
                    "milk": "dairy", "lactose": "dairy", "wheat": "gluten", "prawn": "shellfish", "eggs": "egg"}


# Name words that mean an allergen is in the food. Used for anything without a dish
# profile: Instamart products, add-ons, and dishes the classifier hasn't seen yet.
ALLERGEN_WORDS = {
    "dairy": ("milk", "curd", "dahi", "paneer", "cheese", "butter", "ghee", "lassi", "chaas", "buttermilk",
              "yogurt", "yoghurt", "cream", "kheer", "raita", "makhani", "malai", "khoya", "mawa", "rabri"),
    "peanut": ("peanut", "groundnut", "moongfali", "mungfali"),
    "tree_nut": ("cashew", "kaju", "almond", "badam", "pista", "pistachio", "walnut", "akhrot", "hazelnut", "nuts"),
    "gluten": ("wheat", "atta", "maida", "roti", "chapati", "naan", "bread", "paratha", "pasta", "noodles",
               "suji", "rava", "kulcha", "bhatura", "puri", "sandwich", "burger", "pizza", "maggi"),
    "egg": ("egg", "eggs", "omelette", "omelet", "anda", "bhurji egg"),
    "soy": ("soy", "soya", "tofu"),
    "fish": ("fish", "surmai", "pomfret", "rohu", "tuna", "salmon"),
    "shellfish": ("prawn", "prawns", "shrimp", "crab", "lobster"),
    "sesame": ("sesame", "til", "tahini"),
}


def _name_allergen(name, allergies):
    """The user's allergy that this product NAME points to, or None."""
    words = set(re.findall(r"[a-z]+", (name or "").lower()))
    for a in allergies:
        key = _ALLERGY_ALIASES.get(a["name"], a["name"].replace(" ", "_"))
        if words & set(ALLERGEN_WORDS.get(key, ())) or a["name"].lower() in (name or "").lower():
            return a["name"]
    return None


def _allergy_check(items, allergies):
    """Profiled allergens vs the user's: (blocking allergen, note to restaurant).

    core -> blocked; removable -> kept with a "leave it out" note for the restaurant.
    """
    notes = []
    for a in allergies:
        want = _ALLERGY_ALIASES.get(a["name"], a["name"].replace(" ", "_"))
        for i in items:
            for x in i.get("allergens") or ():
                if x["name"] == want:
                    if x["how"] == "core" or i["source"] == "instamart":   # packaged food can't be altered
                        return a["name"], None
                    notes.append(f"No {a['name']} please, {'severe ' if a['severe'] else ''}allergy")
    return None, "; ".join(dict.fromkeys(notes)) or None


def _jain_ok(item):
    n = item["name"].lower()
    if "jain" in n:
        return True
    if "onion_garlic" in item:
        return not item["onion_garlic"]
    return "jain" in n or (any(w in n for w in JAIN_SAFE_WORDS) and not any(w in n for w in GRAVY_WORDS))


def _fits_slot(d, slot):
    n = f" {d.name.lower()} "
    if any(w in n for w in SNACK_ONLY_WORDS):
        return slot == "snack" and d.price >= MIN_PRICE["snack"]
    if any(w in n for w in SIDE_WORDS) or d.price < MIN_PRICE.get(slot, MEAL_MIN_PRICE):
        return False
    if re.search(r"serves\s*[2-9]|\bfor\s*[2-9]\b|family|party pack|bucket", n):
        return False   # single-person plan (spec 1.9): no sharing portions
    # bread/rice/sides never headline; a curry only with its accompaniment (see candidates)
    if d.course in ("bread", "staple", "side"):
        return False
    if slot == "snack":
        return d.dish_kind in ("snack", "beverage") or (d.meal_type == "breakfast" and d.price < 200)
    if d.course not in ("complete", "curry"):
        return False
    return d.dish_kind == "meal" and getattr(d, "main_meal_eligible", True) and (
        d.meal_type == slot or (slot != "breakfast" and d.meal_type in ("lunch", "dinner")))


def _im_safe(name, diet):
    n = name.lower()
    if diet == "vegan" and any(w in n for w in _ANIMAL):
        return False
    if diet in ("veg", "jain") and any(w in n for w in _NON_VEG_WORDS):
        return False
    if diet == "eggetarian" and any(w in n for w in _NON_VEG_WORDS if w not in ("egg", "omelette")):
        return False
    return not (diet == "jain" and any(w in n for w in tp._JAIN_BLOCKED_KEYWORDS))


def _fits_profile(d, slot, prof):
    """Slot fit from the dish profile (what the dish IS), plus the hard price/portion bars."""
    if d.price < MIN_PRICE.get(slot, MEAL_MIN_PRICE) or prof["serves"] > 1 or slot not in prof["slots"]:
        return False
    if slot == "snack":
        return prof["kind"] in ("snack", "meal")   # chai-time namkeen/tiffin, not dessert
    return prof["kind"] in ("meal", "curry")


def _side_qty(name, q):
    """How many of this roti/rice item one person needs with a curry (0 = don't use it).

    q is the per-piece default (2 roti, 1 rice). A pack already holds several
    pieces, so it is ordered once; a sharing pack (more than 4 pieces, or a
    tub/basket/family size) is never a one-person side.
    """
    n = name.lower()
    if not q or re.search(r"\b(tub|basket|bucket|family|party|jumbo|platter)\b", n):
        return 0
    m = (re.search(r"pack of\s*(\d+)", n) or re.search(r"(\d+)\s*[- ]?\s*(?:pcs|pc|pieces|piece|nos)\b", n)
         or re.search(r"\((\d+)\)", n))
    pieces = int(m.group(1)) if m else 1
    return 0 if pieces > 4 else 1 if pieces > 1 else q


def candidates(slot, day, profile, dishes_fn, im_fn, conn=None):
    """-> list of card drafts {items, price, kind} before filtering.

    With a connection, every rule reads the dish profile (dish_profile.py); without
    one (or for names never profiled) the keyword rules decide.
    """
    diet = diet_on(profile, day)
    pool = dishes_fn(diet in ("veg", "jain", "vegan"))
    profs = dish_profile.profiles(conn, [d.name for d in pool]) if conn is not None else {}

    def carb_qty(d):   # 2 roti or 1 rice per curry; 0 = not an accompaniment
        p = profs.get(d.name)
        if p and p.get("source") != "rules":
            q = {"bread": 2, "rice": 1}.get(p["kind"], 0)
        else:
            q = ACC_QTY.get(d.course, 0) if d.dish_kind == "meal" else 0
        return _side_qty(d.name, q)

    acc = {}   # restaurant -> cheapest roti/rice serving, so a curry is a whole meal
    for d in pool:
        q = carb_qty(d)
        if q:
            cur = acc.get(d.restaurant_id)
            if cur is None or d.price * q < cur.price * carb_qty(cur):
                acc[d.restaurant_id] = d
    rainy = season(day) == "monsoon" or bool(weather(profile.get("city"), day).get("rain"))
    tea = {}   # restaurant -> cheapest plain chai
    if rainy and slot == "snack":
        for d in pool:
            if _has(d.name, ("chai", "tea")) and not _has(d.name, ("iced", "cold", "lemon")) and d.price <= 80:
                if d.restaurant_id not in tea or d.price < tea[d.restaurant_id].price:
                    tea[d.restaurant_id] = d
    out = []
    for d in pool:
        p = profs.get(d.name)
        if p and p.get("source") != "rules":
            fits, needs_carb = _fits_profile(d, slot, p), p["kind"] == "curry"
        else:
            fits, needs_carb = _fits_slot(d, slot), d.course == "curry"
        if not fits:
            continue
        item = _dish_item(d)
        if p and p.get("source") != "rules":   # rule guesses must not override the Jain safe-list
            item.update(canonical=p.get("canonical"), onion_garlic=p["onion_garlic"], allergens=p.get("allergens"))
        items = [item]
        if slot == "snack" and rainy and _has(d.name, RAINY) and not _has(d.name, ("chai", "tea", "soup")):
            cup = tea.get(d.restaurant_id)
            if cup is not None:
                items.append({**_dish_item(cup), "quantity": 1, "side": True})
        if needs_carb:
            side = acc.get(d.restaurant_id)
            if side is None:
                continue
            sp = profs.get(side.name)
            items.append({**_dish_item(side), "quantity": carb_qty(side), "side": True,
                          **({"allergens": sp.get("allergens")} if sp and sp.get("source") != "rules" else {})})
        out.append({"items": items})
    for qa, qb in IM_BUNDLES.get(slot, ()):
        picked = []
        for q in (qa, qb):
            try:
                rows = [r for r in im_fn(q) if r.get("price") and _im_safe(r.get("name") or "", diet)
                        and not _name_allergen(f"{q} {r.get('name') or ''}", profile.get("allergies") or [])]
            except Exception as e:  # noqa: BLE001 — Instamart outage = restaurant-only cards
                print(f"[daily] instamart '{q}' failed: {e}")
                rows = []
            if rows:
                picked.append(_im_item(min(rows, key=lambda r: r["price"])))
        if len(picked) == 2:
            out.append({"items": picked})
    for c in out:
        c["price"] = _total(c["items"])
    return out

# ---------------------------------------------------------------- ranking

def _recent_names(conn, user_id, day, days):
    rows = conn.execute(
        "SELECT c.items FROM menu_card c JOIN daily_menu m ON m.id=c.menu_id "
        "WHERE m.user_id=? AND m.date>=? AND m.date<?",
        (user_id, (day - timedelta(days=days)).isoformat(), day.isoformat()))
    return {_norm(i["name"]) for r in rows for i in _j(r["items"], [])}


def _pref(item, w):
    n = _norm(item["name"])
    dish = _norm(item.get("canonical") or item["name"])
    s = (w.get(("dish", dish), 0) + (w.get(("dish", n), 0) if dish != n else 0) + w.get(("cuisine", _norm(item.get("cuisine"))), 0)
         + w.get(("restaurant", _norm(item.get("restaurant_name"))), 0)
         + w.get(("grocery", n), 0)
         + sum(v for (dim, k), v in w.items() if dim == "ingredient" and k and k in n))
    return s


def _blocked(item, blocks):
    n = _norm(item["name"])
    return any((dim == "dish" and k in (n, _norm(item.get("canonical")))) or (dim == "ingredient" and k in n)
               or (dim == "restaurant" and k == _norm(item.get("restaurant_name")))
               or (dim == "cuisine" and k == _norm(item.get("cuisine")))
               for dim, k in blocks)


def filter_and_score(conn, user_id, profile, day, slot, drafts, ctx):
    """Hard filters + score. Returns (kept, excluded). Shared with the chat agent."""
    diet_only = _taste(profile, day, with_allergies=False)
    with_allergy = _taste(profile, day, with_allergies=True)
    kept, excluded = [], []
    for c in drafts:
        if c["price"] >= MAX_ORDER:
            continue
        items = c["items"]
        if any(_blocked(i, ctx["blocks"]) for i in items):
            continue
        food = [i for i in items if i["source"] == "food"]
        if any(not tp.adheres_to_diet(_as_dish(i), diet_only) for i in food):
            continue
        if diet_on(profile, day) == "jain" and any(not _jain_ok(i) for i in food if not i.get("side")):
            continue
        if any(not _im_safe(i["name"], diet_on(profile, day)) for i in items):
            continue
        hit, note = _allergy_check(items, profile["allergies"])
        if hit is None:   # items without a profile (Instamart, unseen dishes): judge by name
            bare = [i for i in items if i.get("allergens") is None]
            hit = next((a for a in (_name_allergen(i["name"], profile["allergies"]) for i in bare) if a), None) \
                or next((a for a in (tp.allergy_blocked(_as_dish(i), with_allergy) for i in bare) if a), None)
        if note:
            items = [{**items[0], "note": note}] + items[1:]
            c = {**c, "items": items}
        # llm=False: hundreds of candidates; only the few persisted cards get an estimate
        nut, conf, _ = _card_nutrition(conn, items, llm=False)
        c = {**c, "nutrients": {**nut, "confidence": conf}}
        # a meal must be a meal: one idli is not lunch (measured, not guessed from the name)
        if nut.get("kcal", 0) < MIN_MEAL_KCAL.get(slot, 0):
            continue
        # soft-drink combos ("Nachos + Coke") are junk for a health-aware planner
        if any(_contains_word(i["name"].lower(), w) for i in items for w in SODA_WORDS):
            continue
        if hit:
            excluded.append({**c, "allergen_hit": hit})
            continue
        main = items[0]
        pref_raw = _pref(main, ctx["w"])
        parts = {
            "pref": math.tanh(pref_raw / 3) * 0.5 + 0.5,
            "gap": nutrition.gap_fit(nut, ctx["gap"], profile["goal"], ctx["remaining"]),
            "weather": (weather_score(" ".join(i["name"] for i in items), day, ctx["wx"]) + 1) / 2,
            "budget": 1.0 if c["price"] <= ctx["cap"] else max(0.0, 1 - (c["price"] - ctx["cap"]) / max(ctx["cap"], 1)),
            "novelty": 0.0 if _norm(main["name"]) in ctx["seen14"] else 1.0,
        }
        c["parts"] = parts
        c["pref_raw"] = pref_raw
        c["score"] = round(sum(WEIGHTS[k] * v for k, v in parts.items()), 4)
        if slot == "breakfast" and any(w in main["name"].lower() for w in INDIAN_BREAKFAST_WORDS):
            c["score"] = round(c["score"] + INDIAN_BREAKFAST_BONUS, 4)
        if "jain" in main["name"].lower() and diet_on(profile, day) == "jain":
            c["score"] = round(c["score"] + JAIN_LABEL_BONUS, 4)
        c["repeat"] = _norm(main["name"]) in ctx["recent"]
        c["over_cap"] = c["price"] > ctx["cap"]
        kept.append(c)
    return kept, excluded


def _as_dish(i):
    from types import SimpleNamespace
    return SimpleNamespace(name=i["name"], veg=i["veg"], dish_kind=i.get("kind", "meal"),
                           health_tags=(), satiety=None)


def context(conn, user_id, profile, day):
    w, blocks = weights(conn, user_id)
    ns = nutrition_state(conn, user_id, profile, day)
    return {"w": w, "blocks": blocks, "gap": ns["gap"], "remaining": len(ns["remaining_slots"]) or 1,
            "wx": weather(profile.get("city"), day),
            "cap": budget(conn, user_id, profile, day)["daily_cap"] or 1,
            "recent": _recent_names(conn, user_id, day, REPEAT_DAYS),
            "seen14": _recent_names(conn, user_id, day, 14)}


_NOISE_WORDS = {"plain", "special", "classic", "regular", "full", "half", "pcs", "pc", "the", "and", "with"}


def _dish_words(name):
    return set(re.findall(r"[a-z]+", name.lower())) - _NOISE_WORDS


def _same_dish(name, used_names):
    """Live menus rename one dish many ways ("Rajma chawal" / "Kadchi Plain Rajma-Chawal",
    "Chole Bhature" / "Chole Bhature(2 Pcs)"): same dish when one name's words all
    appear in the other. Needs 2+ words so a bare "Paneer" can't swallow everything."""
    w = _dish_words(name)
    for u in used_names:
        small, big = sorted((w, _dish_words(u)), key=len)
        if small == big or (len(small) >= 2 and small <= big):
            return True
    return False


def _main_name(items):
    """Dedupe key: the headline dish; an Instamart bundle is all its items (no restaurant main)."""
    if items and items[0]["source"] == "instamart":
        return _norm(" + ".join(i["name"] for i in items if not i.get("addon")))
    return _norm(items[0].get("canonical") or items[0]["name"]) if items else ""


def assign_roles(kept, used_restaurants, used_names=None):
    """Best card per role; a restaurant appears at most once per day (all slots).

    The spec says once per day, but an empty slot is worse: only when a slot would
    get fewer than 3 cards do remaining roles reuse a restaurant, and the card says so.
    """
    picks = []
    used_names = set() if used_names is None else used_names

    def take(role, pool, key, reason, reuse=False):
        if any(r == role for _, (r, _w) in picks):
            return
        for c in sorted(pool, key=key):
            rid = c["items"][0]["restaurant_id"]
            repeat = rid != "instamart" and rid in used_restaurants
            name = _main_name(c["items"])
            if (repeat and not reuse) or any(c is p for p, _ in picks) or _same_dish(name, used_names):
                continue
            used_names.add(name)
            if rid != "instamart":
                used_restaurants.add(rid)
            why = reason(c) + (" (restaurant repeats today: few options nearby)" if repeat else "")
            picks.append((c, (role, why)))
            return

    fresh = [c for c in kept if not c["repeat"]]
    liked = [c for c in kept if c["pref_raw"] > 0] or fresh   # cold start: best overall
    roles = [
        ("usual", liked, lambda c: -(c["pref_raw"] + c["score"]),
         lambda c: "You've liked this before" if c["pref_raw"] > 0 else "Top match for your taste"),
        ("gap", fresh, lambda c: -c["parts"]["gap"], lambda c: "Closes today's nutrient gap"),
        ("new", [c for c in fresh if c["parts"]["novelty"]], lambda c: -c["score"],
         lambda c: "Something you haven't had lately"),
        ("budget", [c for c in fresh if (c["items"][0].get("rating") or 4) >= 3.8],
         lambda c: c["price"], lambda c: "Cheapest that still rates well"),
    ]
    for r in roles:
        take(*r)
    if len(picks) < 3:
        for r in roles:
            take(*r, reuse=True)
    # breakfast/snack: a role nothing else filled goes to the best Instamart bundle (spec 1.1)
    bundles = [c for c in fresh if c["items"][0]["source"] == "instamart"]
    if bundles and not any(c["items"][0]["source"] == "instamart" for c, _ in picks):
        for role, _pool, key, reason in roles:
            take(role, bundles, key, reason)
    order_ = [r[0] for r in roles]
    picks.sort(key=lambda p: order_.index(p[1][0]))
    return picks


def _addon(conn, profile, day, slot, card, gap, im_fn, cache):
    """Instamart side that suits the slot and closes the biggest remaining gap it can."""
    if any(i["source"] == "instamart" for i in card["items"]):
        return None
    targets = nutrition.targets(profile["goal"])
    after = {k: max(0.0, g - card["nutrients"].get(k, 0) / targets[k]) for k, g in gap.items()}
    diet = diet_on(profile, day)
    names = " ".join(i["name"].lower() for i in card["items"])
    for g in sorted((k for k in after if after[k] > 0.25 and k != "kcal"), key=lambda k: -after[k]):
        q = GAP_ADDON.get(slot, {}).get(g)
        if not q:
            continue
        if diet == "vegan" and q in ("curd", "milk", "eggs"):
            q = "tofu" if g == "protein" else None
        elif diet in ("veg", "jain") and q == "eggs":
            q = "paneer"
        if not q or q in names or (q == "curd" and any(w in names for w in ("dahi", "raita", "curd", "lassi"))):
            continue   # already on the plate (curd rice + dahi) or no fit for this diet
        if q not in cache:
            try:
                rows = [r for r in im_fn(q) if r.get("price") and _im_safe(r.get("name") or "", diet)
                        and not _name_allergen(f"{q} {r.get('name') or ''}", profile.get("allergies") or [])]
            except Exception:  # noqa: BLE001 — add-on is optional
                rows = []
            cache[q] = _im_item(min(rows, key=lambda r: r["price"])) if rows else None
        if cache[q]:
            return {**cache[q], "addon": True,
                    "addon_reason": f"add {ADDON_LABEL.get(q, q)} for {GAP_LABEL.get(g, g)}"}
    return None


def build_day(*args, **kwargs):
    """Serialised: every path that builds menus (today, regenerate, nightly) takes the same lock."""
    with _BUILD_LOCK:
        return _build_day(*args, **kwargs)


def _build_day(conn, user_id, day, dishes_fn, im_fn, slots=None):
    """Generate (or regenerate) menus for every active slot of `day`."""
    profile = get_profile(conn, user_id)
    if not profile:
        raise ValueError("no profile — finish onboarding first")
    # the slots being rebuilt don't count as "used": their old cards are about to go
    used, used_names = _used_today(conn, user_id, day, exclude_slots=slots or profile["slots"])
    addon_cache = {}
    severe = [a["name"] for a in profile["allergies"] if a["severe"]]
    for slot in slots or profile["slots"]:
        if _ordered(conn, user_id, day, slot):
            continue   # never replace a slot the user already ordered
        ctx = context(conn, user_id, profile, day)
        drafts = candidates(slot, day, profile, dishes_fn, im_fn, conn)
        kept, excluded = filter_and_score(conn, user_id, profile, day, slot, drafts, ctx)
        picks = assign_roles(kept, used, used_names)
        # keep old cards only when NOTHING was fetched (outage); if the rules
        # removed everything, stale cards would break them (e.g. a Jain day)
        if not dishes_fn(diet_on(profile, day) in ("veg", "jain", "vegan")) and conn.execute(
                "SELECT 1 FROM menu_card c JOIN daily_menu m ON m.id=c.menu_id "
                "WHERE m.user_id=? AND m.date=? AND m.slot=?", (user_id, day.isoformat(), slot)).fetchone():
            continue
        conn.execute("DELETE FROM daily_menu WHERE user_id=? AND date=? AND slot=?",
                     (user_id, day.isoformat(), slot))
        mid = conn.execute("INSERT INTO daily_menu (user_id, date, slot) VALUES (?,?,?)",
                           (user_id, day.isoformat(), slot)).lastrowid
        # one add-on per slot, offered on the gap card first: on every card it's noise
        addon_for = next((c for c, (r, _) in picks if r == "gap"), picks[0][0] if picks else None)
        for pos, (c, (role, why)) in enumerate(picks):
            wr = weather_reason(" ".join(i["name"] for i in c["items"]), day, ctx["wx"])
            reasons = [wr, why] if wr else [why]
            add = _addon(conn, profile, day, slot, c, ctx["gap"], im_fn, addon_cache) if c is addon_for else None
            items = list(c["items"])
            if add and c["price"] + add["price"] < MAX_ORDER:
                items.append(add)
                reasons.append(add["addon_reason"])
            if c["over_cap"]:
                reasons.append(f"Above today's soft cap of Rs {ctx['cap']:.0f}")
            if items[0].get("note"):
                reasons.append(f"We'll ask the restaurant: {items[0]['note']}")
            elif severe and items[0].get("allergens") is None:   # unprofiled: can't tell, so ask
                reasons.append("Severe allergy: check the pack label" if items[0]["source"] == "instamart"
                               else "Severe allergy: confirm with restaurant")
            nut, conf, sources = _card_nutrition(conn, items)
            conn.execute(
                "INSERT INTO menu_card (menu_id, role, position, items, price, nutrients, score, reasons) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (mid, role, pos, json.dumps(items), _total(items),
                 json.dumps({**nut, "confidence": conf, "source": sources}),
                 c["score"], json.dumps(reasons)))
        # one row per dish: the same poha from five restaurants is one hidden item, not five
        hidden = {}
        for c in sorted(excluded, key=lambda c: -c.get("score", 0)):
            hidden.setdefault(_norm(c["items"][0].get("canonical") or c["items"][0]["name"]), c)
        for c in list(hidden.values())[:5]:
            conn.execute("INSERT INTO excluded_card (menu_id, items, allergen_hit) VALUES (?,?,?)",
                         (mid, json.dumps(c["items"]), c["allergen_hit"]))
        conn.commit()


def _used_today(conn, user_id, day, exclude_slots=None):
    """(restaurant ids, dish names) already on other slots' cards today."""
    rids, names = set(), set()
    for r in conn.execute("SELECT m.slot, c.items FROM menu_card c JOIN daily_menu m ON m.id=c.menu_id "
                          "WHERE m.user_id=? AND m.date=?", (user_id, day.isoformat())):
        if exclude_slots and r["slot"] in exclude_slots:
            continue
        items = _j(r["items"], [])
        if items and items[0]["restaurant_id"] != "instamart":
            rids.add(items[0]["restaurant_id"])
        names.add(_main_name(items))
    return rids, names


def _ordered(conn, user_id, day, slot):
    return conn.execute(
        "SELECT 1 FROM order_record o JOIN menu_card c ON c.id=o.card_id JOIN daily_menu m ON "
        "m.id=c.menu_id WHERE m.user_id=? AND m.date=? AND m.slot=? AND o.status IN "
        "('placed','dry_run')", (user_id, day.isoformat(), slot)).fetchone() is not None

# ---------------------------------------------------------------- view

def _card(r):
    c = dict(r)
    for k, d in (("items", []), ("nutrients", {}), ("reasons", [])):
        c[k] = _j(c[k], d)
    c["deliveries"] = len({i["source"] for i in c["items"]})
    return c


def get_card(conn, card_id):
    r = conn.execute("SELECT c.*, m.user_id, m.slot, m.date FROM menu_card c JOIN daily_menu m "
                     "ON m.id=c.menu_id WHERE c.id=?", (card_id,)).fetchone()
    return _card(r) if r else None


def today(conn, user_id, day, now, dishes_fn, im_fn, stock_fn=None):
    """Today screen. Builds missing menus; replaces slots whose cards went out of stock.

    stock_fn(item) -> True (orderable) | False (sold out / closed) | None (unknown).
    Rechecked at most every RECHECK_MIN per slot; unknown never triggers a rebuild.
    """
    profile = get_profile(conn, user_id)
    if not profile:
        return None
    # One build at a time: the page asks for today twice on load, and two builds
    # writing at once ended in "database is locked". The second caller waits, then
    # finds the menus fresh and builds nothing.
    with _BUILD_LOCK:
        stale = [s for s in profile["slots"]
                 if not _menu_fresh(conn, user_id, day, s)
                 or (stock_fn and not _ordered(conn, user_id, day, s)
                     and _gone(conn, user_id, day, s, stock_fn))]
        if stale:
            build_day(conn, user_id, day, dishes_fn, im_fn, slots=stale)
    slots = []
    for s in profile["slots"]:
        m = conn.execute("SELECT * FROM daily_menu WHERE user_id=? AND date=? AND slot=?",
                         (user_id, day.isoformat(), s)).fetchone()
        cards = [_card(r) for r in conn.execute(
            "SELECT * FROM menu_card WHERE menu_id=? ORDER BY position", (m["id"],))] if m else []
        exc = [{"items": _j(r["items"], []), "allergen_hit": r["allergen_hit"], "id": r["id"]}
               for r in conn.execute("SELECT * FROM excluded_card WHERE menu_id=?", (m["id"],))] if m else []
        order = conn.execute(
            "SELECT o.* FROM order_record o JOIN menu_card c ON c.id=o.card_id WHERE c.menu_id=? "
            "AND o.status IN ('placed','dry_run') ORDER BY o.id DESC LIMIT 1",
            (m["id"],)).fetchone() if m else None
        logged = conn.execute("SELECT 1 FROM consumption_log WHERE user_id=? AND date=? AND slot=?",
                              (user_id, day.isoformat(), s)).fetchone()
        end = profile["windows"][s][1]
        slots.append({"slot": s, "window": profile["windows"][s], "cards": cards,
                      "excluded": exc, "ordered": dict(order) if order else None,
                      "nudge": bool(now.strftime("%H:%M") > end and not logged
                                    and day == now.date())})
    return {"date": day.isoformat(), "diet": diet_on(profile, day), "season": season(day),
            "weather": weather(profile.get("city"), day), "profile": profile,
            "budget": budget(conn, user_id, profile, day),
            "nutrition": nutrition_state(conn, user_id, profile, day), "slots": slots}


RECHECK_MIN = 30


def _gone(conn, user_id, day, slot, stock_fn):
    """True when a card's main dish is confirmed unorderable. Throttled per slot.

    Not "missing from today's search pool": live search results vary per fetch, so
    absence proves nothing — only an explicit sold-out/closed answer counts.
    """
    m = conn.execute("SELECT * FROM daily_menu WHERE user_id=? AND date=? AND slot=?",
                     (user_id, day.isoformat(), slot)).fetchone()
    last = datetime.fromisoformat(m["refreshed_at"] or m["generated_at"])
    # generated_at/refreshed_at are naive UTC (sqlite datetime('now'))
    if (datetime.now(timezone.utc).replace(tzinfo=None) - last).total_seconds() < RECHECK_MIN * 60:
        return False
    conn.execute("UPDATE daily_menu SET refreshed_at=datetime('now') WHERE id=?", (m["id"],))
    conn.commit()
    for r in conn.execute("SELECT items FROM menu_card WHERE menu_id=? AND role!='chat'", (m["id"],)):
        main = _j(r["items"], [{}])[0]
        if main.get("source") == "food" and stock_fn(main) is False:
            return True
    return False


def _menu_fresh(conn, user_id, day, slot):
    return conn.execute("SELECT 1 FROM daily_menu WHERE user_id=? AND date=? AND slot=?",
                        (user_id, day.isoformat(), slot)).fetchone() is not None

# ---------------------------------------------------------------- consumption

def log_food(conn, user_id, day, slot, source, names):
    """Off-app food / nudge answer -> consumption_log (+ off_plan signal per dish)."""
    if slot not in SLOTS:
        raise ValueError(f"slot must be one of {SLOTS}")
    looks = [nutrition.lookup(conn, n) for n in names]
    nut = nutrition.add(*[l["nutrients"] for l in looks])
    conf = min((l["confidence"] for l in looks), default=1.0)
    conn.execute("INSERT INTO consumption_log (user_id, date, slot, source, items, nutrients, "
                 "confidence) VALUES (?,?,?,?,?,?,?)",
                 (user_id, day.isoformat(), slot, source, json.dumps(names), json.dumps(nut), conf))
    conn.commit()
    for n in names:
        record(conn, user_id, "off_plan", "dish", n)
    return {"nutrients": nut, "confidence": conf}


def parse_food_text(text):
    """'had dal and 2 roti at home' -> ['dal', 'roti', 'roti']."""
    t = re.sub(r"\b(i|had|ate|have|at|home|for|my|some|a|an|the|just|today|breakfast|lunch|dinner|snack)\b",
               " ", text.lower())
    out = []
    for part in re.split(r",| and | with |&|\+", t):
        part = part.strip(" .!")
        m = re.match(r"(\d+)\s+(.*)", part)
        qty, name = (int(m.group(1)), m.group(2)) if m else (1, part)
        if name:
            out += [re.sub(r"\s+", " ", name).strip()] * min(qty, 6)
    return out

# ---------------------------------------------------------------- ordering

def order(conn, user_id, card_id, food_exec, im_client, address_id, confirm=False, preview=False):
    # confirm must come from a user click (the HTTP order endpoint), never from the agent
    """One tap -> one or two orders (restaurant + Instamart). Honours profile.mode.

    preview=True builds the real carts and returns Swiggy's payable totals without
    ordering or recording anything: the summary a live order is confirmed against.
    """
    card = get_card(conn, card_id)
    if not card or card["user_id"] != user_id:
        raise ValueError("no such card")
    if not confirm:
        raise ValueError("confirm required")
    profile = get_profile(conn, user_id)
    dry = preview or profile["mode"] != "live"
    rec = (lambda *a, **k: _result(*a, **k)) if preview else (lambda *a, **k: _rec(conn, *a, **k))
    if card["price"] >= MAX_ORDER:
        raise ValueError(f"order total must stay under Rs {MAX_ORDER}")
    if _ordered(conn, user_id, _date.fromisoformat(card["date"]), card["slot"]):
        raise ValueError("this slot is already ordered")
    results = []
    food = [i for i in card["items"] if i["source"] == "food"]
    groc = [i for i in card["items"] if i["source"] == "instamart"]
    if food:
        f = food[0]
        try:
            r = food_exec.place(f["id"], f["restaurant_id"], _total(food),
                                raw_variant=f.get("raw_variant"), dry_run=dry, note=f.get("note"),
                                extra_items=[{"id": i["id"], "quantity": _qty(i),
                                              "raw_variant": i.get("raw_variant")} for i in food[1:]])
            results.append(rec(card_id, "food", r.get("order_id"), r["status"] if r["status"] != "confirmed" else "placed",
                                dry, r.get("amount") or _total(food), r.get("eta_min")))
        except Exception as e:  # noqa: BLE001 — fall back to the Swiggy app
            results.append(rec(card_id, "food", None, "failed", dry, 0, None, str(e),
                                "https://www.swiggy.com/search?query=" + urllib.parse.quote(f["name"])))
    if groc:
        amt = _total(groc)
        try:
            if im_client is None:
                oid, st = (None if dry else f"IM-MOCK-{card_id}"), ("dry_run" if dry else "placed")
            else:
                im_client.update_cart(address_id, [{"spinId": i["id"], "quantity": _qty(i)} for i in groc])
                if dry:
                    oid, st = None, "dry_run"
                else:
                    res = im_client.checkout(address_id)
                    data = res.get("data") or res
                    oid, st = str(data.get("orderId") or data.get("order_id") or "IM-?"), "placed"
            results.append(rec(card_id, "instamart", oid, st, dry, amt, 15))
        except Exception as e:  # noqa: BLE001
            results.append(rec(card_id, "instamart", None, "failed", dry, 0, None, str(e),
                                "https://www.swiggy.com/instamart"))
    ok = [r for r in results if r["status"] != "failed"]
    if preview:
        return {"card_id": card_id, "mode": "preview", "orders": results, "logged": None}
    if ok:
        log = log_food_items(conn, user_id, card)
        record_card(conn, user_id, card, "ordered", card["position"])
        for other in conn.execute("SELECT * FROM menu_card WHERE menu_id=? AND id!=?",
                                  (card["menu_id"], card_id)).fetchall():
            oc = _card(other)
            record_card(conn, user_id, oc, "skip", other["position"])
            m = oc["items"][0]
            key = _norm(m.get("canonical") or m["name"])
            if conn.execute("SELECT 1 FROM feedback_event WHERE user_id=? AND type='ordered' AND dimension='dish' "
                            "AND key=?", (user_id, key)).fetchone():
                record(conn, user_id, "no_reorder", "dish", key, other["id"], other["position"])
    else:
        log = None
    return {"card_id": card_id, "mode": "dry_run" if dry else "live", "orders": results,
            "logged": log}


def log_food_items(conn, user_id, card):
    # dry-run orders also log consumption so the demo's rings move; flagged by source
    conn.execute("INSERT INTO consumption_log (user_id, date, slot, source, items, nutrients, "
                 "confidence) VALUES (?,?,?,?,?,?,?)",
                 (user_id, card["date"], card["slot"], "app_order",
                  json.dumps([i["name"] for i in card["items"]]),
                  json.dumps({k: v for k, v in card["nutrients"].items() if k in nutrition.KEYS}),
                  card["nutrients"].get("confidence", 0.5)))
    conn.commit()
    return True


def _rec(conn, card_id, platform, oid, status, dry, amount, eta, error=None, fallback=None):
    conn.execute("INSERT INTO order_record (card_id, platform, order_id, status, mode, amount) "
                 "VALUES (?,?,?,?,?,?)", (card_id, platform, oid, status,
                                          "dry_run" if dry else "live", amount))
    conn.commit()
    return _result(card_id, platform, oid, status, dry, amount, eta, error, fallback)


def _result(card_id, platform, oid, status, dry, amount, eta, error=None, fallback=None):
    return {"platform": platform, "order_id": oid, "status": status, "amount": amount,
            "eta_min": eta, "error": error, "fallback_url": fallback}

# ---------------------------------------------------------------- onboarding

QUIZ = [("Masala Dosa", True), ("Idli Sambar", True), ("Poha", True), ("Aloo Paratha", True),
        ("Chole Bhature", True), ("Rajma Chawal", True), ("Dal Makhani", True),
        ("Paneer Butter Masala", True), ("Veg Biryani", True), ("Pav Bhaji", True),
        ("Khichdi", True), ("Curd Rice", True), ("Masala Oats", True), ("Veg Thali", True),
        ("Egg Bhurji", False), ("Chicken Biryani", False), ("Butter Chicken", False),
        ("Fish Curry", False)]


def quiz(diet):
    return [n for n, veg in QUIZ if veg or diet in ("nonveg", "eggetarian") and
            ("egg" in n.lower() or diet == "nonveg")]


def _order_item_name(item):
    """'Afghani Chaap (1)' / '2 x Butter Naan' -> the dish name without the quantity."""
    return re.sub(r"^\s*\d+\s*[x×]\s*|\s*[x×]\s*\d+\s*$|\s*\(\d+\)\s*$", "", item).strip()


def pull_food_orders(conn, user_id, food_client, address_id):
    """Swiggy Food order history (get_food_orders, docs: addressId + orderCount<=15) ->
    +2 per dish, +2/3 per restaurant, once per orderId. Also catches orders placed
    directly in the Swiggy app, the planner's old blind spot."""
    if food_client is None or not address_id:
        return 0
    try:
        resp = food_client.call("get_food_orders", {"addressId": str(address_id), "orderCount": 15})
    except Exception as e:  # noqa: BLE001 — history is a best-effort signal
        print(f"[daily] food order history failed: {e}")
        return 0
    orders = ((resp.get("data") or resp) if isinstance(resp, dict) else {}).get("orders") or []
    learned = 0
    for o in orders:
        oid = str(o.get("orderId") or "")
        if not oid or conn.execute("SELECT 1 FROM feedback_event WHERE user_id=? AND dimension='order' "
                                   "AND key=?", (user_id, oid)).fetchone():
            continue
        record(conn, user_id, "history", "order", oid, value=0)   # seen-marker: learn each order once
        names = [n for n in (_order_item_name(i) for i in re.split(r",|\n", o.get("orderedItems") or "")) if n]
        # learn on the standard dish name, the same key the cards are scored on
        prof = dish_profile.profiles(conn, names)
        for name in names:
            record(conn, user_id, "history", "dish", (prof.get(name) or {}).get("canonical") or name)
        if o.get("restaurantName"):
            record(conn, user_id, "history", "restaurant", o["restaurantName"], value=EVENT_DELTAS["history"] / 3)
        learned += 1
    return learned


def pull_history(conn, user_id, im_client, address_id):
    """Instamart get_orders + your_go_to_items as cold-start grocery signal."""
    if im_client is None:
        return 0
    names = []
    for fn, args in ((im_client.get_orders, ()), (im_client.your_go_to_items, (address_id,))):
        try:
            names += _names(fn(*args))
        except Exception as e:  # noqa: BLE001 — cold start is best-effort
            print(f"[daily] history pull failed: {e}")
    for n in dict.fromkeys(names):
        # once per product: this runs on every profile save, and repeats used to pile up
        if not conn.execute("SELECT 1 FROM feedback_event WHERE user_id=? AND type='history' AND dimension='grocery' "
                            "AND key=?", (user_id, _norm(n))).fetchone():
            record(conn, user_id, "history", "grocery", n)
    return len(names)


def _names(obj, depth=0):
    """Collect product display names from an arbitrary Instamart payload."""
    if depth > 6:
        return []
    if isinstance(obj, list):
        return [n for x in obj for n in _names(x, depth + 1)]
    if isinstance(obj, dict):
        own = [obj[k] for k in ("displayName", "productName", "itemName") if isinstance(obj.get(k), str)]
        return own + [n for v in obj.values() if isinstance(v, (list, dict)) for n in _names(v, depth + 1)]
    return []

# ---------------------------------------------------------------- nightly

def nightly(conn, dishes_fn, im_fn, today_=None):
    """Recompute weights -> regenerate memory MD -> build tomorrow's menus, every user."""
    day = (today_ or _date.today()) + timedelta(days=1)
    done = 0
    for r in conn.execute("SELECT user_id FROM user_profile").fetchall():
        uid = r["user_id"]
        recompute(conn, uid)
        write_memory_md(conn, uid)
        try:
            build_day(conn, uid, day, dishes_fn, im_fn)
            done += 1
            import plan_quality
            v = today(conn, uid, day, datetime.combine(day, datetime.min.time()), dishes_fn, im_fn)
            for issue in plan_quality.check_day(conn, v):
                print(f"[quality] user {uid} {day} {issue['slot']}: {issue['rule']} - {issue['detail']}")
        except Exception as e:  # noqa: BLE001 — one user's failure must not stop the batch
            print(f"[daily] nightly build failed for user {uid}: {e}")
    return done


def delete_user(conn, user_id):
    """Erase everything stored about a user (account deletion). Children first."""
    u = (int(user_id),)
    conn.execute("DELETE FROM order_record WHERE card_id IN (SELECT c.id FROM menu_card c JOIN daily_menu m ON c.menu_id = m.id WHERE m.user_id = ?)", u)
    conn.execute("DELETE FROM menu_card WHERE menu_id IN (SELECT id FROM daily_menu WHERE user_id = ?)", u)
    conn.execute("DELETE FROM excluded_card WHERE menu_id IN (SELECT id FROM daily_menu WHERE user_id = ?)", u)
    conn.execute("DELETE FROM notifications WHERE meal_slot_id IN (SELECT s.id FROM meal_slots s JOIN plans p ON s.plan_id = p.id WHERE p.user_id = ?)", u)
    conn.execute("DELETE FROM meal_slots WHERE plan_id IN (SELECT id FROM plans WHERE user_id = ?)", u)
    for t in ("daily_menu", "plans", "consumption_log", "feedback_event", "pref_weight", "ledger_transactions",
              "budget_cycles", "appetite_profiles", "user_profile"):
        conn.execute(f"DELETE FROM {t} WHERE user_id = ?", u)
    conn.execute("DELETE FROM users WHERE id = ?", u)
    conn.commit()
    (MEMORY_DIR / f"{int(user_id)}.md").unlink(missing_ok=True)
