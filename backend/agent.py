"""Chat agent for the daily recommender (spec §1.8).

Gemini picks one tool per step as JSON ({"tool","args"} or {"reply"}), up to
MAX_STEPS. Without a key / on a bad reply, a small keyword router picks the
tool instead, so every capability still works offline. Every search result
passes daily.filter_and_score — the same hard filters as the cards.
"""
import json
import re
import time
from datetime import datetime, timedelta

import daily
import gemini

MAX_STEPS = 3
DEADLINE_S = 20   # whole LLM loop; Gemini fallbacks can each take seconds
_LAST = {}   # user_id -> last search results (so "add the 2nd one" resolves)

TOOLS = """Tools (reply ONLY one JSON object per turn):
{"tool":"search","args":{"query":"spicy paneer","max_price":250,"slot":"dinner"}}
{"tool":"add","args":{"index":0,"slot":"dinner"}}          # put a search result into today's slot
{"tool":"order","args":{"card_id":12}}                     # only asks the user to confirm in the UI
{"tool":"log","args":{"slot":"lunch","text":"dal and 2 roti"}}
{"tool":"pref","args":{"action":"never|like|dislike","dimension":"ingredient|dish|cuisine|restaurant","key":"paneer"}}
{"tool":"explain","args":{"card_id":12}}
{"tool":"gaps","args":{}}
When done: {"reply":"short friendly answer"}"""


def run(conn, user_id, message, deps, now=None):
    """deps: dishes_fn, im_fn, food_exec, im_client, address_id."""
    now = now or datetime.now()
    trace = []
    if gemini.has_key():
        mem = daily.write_memory_md(conn, user_id).read_text(encoding="utf-8") + grounding(conn, user_id, now)
        deadline = time.monotonic() + DEADLINE_S
        for _ in range(MAX_STEPS):
            if time.monotonic() > deadline:
                break   # slow model chain: answer from the tools already run
            prompt = (f"{TOOLS}\n\nUser memory:\n{mem}\nNow: {now:%A %H:%M}\n"
                      f"User: {message}\nTool results so far: {json.dumps(trace)[-3000:]}")
            step = _json(gemini.chat(prompt, system="You are a concise Indian meal assistant.", timeout=12))
            if not step:
                break
            if "reply" in step:
                if trace and trace[-1]["tool"] == "search" and trace[-1]["result"].get("results"):
                    return _answer(trace)
                return {"reply": step["reply"], "trace": trace}
            if step.get("tool") == "search" and re.search(r"(best|top|famous|popular)", message.lower()):
                step.setdefault("args", {})["best"] = True   # the model often drops "best" from its query
            if any(t["tool"] == step.get("tool") and t.get("args") == step.get("args") for t in trace):
                break   # model is looping on the same call
            trace.append({"tool": step.get("tool"), "args": step.get("args"),
                          "result": _call(conn, user_id, step.get("tool"), step.get("args") or {}, deps, now)})
        if trace:
            return _answer(trace)
    tool, args = route(message)
    res = _call(conn, user_id, tool, args, deps, now)
    trace.append({"tool": tool, "result": res})
    return _answer(trace)


def _answer(trace):
    """Reply + (for a search) the results as data, so the UI shows cards, not a paragraph."""
    out = {"reply": _summarize(trace), "trace": trace}
    last = trace[-1]
    if last["tool"] == "search" and last["result"].get("results"):
        out["results"] = last["result"]["results"]
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
    price = re.search(r"(?:under|below|<)\s*(?:rs\.?|₹)?\s*(\d+)", m)
    q = re.sub(r"(?:under|below|<)\s*(?:rs\.?|₹)?\s*\d+|something|i want|craving|for|some|please", " ", m)
    return "search", {"query": q.strip(), "max_price": int(price.group(1)) if price else None,
                      "slot": slot}


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


_FILLER = {"spicy", "hot", "teekha", "something", "best", "top", "famous", "popular", "good", "near", "nearby",
           "around", "the", "for", "and", "with", "from", "want", "need", "get", "show", "find", "some", "any",
           "under", "below", "rupees", "please", "instamart", "grocery", "groceries", "pack", "packet",
           "order", "can", "you", "what", "which", "where", "today", "tonight", "now", "have"}


