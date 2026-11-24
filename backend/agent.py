"""Chat agent for the daily recommender (spec §1.8).

Gemini picks one tool per step as JSON ({"tool","args"} or {"reply"}), up to
MAX_STEPS. Without a key / on a bad reply, a small keyword router picks the
tool instead, so every capability still works offline. Every search result
passes daily.filter_and_score — the same hard filters as the cards.

A search can name a place. Where the user gets deliveries ("best rasmalai in
Gurgaon" from a Gurugram address) it searches Swiggy as usual. Anywhere else
("best chole bhature in CP") Swiggy can't deliver, so the answer is where to go:
places from a Google-grounded Gemini lookup, with map links and no order button,
plus what does deliver to the user.
"""
import json
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import daily
import gemini

MAX_STEPS = 3
DEADLINE_S = 20   # whole LLM loop; Gemini fallbacks can each take seconds
_LAST = {}   # user_id -> last search results (so "add the 2nd one" resolves)

TOOLS = """Tools (reply ONLY one JSON object per turn):
{"tool":"search","args":{"query":"chole bhature","place":"Connaught Place, Delhi","max_price":250,"slot":"dinner"}}
    query: only the food. place: only when the user names a place (not "near me"), written out in full
    ("CP" -> "Connaught Place, Delhi"); leave it out otherwise, never take it from the memory.
{"tool":"add","args":{"index":0,"slot":"dinner"}}          # put a search result into today's slot
{"tool":"order","args":{"card_id":12}}                     # only asks the user to confirm in the UI
{"tool":"log","args":{"slot":"lunch","text":"dal and 2 roti"}}
{"tool":"pref","args":{"action":"never|like|dislike","dimension":"ingredient|dish|cuisine|restaurant","key":"paneer"}}
{"tool":"explain","args":{"card_id":12}}
{"tool":"gaps","args":{}}
When done: {"reply":"short friendly answer"}"""


def run(conn, user_id, message, deps, now=None):
    """deps: dishes_fn, im_fn, food_exec, im_client, address_id; optional search_fn, area_fn, live."""
    now = now or datetime.now()
    trace = []
    if gemini.has_key():
        mem = daily.write_memory_md(conn, user_id).read_text(encoding="utf-8") + grounding(conn, user_id, now)
        deadline = time.monotonic() + DEADLINE_S
        for _ in range(MAX_STEPS):
            left = deadline - time.monotonic()
            if left < 2:
                break   # slow model chain: answer from the tools already run
            prompt = (f"{TOOLS}\n\nUser memory:\n{mem}\nNow: {now:%A %H:%M}\n"
                      f"User: {message}\nTool results so far: {json.dumps(trace)[-3000:]}")
            step = _json(gemini.chat(prompt, system="You are a concise Indian meal assistant.",
                                     timeout=min(12, left)))
            if not step:
                break
            if "reply" in step:
                return {"reply": step["reply"], "trace": trace}
            tool, args = step.get("tool"), step.get("args") or {}
            if tool == "search":
                args = _search_args(args, message)
            if any(t["tool"] == tool and t.get("args") == args for t in trace):
                break   # model is looping on the same call
            trace.append({"tool": tool, "args": args, "result": _call(conn, user_id, tool, args, deps, now)})
            if tool == "search" and "error" not in trace[-1]["result"]:
                return _answer(trace)   # the cards are the answer; another model round only adds seconds
        if trace:
            return _answer(trace)
    tool, args = route(message)
    res = _call(conn, user_id, tool, args, deps, now)
    trace.append({"tool": tool, "result": res})
    return _answer(trace)


def _search_args(args, message):
    """The model reads the city from memory and sometimes adds it unasked: keep a place only if the user said one."""
    p = args.get("place")
    if p and not _place_in(message) and not set(_words(p)) & set(_words(message)):
        args = {k: v for k, v in args.items() if k != "place"}
    if re.search(r"\b(best|top|famous|popular)\b", message.lower()):
        args = {**args, "best": True}   # the model often drops "best" from its query
    return args


def _answer(trace):
    """Reply + (for a search) the results as data, so the UI shows cards, not a paragraph."""
    out = {"reply": _summarize(trace), "trace": trace}
    last = trace[-1]
    if last["tool"] == "search":
        out.update({k: v for k, v in last["result"].items()
                    if k in ("results", "places", "sources", "suggest_html", "maps_url") and v})
    return out


