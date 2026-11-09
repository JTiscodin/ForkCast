"""Plan quality gate — audits a built day (daily.today view) against plain
Indian-meal rules, reading the same dish profiles the planner uses. Runs in the
tests, the nightly batch (logged) and GET /daily/{user}/quality, so a bad plan
is caught by the system instead of by the user.
"""
import dish_profile

MAIN_SLOTS = ("breakfast", "lunch", "dinner")
NOT_A_MEAL = ("side", "snack", "sweet", "drink", "bread", "rice")


def check_day(conn, view):
    """-> list of {slot, card_id, rule, detail}; empty means the day passes."""
    items = [i for s in view["slots"] for c in s["cards"] for i in c["items"]]
    prof = dish_profile.profiles(conn, [i["name"] for i in items], llm=False)
    jain = view["diet"] == "jain"
    out, seen = [], {}

    def bad(slot, card, rule, detail):
        out.append({"slot": slot, "card_id": card["id"], "rule": rule, "detail": detail})

    for s in view["slots"]:
        slot = s["slot"]
        for c in s["cards"]:
            main = c["items"][0]
            p = prof[main["name"]]
            sides = [i for i in c["items"][1:] if i.get("side")]
            if main["source"] == "food":
                if slot in MAIN_SLOTS and p["kind"] in NOT_A_MEAL:
                    bad(slot, c, "not_a_meal", f"{main['name']} is a {p['kind']}, not a {slot}")
                min_kcal = {"breakfast": 150, "lunch": 250, "dinner": 250}.get(slot, 0)
                if c.get("nutrients", {}).get("kcal", min_kcal) < min_kcal:
                    bad(slot, c, "too_small", f"{main['name']} is ~{c['nutrients']['kcal']:.0f} kcal, too light for {slot}")
                if any(w in main["name"].lower() for w in ("coke", "pepsi", "cola", "sprite", "fanta", "soda")):
                    bad(slot, c, "junk_combo", f"{main['name']} comes with a soft drink")
                if slot == "snack" and p["kind"] in ("sweet", "drink"):
                    bad(slot, c, "not_a_snack", f"{main['name']} is a {p['kind']}, not a chai-time snack")
                if p["kind"] == "curry" and not any(prof[x["name"]]["kind"] in ("bread", "rice") for x in sides):
                    bad(slot, c, "curry_without_carb", f"{main['name']} has no roti or rice")
                if p["serves"] > 1:
                    bad(slot, c, "sharing_portion", f"{main['name']} serves {p['serves']}")
                if jain:
                    for i in [main] + [x for x in c["items"][1:] if x["source"] == "food" and not x.get("side")]:
                        pi = prof[i["name"]]
                        if "jain" not in i["name"].lower() and pi.get("source") != "rules" and pi["onion_garlic"]:
                            bad(slot, c, "jain_unsafe", f"{i['name']} likely has onion/garlic")
            key = p.get("canonical") or dish_profile.key_of(main["name"])
            if key in seen:
                bad(slot, c, "duplicate", f"{main['name']} repeats {seen[key]}")
            seen[key] = main["name"]
            for a in (i for i in c["items"] if i.get("addon")):
                if slot in ("lunch", "dinner") and (prof[a["name"]]["kind"] == "drink" or "milk" in a["name"].lower()):
                    bad(slot, c, "odd_addon", f"{a['name']} doesn't go with {slot}")
    return out