def _search(conn, user_id, a, deps, now):
    profile = daily.get_profile(conn, user_id)
    day, slot = now.date(), a.get("slot") or _slot_now()
    raw = (a.get("query") or "").lower()
    words = [w for w in re.findall(r"[a-z]+", raw) if len(w) > 2]
    spicy = any(w in ("spicy", "hot", "teekha") for w in words)
    best = bool(a.get("best")) or any(w in ("best", "top", "famous", "popular") for w in words)
    grocery = any(w in ("instamart", "grocery", "groceries", "pack", "packet") for w in words)
    city = (profile.get("city") or "").lower().split()
    words = [w for w in words if w not in _FILLER and w not in city]
    drafts = [{"items": [daily._dish_item(d)], "price": float(d.price)}
              for d in deps["dishes_fn"](daily.diet_on(profile, day) in ("veg", "jain", "vegan"))
              if (not words or any(w in d.name.lower() or w in d.cuisine for w in words))
              and (not spicy or "spicy" in d.tags or any(s in d.name.lower() for s in
                                                          ("chilli", "65", "schezwan", "kolhapuri",
                                                           "pepper", "chettinad", "spicy")))]
    # Today's cached menu is built for meals; anything else (a sweet, a specific dish)
    # is searched on Swiggy live so the answer comes from restaurants.
    if words and len(drafts) < 3 and deps.get("search_fn"):
        have = {d["items"][0]["id"] for d in drafts}
        try:
            live = deps["search_fn"](" ".join(words), daily.diet_on(profile, day) in ("veg", "jain", "vegan"))
        except Exception as e:  # noqa: BLE001 — live search is best-effort
            print(f"[agent] live search failed: {e}")
            live = []
        drafts += [{"items": [daily._dish_item(d)], "price": float(d.price)} for d in live if d.dish_id not in have]
    # Instamart only when asked for groceries, or when no restaurant has it
    if words and (grocery or not drafts):
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
        slot = "snack"
        kept, excluded = daily.filter_and_score(conn, user_id, profile, day, slot, drafts, ctx)
    kept.sort(key=(lambda c: (-(c["items"][0].get("rating") or 0), -c["score"])) if best else (lambda c: -c["score"]))
    _LAST[user_id] = kept[:5]
    return {"query": " ".join(words), "best": best,
            "results": [{"index": i, "name": c["items"][0]["name"], "price": c["price"],
                         "restaurant": c["items"][0]["restaurant_name"],
                         "rating": c["items"][0].get("rating") or None,
                         "image_url": c["items"][0].get("image_url") or "",
                         "source": c["items"][0]["source"], "veg": c["items"][0].get("veg", True),
                         "kcal": round(c["nutrients"].get("kcal") or 0)} for i, c in enumerate(kept[:5])],
            "excluded_for_allergies": len(excluded)}


def _add(conn, user_id, a, deps, now):
    c = _LAST.get(user_id, [])[int(a.get("index", 0))]
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
        if not r["results"]:
            return "Nothing nearby matches that within your diet and allergy rules."
        what = r.get("query") or "that"
        return (f"Best-rated {what} near you:" if r.get("best") else f"Here's what I found for {what}:")
    if t["tool"] == "add":
        return f"Added {r['name']} to {r['slot']}. Tap Confirm on its card to order."
    if t["tool"] == "order":
        return f"Tap Confirm on {r['name']} (Rs {r['price']:.0f}) in today's cards to place it."
    if t["tool"] == "log":
        return f"Logged {', '.join(r['logged'])} (~{r['nutrients']['kcal']:.0f} kcal)."
    if t["tool"] == "pref":
        return f"Got it — {'never showing' if r['action'] == 'never' else 'noted you ' + r['action']} {r['key']}."
    if t["tool"] == "explain":
        return f"{r['name']} is your '{r['role']}' pick: " + "; ".join(r["reasons"]) + "."
    if t["tool"] == "gaps":
        if not r["days_logged"]:
            return "I don't have any meals logged yet, so I can't tell what you're low on."
        return "You're low on " + (", ".join(r["low_on"]) or "nothing notable") + " this week."
    return json.dumps(r)