def grounding(conn, user_id, now):
    """Retrieved facts for the prompt: last 7 days of meals + today's card ids."""
    since = (now.date() - timedelta(days=6)).isoformat()
    meals = conn.execute("SELECT date, slot, items FROM consumption_log WHERE user_id=? AND date>=? "
                         "ORDER BY date DESC, id DESC LIMIT 20", (user_id, since)).fetchall()
    cards = conn.execute("SELECT c.id, c.role, c.items, c.price, m.slot FROM menu_card c JOIN daily_menu m "
                         "ON m.id=c.menu_id WHERE m.user_id=? AND m.date=?",
                         (user_id, now.date().isoformat())).fetchall()
    out = ["\nRecent meals:"] + [f"- {r['date']} {r['slot']}: {', '.join(json.loads(r['items'])) or 'skipped'}"
                                 for r in meals]
    out += ["Today's cards (id, slot, role, dish, Rs):"] + [
        f"- {r['id']} {r['slot']} {r['role']} {json.loads(r['items'])[0]['name']} {r['price']:.0f}" for r in cards]
    return "\n".join(out) + "\n"


_PRICE = r"(?:under|below|less than|within|upto|up to|<)\s*(?:rs\.?|inr|₹)?\s*(\d+)"


def route(msg):
    """Keyword fallback: message -> (tool, args)."""
    m = msg.lower()
    slot = next((s for s in daily.SLOTS if s in m), None) or _slot_now()
    if re.search(r"\b(had|ate|eaten)\b", m):
        return "log", {"slot": slot, "text": msg}
    hit = re.search(r"(?:stop suggesting|never show|no more|don't show|dont show)\s+(.+)", m)
    if hit:
        return "pref", {"action": "never", "dimension": "ingredient", "key": hit.group(1).strip(" .!")}
    hit = re.search(r"\border\s+(?:card\s+)?#?(\d+)", m)
    if hit:
        return "order", {"card_id": int(hit.group(1))}
    hit = re.search(r"\badd\s+(?:the\s+)?#?(\d+)", m)
    if hit:
        return "add", {"index": int(hit.group(1)) - 1, "slot": slot}
    hit = re.search(r"why .*?#?(\d+)", m)
    if hit:
        return "explain", {"card_id": int(hit.group(1))}
    if re.search(r"low on|lacking|missing|gap|nutri", m):
        return "gaps", {}
    price = re.search(_PRICE, m)
    return "search", {"query": msg, "max_price": int(price.group(1)) if price else None,
                      "slot": slot, "place": _place_in(msg)}


def _slot_now():
    h = datetime.now().hour
    return "breakfast" if h < 11 else "lunch" if h < 16 else "snack" if h < 19 else "dinner"


def _call(conn, user_id, tool, args, deps, now):
    try:
        fn = {"search": _search, "add": _add, "order": _order, "log": _log, "pref": _pref,
              "explain": _explain, "gaps": _gaps}[tool]
    except KeyError:
        return {"error": f"unknown tool {tool}"}
    try:
        return fn(conn, user_id, args, deps, now)
    except (ValueError, KeyError, TypeError, IndexError) as e:
        return {"error": str(e)}


# ---------------------------------------------------------------- places

_PLACE_RE = re.compile(r".*\b(?:in|at|near|around)\s+(.+?)[\s?.!]*$", re.I | re.S)
# what follows "in"/"near" but isn't somewhere: "high in protein", "near me", "in the evening"
_NOT_PLACE = re.compile(
    r"(?:me|us|here|home|my .*|our .*|the (?:morning|evening|afternoon|night|rain|cold|heat)|morning|evening|"
    r"afternoon|night|breakfast|lunch|snacks?|dinner|budget|protein|iron|calcium|fib(?:re|er)|carbs?|calories|"
    r"fat|sugar|sodium|vitamins?|a hurry|rain|winter|summer|monsoon|today|tonight|this weather|"
    r"(?:the )?(?:area|locality|neighbou?rhood|vicinity|city|town))$", re.I)
