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
                return {"reply": step["reply"], "trace": trace}
            if any(t["tool"] == step.get("tool") and t.get("args") == step.get("args") for t in trace):
                break   # model is looping on the same call
            trace.append({"tool": step.get("tool"), "args": step.get("args"),
                          "result": _call(conn, user_id, step.get("tool"), step.get("args") or {}, deps, now)})
        if trace:
            return {"reply": _summarize(trace), "trace": trace}
    tool, args = route(message)
    res = _call(conn, user_id, tool, args, deps, now)
    trace.append({"tool": tool, "result": res})
    return {"reply": _summarize(trace), "trace": trace}


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


def _search(conn, user_id, a, deps, now):
    profile = daily.get_profile(conn, user_id)
    day, slot = now.date(), a.get("slot") or _slot_now()
    words = [w for w in re.findall(r"[a-z]+", (a.get("query") or "").lower()) if len(w) > 2]
    spicy = any(w in ("spicy", "hot", "teekha") for w in words)
    words = [w for w in words if w not in ("spicy", "hot", "teekha", "something")]
    drafts = [{"items": [daily._dish_item(d)], "price": float(d.price)}
              for d in deps["dishes_fn"](daily.diet_on(profile, day) in ("veg", "jain", "vegan"))
              if (not words or any(w in d.name.lower() or w in d.cuisine for w in words))
              and (not spicy or "spicy" in d.tags or any(s in d.name.lower() for s in
                                                          ("chilli", "65", "schezwan", "kolhapuri",
                                                           "pepper", "chettinad", "spicy")))]
    if words:
        try:
            drafts += [{"items": [daily._im_item(r)], "price": float(r["price"])}
                       for r in deps["im_fn"](" ".join(words))[:5] if r.get("price")]
        except Exception:  # noqa: BLE001 — Instamart optional
            pass
    if a.get("max_price"):
        drafts = [d for d in drafts if d["price"] <= float(a["max_price"])]
    ctx = daily.context(conn, user_id, profile, day)
    kept, excluded = daily.filter_and_score(conn, user_id, profile, day, slot, drafts, ctx)
    kept.sort(key=lambda c: -c["score"])
    _LAST[user_id] = kept[:5]
    return {"results": [{"index": i, "name": c["items"][0]["name"], "price": c["price"],
                         "restaurant": c["items"][0]["restaurant_name"]} for i, c in enumerate(kept[:5])],
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
        return "Here's what fits: " + "; ".join(
            f"{x['index'] + 1}. {x['name']} (Rs {x['price']:.0f}, {x['restaurant']})" for x in r["results"]) \
            + ". Say 'add 1' to put one in today's plan."
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