_ALIASES = {"gurgaon": "gurugram", "ggn": "gurugram", "bangalore": "bengaluru", "blr": "bengaluru",
            "bombay": "mumbai", "calcutta": "kolkata", "madras": "chennai", "poona": "pune", "baroda": "vadodara",
            "mysore": "mysuru", "cochin": "kochi", "trivandrum": "thiruvananthapuram", "vizag": "visakhapatnam",
            "hyd": "hyderabad", "cp": "connaught place"}


def _place_in(text):
    """'best chole bhature in CP' -> 'CP'; None for 'near me', 'high in protein', 'in the evening'."""
    t = re.sub(_PRICE, " ", text or "", flags=re.I)
    t = re.sub(r"\b(?:for|at)\s+(?:breakfast|lunch|snacks?|dinner)\b|\b(?:today|tonight|right now|now|please)\b",
               " ", t, flags=re.I)
    m = _PLACE_RE.match(t.strip())
    p = m.group(1).strip(" ,.'\"") if m else ""
    if not p or _NOT_PLACE.fullmatch(p) or len(p) > 40 or len(p.split()) > 5 or not re.search(r"[a-z]", p, re.I):
        return None
    return p


def _words(s):
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def _canon(s):
    return " ".join(_ALIASES.get(w, w) for w in _words(s))


def _local(place, here):
    """Is the place where the user gets deliveries? Its first part ('Connaught Place' of
    'Connaught Place, Delhi') appears in their Swiggy address line or city."""
    first = _canon(place.split(",")[0])
    return bool(first) and f" {first} " in f" {_canon(here)} "


def _show(place):
    """'cp' -> 'CP', 'lajpat nagar' -> 'Lajpat Nagar'; typed capitals are kept."""
    if place != place.lower():
        return place
    return place.upper() if len(place) <= 3 else place.title()


def _maps(query):
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote_plus(query)


_PLACES = {}   # (dish, place) -> (fetched_at, lookup): famous spots don't change by the hour
PLACES_TTL_S = 6 * 3600


def _where_to_try(dish, place, city):
    """Places to go for a dish in a place -> {places, sources, suggest_html, grounded}.

    Google-grounded Gemini first; without grounding quota, the model's own knowledge,
    flagged so the reply can say it wasn't checked live. Only the city is sent, never
    the address.
    """
    key = (dish, place.lower())
    hit = _PLACES.get(key)
    if hit and time.time() - hit[0] < PLACES_TTL_S:
        return hit[1]
    near = f" The user lives in {city}; if the place name is ambiguous, pick the one nearest there." if city else ""
    ask = (f"Where should someone go for the best {dish or 'food'} in {place}?{near} "
           'Reply with ONLY this JSON, no other text: {"places":[{"name":"","area":"","known_for":"","price":""}]} '
           "with 3 to 5 real places that serve it and are still open, best first. area: the neighbourhood or "
           "landmark. known_for: why people go, at most 12 words. price: approximate cost for one in rupees, "
           "or empty if unsure.")
    text, sources, suggest = gemini.search(ask + " Use Google Search for current information.", timeout=25)
    grounded = bool(text)
    if not text:
        text = gemini.chat(ask, timeout=15)
    places = []
    for p in ((_json(text) or {}).get("places") or [])[:5]:
        if isinstance(p, dict) and isinstance(p.get("name"), str) and p["name"].strip():
            name, area = p["name"].strip()[:80], str(p.get("area") or "").strip()[:80]
            places.append({"name": name, "area": area, "known_for": str(p.get("known_for") or "").strip()[:140],
                           "price": str(p.get("price") or "").strip()[:40],
                           "maps_url": _maps(f"{name}, {area or place}")})
    out = {"places": places, "sources": sources if places else [],
           "suggest_html": suggest if places else "", "grounded": grounded}
    if places:
        _PLACES[key] = (time.time(), out)
    return out


# ---------------------------------------------------------------- search

_FILLER = {"spicy", "hot", "teekha", "something", "anything", "best", "top", "famous", "popular", "good", "great",
           "nice", "tasty", "authentic", "near", "nearby", "around", "the", "for", "and", "with", "from", "want",
           "need", "get", "show", "find", "some", "any", "under", "below", "within", "upto", "less", "than",
           "rupees", "please", "instamart", "grocery", "groceries", "pack", "packet", "order", "can", "you",
           "what", "which", "where", "who", "today", "tonight", "now", "have", "eat", "eating", "food", "foods",
           "place", "places", "restaurant", "restaurants", "shop", "shops", "joint", "joints", "try", "should",
           "could", "would", "like", "love", "craving", "crave", "feel", "feeling", "suggest", "recommend",
           "option", "options", "dish", "dishes", "item", "items", "breakfast", "lunch", "snack", "snacks",
           "dinner", "delivered", "deliver", "delivery", "available", "get", "out", "there", "here", "this", "that"}


def _search(conn, user_id, a, deps, now):
    profile = daily.get_profile(conn, user_id)
    day, slot = now.date(), a.get("slot") or _slot_now()
    raw = a.get("query") or ""
    place = a.get("place") if "place" in a else _place_in(raw)
    city = profile.get("city") or ""
    words = [w for w in re.findall(r"[a-z]+", raw.lower()) if len(w) > 2]
    flags = {"spicy": any(w in ("spicy", "hot", "teekha") for w in words),
             "best": bool(a.get("best")) or any(w in ("best", "top", "famous", "popular") for w in words),
             "grocery": any(w in ("instamart", "grocery", "groceries", "pack", "packet") for w in words)}
    # place and city names aren't food: "rasmalai gurgaon" finds nothing on Swiggy
    not_food = set(_words(_canon(f"{place or ''} {city}"))) | set(_words(place))
    words = [w for w in words if w not in _FILLER and _ALIASES.get(w, w) not in not_food]
    dish = " ".join(words)
    if place and not _local(place, f"{deps['area_fn']() if deps.get('area_fn') else ''} {city}"):
        # Swiggy delivers only near the user: say where to go there, and what does deliver here
        with ThreadPoolExecutor(max_workers=1) as pool:
            web = pool.submit(_where_to_try, dish, _show(place), city)
            out = _deliverable(conn, user_id, profile, day, slot, words, flags, a, deps) if words else \
                {"query": dish, "best": flags["best"], "results": [], "excluded_for_allergies": 0}
            try:
                out.update(web.result())
            except Exception as e:  # noqa: BLE001 — the map link below still answers
                print(f"[agent] place lookup failed: {e}")
        return {**out, "place": _show(place), "local": False,
                "maps_url": _maps(f"{dish or 'food'} in {_show(place)}")}
    out = _deliverable(conn, user_id, profile, day, slot, words, flags, a, deps)
    out["live"] = deps.get("live", True)
    if place:
        out.update(place=_show(place), local=True)
        if not out["results"] and words:   # nothing on Swiggy right now: still say where it's good
            out.update(_where_to_try(dish, _show(place), city), maps_url=_maps(f"{dish} in {_show(place)}"))
    return out


def _deliverable(conn, user_id, profile, day, slot, words, flags, a, deps):
    """Swiggy (and, for groceries, Instamart) results that deliver to the user, best first, one per restaurant."""
    veg = daily.diet_on(profile, day) in ("veg", "jain", "vegan")
    drafts = [{"items": [daily._dish_item(d)], "price": float(d.price)}
              for d in deps.get("chat_dishes_fn", deps["dishes_fn"])(veg)
              if (not words or any(w in d.name.lower() or w in d.cuisine for w in words))
              and (not flags["spicy"] or "spicy" in d.tags or any(s in d.name.lower() for s in
                                                                   ("chilli", "65", "schezwan", "kolhapuri",
                                                                    "pepper", "chettinad", "spicy")))]
    # Today's cached menu is built for meals; a sweet, a specific dish, or "the best X"
    # is searched on Swiggy live so the answer comes from every restaurant near the user.
    if words and (flags["best"] or len(drafts) < 3) and deps.get("search_fn"):
        have = {d["items"][0]["id"] for d in drafts}
        try:
            live = deps["search_fn"](" ".join(words), veg, **({"pages": 2} if flags["best"] else {}))
        except Exception as e:  # noqa: BLE001 — live search is best-effort
            print(f"[agent] live search failed: {e}")
            live = []
        drafts += [{"items": [daily._dish_item(d)], "price": float(d.price)} for d in live if d.dish_id not in have]
    # Instamart only when asked for groceries, or when no restaurant has it
    if words and (flags["grocery"] or not drafts):
        try:
            drafts += [{"items": [daily._im_item(r)], "price": float(r["price"])}
                       for r in deps["im_fn"](" ".join(words))[:5] if r.get("price")]
        except Exception:  # noqa: BLE001 — Instamart optional
            pass
    if a.get("max_price"):
        drafts = [d for d in drafts if d["price"] <= float(a["max_price"])]
    ctx = daily.context(conn, user_id, profile, day)
    kept, excluded = daily.filter_and_score(conn, user_id, profile, day, slot, drafts, ctx)
    if not kept and drafts and slot != "snack":   # a dessert is not "too small for dinner"
        kept, excluded = daily.filter_and_score(conn, user_id, profile, day, "snack", drafts, ctx)

    rating = (lambda c: c["items"][0].get("rating") or 0) if flags["best"] else (lambda c: 0)
    kept.sort(key=lambda c: (*_fit(c["items"][0]["name"], words), -rating(c), -c["score"]))
    top, seen = [], set()
    for c in kept:   # one per restaurant: "best rasmalai" means five places, not one shop's menu
        rid = c["items"][0]["restaurant_id"]
        if rid not in seen or rid == "instamart":
            seen.add(rid)
            top.append(c)
        if len(top) == 5:
            break
    _LAST[user_id] = top
    return {"query": " ".join(words), "best": flags["best"],
            "results": [{"index": i, "name": c["items"][0]["name"], "price": c["price"],
                         "restaurant": c["items"][0]["restaurant_name"],
                         "rating": c["items"][0].get("rating") or None,
                         "image_url": c["items"][0].get("image_url") or "",
                         "source": c["items"][0]["source"], "veg": c["items"][0].get("veg", True),
                         "kcal": round(c["nutrients"].get("kcal") or 0)} for i, c in enumerate(top)],
            "excluded_for_allergies": len(excluded)}


_PORTION = {"pcs", "pc", "piece", "pieces", "nos", "plate", "portion", "serving", "full", "half", "regular",
            "small", "medium", "large", "classic", "special", "fresh", "desi", "the", "and", "with", "of"}
_BULK = re.compile(r"\bkgs?\b|\d\s*kg|\b(?:[5-9]\d\d|1000)\s*(?:g|gm|gms|grams?)\b|\bserves\s*[2-9]|family|party|"
                   r"\bbox of\b|\bpack of\s*(?:[5-9]|\d\d)", re.I)


def _fit(name, words):
    """Sort key (lower is better) for how plainly a menu name is the dish asked for:
    "Rasmalai (2 Pcs)" > "Mango Rasmalai Cup" > "Rasmalai Cake - 1Kg" > "Gulab Jamun"."""
    n = name.lower()
    has_all = all(w in n for w in words)
    extra = [w for w in re.findall(r"[a-z]+", n) if w not in _PORTION and not any(w in q or q in w for q in words)]
    return (not has_all, bool(_BULK.search(n)), len(extra))


def _add(conn, user_id, a, deps, now):
    found = _LAST.get(user_id, [])
    i = int(a.get("index", 0))
    if not 0 <= i < len(found):
        raise ValueError("that result isn't on my list any more, search again and pick from the new list")
    c = found[i]
    slot = a.get("slot") or _slot_now()
    if slot not in daily.SLOTS:
        raise ValueError("bad slot")
    d = now.date().isoformat()
    conn.execute("INSERT OR IGNORE INTO daily_menu (user_id, date, slot) VALUES (?,?,?)", (user_id, d, slot))
    mid = conn.execute("SELECT id FROM daily_menu WHERE user_id=? AND date=? AND slot=?",
                       (user_id, d, slot)).fetchone()["id"]
    cid = conn.execute(
        "INSERT INTO menu_card (menu_id, role, position, items, price, nutrients, score, reasons) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (mid, "chat", 99, json.dumps(c["items"]), c["price"], json.dumps(c["nutrients"]),
         c["score"], json.dumps(["Added from chat"]))).lastrowid
    conn.commit()
    return {"card_id": cid, "slot": slot, "name": c["items"][0]["name"],
            "note": "confirm it from today's cards"}


def _order(conn, user_id, a, deps, now):
    # never place an order from chat: an LLM step is not a user click. Return the
    # card for the UI's Confirm button, which calls /daily/{uid}/order/{card_id}.
    c = daily.get_card(conn, int(a["card_id"]))
    if not c or c["user_id"] != user_id:
        raise ValueError("no such card")
    return {"needs_confirmation": True, "card_id": c["id"], "name": c["items"][0]["name"],
            "price": c["price"]}


def _log(conn, user_id, a, deps, now):
    names = daily.parse_food_text(a.get("text", ""))
    if not names:
        raise ValueError("couldn't read any dish names")
    res = daily.log_food(conn, user_id, now.date(), a.get("slot") or _slot_now(), "chat_log", names)
    return {"logged": names, **res}


def _pref(conn, user_id, a, deps, now):
    dim, key, act = a.get("dimension", "ingredient"), a["key"], a.get("action", "never")
    if act == "never":
        daily.record(conn, user_id, "never", dim, key, value=0)
    else:
        daily.record(conn, user_id, "up" if act == "like" else "down", dim, key)
    daily.write_memory_md(conn, user_id)
    return {"ok": True, "action": act, "key": key}


def _explain(conn, user_id, a, deps, now):
    c = daily.get_card(conn, int(a["card_id"]))
    if not c or c["user_id"] != user_id:
        raise ValueError("no such card")
    return {"name": c["items"][0]["name"], "role": c["role"], "reasons": c["reasons"],
            "score": c["score"], "nutrients": c["nutrients"]}


def _gaps(conn, user_id, a, deps, now):
    p = daily.get_profile(conn, user_id)
    ns = daily.nutrition_state(conn, user_id, p, now.date())
    low = sorted(((k, g) for k, g in ns["gap"].items() if g > 0.25 and k != "kcal"), key=lambda kv: -kv[1])
    return {"low_on": [k for k, _ in low[:4]], "days_logged": ns["days_logged"]}


def _json(txt):
    m = re.search(r"\{.*\}", txt or "", re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except ValueError:
        return None


def _summarize(trace):
    """Deterministic reply text from the last tool result."""
    t = trace[-1]
    r = t["result"]
    if "error" in r:
        return f"Sorry, {r['error']}."
    if t["tool"] == "search":
        return _search_reply(r)
    if t["tool"] == "add":
        return f"Added {r['name']} to {r['slot']}. Find it in today's {r['slot']} cards to add it to your cart."
    if t["tool"] == "order":
        return f"{r['name']} (₹{r['price']:.0f}) is in today's cards: tap its button there to order it."
    if t["tool"] == "log":
        return f"Logged {', '.join(r['logged'])} (~{r['nutrients']['kcal']:.0f} kcal)."
    if t["tool"] == "pref":
        did = "I won't suggest" if r["action"] == "never" else f"noted that you {r['action']}"
        return f"Got it, {did} {r['key']}."
    if t["tool"] == "explain":
        return f"{r['name']} is your '{r['role']}' pick: " + "; ".join(r["reasons"]) + "."
    if t["tool"] == "gaps":
        if not r["days_logged"]:
            return "I don't have any meals logged yet, so I can't tell what you're low on."
        return "You're low on " + (", ".join(r["low_on"]) or "nothing notable") + " this week."
    return json.dumps(r)


def _search_reply(r):
    dish, place = r.get("query") or "food", r.get("place")
    if place and not r.get("local"):
        if r.get("places"):
            checked = "" if r.get("grounded") else " (not checked live, so confirm before you go)"
            return f"Top spots for {dish} in {place}{checked}. It's outside your delivery area, so these are to visit:"
        return f"I couldn't look up places in {place} right now. The map link below searches it for you."
    if r["results"]:
        return f"Best-rated {dish} that delivers to you:" if r.get("best") else f"Here's {dish} that delivers to you:"
    if r.get("places"):
        return f"Nothing on Swiggy delivers {dish} to you right now. Places in {place} known for it:"
    if not r.get("live", True):
        return ("Swiggy isn't connected, so I can only search the sample menu. "
                "Reconnect Swiggy from the top bar to search restaurants near you.")
    hidden = r.get("excluded_for_allergies")
    return (f"I couldn't find {dish} near you that fits your diet and allergy rules."
            + (f" {hidden} option{'s' if hidden > 1 else ''} hidden for your allergies." if hidden else ""))
