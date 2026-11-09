"""Daily personalization — spec §4 done criteria, against mock catalog + in-memory DB."""
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

import agent
import daily
import db
import gemini
import nutrition
from catalog import mock_catalog
from order_executor import OrderExecutor

DAY = date(2026, 11, 4)          # a Wednesday (weekday 2)
NOW = datetime(2026, 11, 4, 9, 0)
IM = {"curd": [{"id": "c1", "name": "Dahi 400g", "price": 35}],
      "banana": [{"id": "b1", "name": "Banana 6pc", "price": 40}],
      "eggs": [{"id": "e1", "name": "Eggs 6pc", "price": 54}],
      "bread": [{"id": "br", "name": "Bread", "price": 45}],
      "paneer": [{"id": "p1", "name": "Paneer 200g", "price": 90}]}


def im_fn(q):
    return IM.get(q, [])


def dishes_fn(veg_only):
    # one restaurant per dish: the 7-restaurant mock is smaller than any real neighbourhood
    # (curries keep their restaurant so they can pair with its roti/rice)
    return [d if d.course in ("curry", "bread", "staple")
            else replace(d, restaurant_id="r-" + d.dish_id, restaurant_name="R " + d.dish_id)
            for d in mock_catalog() if d.veg or not veg_only]


@pytest.fixture
def conn(monkeypatch, tmp_path):
    monkeypatch.setattr(gemini, "has_key", lambda: False)
    monkeypatch.setattr(daily, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(daily, "weather", lambda city, day: {})
    c = db.get_conn(":memory:")
    c.executescript(db.SCHEMA)
    c.execute("INSERT INTO users (id, name) VALUES (1, 'T')")
    daily.save_profile(c, 1, {"diet_type": "nonveg", "slots": ["breakfast", "lunch", "dinner"],
                              "monthly_budget": 9000})
    return c


def view(conn, day=DAY, now=NOW):
    return daily.today(conn, 1, day, now, dishes_fn, im_fn)


def test_role_cards_and_restaurant_once_per_day(conn):
    v = view(conn)
    rids = []
    for s in v["slots"]:
        roles = [c["role"] for c in s["cards"]]
        assert 3 <= len(roles) <= 4, (s["slot"], roles)
        assert len(set(roles)) == len(roles)
        rids += [c["items"][0]["restaurant_id"] for c in s["cards"]
                 if c["items"][0]["restaurant_id"] != "instamart"]
    assert len(rids) == len(set(rids))


def test_allergy_goes_to_excluded_never_cards(conn):
    daily.save_profile(conn, 1, {"allergies": [{"name": "paneer", "severe": True}]})
    v = view(conn)
    names = [i["name"].lower() for s in v["slots"] for c in s["cards"] for i in c["items"]]
    assert not any("paneer" in n for n in names)
    assert any(e["allergen_hit"] == "paneer" for s in v["slots"] for e in s["excluded"])
    assert all("Severe allergy" in " ".join(c["reasons"])
               for s in v["slots"] for c in s["cards"])


def test_weekday_override_changes_cards(conn):
    daily.save_profile(conn, 1, {"weekday_overrides": {str(DAY.weekday()): "veg"}})
    v = view(conn)
    assert v["diet"] == "veg"
    assert all(i["veg"] for s in v["slots"] for c in s["cards"] for i in c["items"])


def test_order_dry_run_logs_and_blocks_double(conn):
    v = view(conn)
    card = v["slots"][1]["cards"][0]
    ex = OrderExecutor(mode="mock")
    r = daily.order(conn, 1, card["id"], ex, None, None, confirm=True)
    assert r["mode"] == "dry_run" and all(o["status"] == "dry_run" for o in r["orders"])
    assert conn.execute("SELECT COUNT(*) FROM consumption_log").fetchone()[0] == 1
    w, _ = daily.weights(conn, 1)
    assert w[("dish", daily._norm(card["items"][0]["name"]))] == pytest.approx(3, abs=0.01)
    with pytest.raises(ValueError):
        daily.order(conn, 1, card["id"], ex, None, None, confirm=True)


def test_two_platform_card_is_two_orders(conn):
    v = view(conn)
    card = next((c for s in v["slots"] for c in s["cards"] if c["deliveries"] == 2), None)
    assert card, "expected a restaurant + Instamart add-on card"
    r = daily.order(conn, 1, card["id"], OrderExecutor(mode="mock"), None, None, confirm=True)
    assert {o["platform"] for o in r["orders"]} == {"food", "instamart"}


def test_never_show_is_permanent_and_filters(conn):
    v = view(conn)
    name = v["slots"][1]["cards"][0]["items"][0]["name"]
    daily.record(conn, 1, "never", "dish", name, value=0)
    daily.build_day(conn, 1, DAY, dishes_fn, im_fn)
    v = view(conn)
    assert name not in [c["items"][0]["name"] for s in v["slots"] for c in s["cards"]]
    daily.recompute(conn, 1, now=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=365))
    assert ("dish", daily._norm(name)) in daily.weights(conn, 1)[1]


def test_decay_halves_after_two_weeks(conn):
    daily.record(conn, 1, "up", "dish", "rajma chawal")
    daily.recompute(conn, 1, now=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=14))
    assert daily.weights(conn, 1)[0][("dish", "rajma chawal")] == pytest.approx(1.5, abs=0.05)


def test_memory_edit_round_trips(conn):
    daily.record(conn, 1, "up", "cuisine", "south_indian")
    m = daily.edit_memory(conn, 1, "cuisine", "south_indian", weight=5)
    assert next(b for b in m["bullets"] if b["key"] == "south_indian")["weight"] == pytest.approx(5)
    m = daily.edit_memory(conn, 1, "cuisine", "south_indian", delete=True)
    assert not any(b["key"] == "south_indian" for b in m["bullets"])
    assert (daily.MEMORY_DIR / "1.md").exists()


def test_repeat_window_keeps_yesterday_out_of_new_roles(conn):
    y = view(conn, DAY - timedelta(days=1), NOW - timedelta(days=1))
    shown = {daily._norm(c["items"][0]["name"]) for s in y["slots"] for c in s["cards"]}
    v = view(conn)
    for s in v["slots"]:
        for c in s["cards"]:
            if c["role"] != "usual":
                assert daily._norm(c["items"][0]["name"]) not in shown


def test_nudge_after_window_end_until_logged(conn):
    late = datetime(2026, 11, 4, 16, 0)
    lunch = next(s for s in view(conn, now=late)["slots"] if s["slot"] == "lunch")
    assert lunch["nudge"]
    daily.log_food(conn, 1, DAY, "lunch", "nudge", [])
    lunch = next(s for s in view(conn, now=late)["slots"] if s["slot"] == "lunch")
    assert not lunch["nudge"]


def test_nutrition_lookup_and_gaps(conn):
    r = nutrition.lookup(conn, "Ghee Roast Masala Dosa")
    assert r["canonical"] == "masala dosa" and r["source"] in ("indb", "ifct")
    assert nutrition.lookup(conn, "Zzqx special", llm=False)["source"] == "default"
    daily.log_food(conn, 1, DAY, "breakfast", "chat_log", ["boiled egg", "boiled egg"])
    ns = daily.nutrition_state(conn, 1, daily.get_profile(conn, 1), DAY)
    egg = nutrition.lookup(conn, "boiled egg")["nutrients"]["protein"]
    assert ns["today"]["protein"] == pytest.approx(2 * egg, abs=0.1) and ns["remaining_slots"] == ["lunch", "dinner"]
    assert 0 < ns["gap"]["protein"] < 1


def test_budget_soft_cap(conn):
    b = daily.budget(conn, 1, daily.get_profile(conn, 1), DAY)
    assert b["days_left"] == 27 and b["daily_cap"] == pytest.approx(9000 / 27, abs=0.01)


def test_profile_validation(conn):
    for bad in ({"diet_type": "keto"}, {"weekday_overrides": {"9": "veg"}}, {"slots": []},
                {"mode": "yolo"}, {"monthly_budget": 0}):
        with pytest.raises(ValueError):
            daily.save_profile(conn, 1, bad)


def test_parse_food_text():
    assert daily.parse_food_text("had dal and 2 roti at home") == ["dal", "roti", "roti"]


def test_agent_fallback_tools(conn):
    deps = {"dishes_fn": dishes_fn, "im_fn": im_fn, "food_exec": OrderExecutor(mode="mock"),
            "im_client": None, "address_id": None}
    r = agent.run(conn, 1, "something with paneer under 300", deps, now=NOW)
    assert r["trace"][0]["tool"] == "search" and r["trace"][0]["result"]["results"]
    r = agent.run(conn, 1, "add 1 for dinner", deps, now=NOW)
    cid = r["trace"][0]["result"]["card_id"]
    r = agent.run(conn, 1, f"order card {cid}", deps, now=NOW)
    assert r["trace"][0]["result"]["needs_confirmation"]
    assert conn.execute("SELECT COUNT(*) FROM order_record").fetchone()[0] == 0
    with pytest.raises(ValueError):
        daily.order(conn, 1, cid, deps["food_exec"], None, None)   # no confirm -> refused
    r = agent.run(conn, 1, f"why card {cid}", deps, now=NOW)
    assert r["trace"][0]["tool"] == "explain"
    r = agent.run(conn, 1, "stop suggesting paneer", deps, now=NOW)
    assert ("ingredient", "paneer") in daily.weights(conn, 1)[1]
    r = agent.run(conn, 1, "something with paneer", deps, now=NOW)
    assert not r["trace"][0]["result"]["results"]
    r = agent.run(conn, 1, "I had poha for breakfast", deps, now=NOW)
    assert r["trace"][0]["result"]["logged"] == ["poha"]
    assert agent.route("what am I low on?")[0] == "gaps"


def test_curry_card_carries_its_bread_or_rice(conn):
    v = view(conn)
    curry = [c for s in v["slots"] for c in s["cards"] if len(c["items"]) > 1 and c["items"][1].get("side")]
    assert curry, "expected a curry + accompaniment card"
    c = curry[0]
    side = c["items"][1]
    assert side["restaurant_id"] == c["items"][0]["restaurant_id"] and side["quantity"] in (1, 2)
    assert c["price"] == pytest.approx(sum(i["price"] * i.get("quantity", 1) for i in c["items"]))


def test_no_bare_bread_or_rice_cards(conn):
    names = [c["items"][0]["name"] for s in view(conn)["slots"] for c in s["cards"]]
    assert not any(n in ("Tawa Roti", "Tandoori Roti", "Butter Naan", "Steamed Rice", "Jeera Rice")
                   for n in names)


def test_executor_sends_side_lines_in_one_cart():
    calls = []

    class FakeMCP:
        def call(self, tool, args):
            calls.append((tool, args))
            return {"cart": {"total": 300}, "availablePaymentMethods": ["COD"]} if tool == "get_food_cart" else {}

    ex = OrderExecutor(mode="mcp", mcp_client=FakeMCP(), address_id="a1")
    r = ex.place("curry1", "r1", 300, dry_run=True, extra_items=[{"id": "roti1", "quantity": 2}])
    cart = next(a for t, a in calls if t == "update_food_cart")["cartItems"]
    assert [(x["menu_item_id"], x["quantity"]) for x in cart] == [("curry1", 1), ("roti1", 2)]
    assert r["status"] == "dry_run" and not any(t == "place_food_order" for t, _ in calls)


def test_small_catalog_reuses_restaurant_instead_of_empty_slot(conn):
    few = lambda veg_only: [d for d in mock_catalog() if d.veg or not veg_only]  # 7 restaurants
    v = daily.today(conn, 1, DAY, NOW, few, im_fn)
    assert all(len(s["cards"]) >= 3 for s in v["slots"])


def _age_menus(conn):
    conn.execute("UPDATE daily_menu SET generated_at=datetime('now','-2 hours'), refreshed_at=NULL")


def test_sold_out_card_is_replaced_on_open(conn):
    v = view(conn)
    gone = v["slots"][1]["cards"][0]["items"][0]["id"]
    _age_menus(conn)
    without = lambda veg_only: [d for d in dishes_fn(veg_only) if d.dish_id != gone]
    v = daily.today(conn, 1, DAY, NOW, without, im_fn, stock_fn=lambda i: i["id"] != gone)
    assert gone not in [i["id"] for s in v["slots"] for c in s["cards"] for i in c["items"]]


def test_unknown_stock_and_empty_rebuild_keep_cards(conn):
    before = {s["slot"]: [c["id"] for c in s["cards"]] for s in view(conn)["slots"]}
    _age_menus(conn)
    v = daily.today(conn, 1, DAY, NOW, dishes_fn, im_fn, stock_fn=lambda i: None)
    assert {s["slot"]: [c["id"] for c in s["cards"]] for s in v["slots"]} == before
    daily.build_day(conn, 1, DAY, lambda veg: [], lambda q: [])   # outage: nothing fetched
    assert {s["slot"]: [c["id"] for c in s["cards"]] for s in view(conn)["slots"]} == before


def test_nutrition_retrieval_handles_menu_spellings():
    for name, canon in (("Hyderabadi Chicken Biriani", "chicken biryani"), ("Murgh Makhni", "butter chicken"),
                        ("Plain Chapathi", "roti"), ("Masala Dossa", "masala dosa")):
        assert canon in nutrition.lookup(None, name, llm=False)["canonical"]
    assert nutrition.lookup(None, "Chicken Lollipop", llm=False)["source"] == "default"


def test_agent_grounding_lists_meals_and_cards(conn):
    view(conn)
    daily.log_food(conn, 1, DAY, "breakfast", "chat_log", ["poha"])
    g = agent.grounding(conn, 1, NOW)
    assert "poha" in g and "usual" in g


def test_sides_and_dish_dupes_never_become_cards(conn):
    # live menus: a Rs 9 raita and the same dish from two restaurants
    base = dishes_fn
    d = next(x for x in mock_catalog() if x.name == "Rajma Chawal")
    extra = [replace(d, dish_id="raita", name="Biryani Raita", price=9, restaurant_id="rr1"),
             replace(d, dish_id="dup", name="RAJMA CHAWAL", restaurant_id="rr2")]
    v = daily.today(conn, 1, DAY, NOW, lambda veg: base(veg) + extra, im_fn)
    names = [daily._norm(" + ".join(i["name"] for i in c["items"] if not i.get("addon")))
             for s in v["slots"] for c in s["cards"]]
    assert "biryani raita" not in names
    assert len(names) == len(set(names))


def test_in_band_swiggy_failure_raises(monkeypatch):
    import swiggy_mcp
    c = swiggy_mcp.SwiggyMCPClient.__new__(swiggy_mcp.SwiggyMCPClient)
    monkeypatch.setattr(c, "_rpc", lambda m, p: {"structuredContent": {
        "success": False, "error": {"message": "addressId is required"}}}, raising=False)
    with pytest.raises(swiggy_mcp.SwiggyMCPError, match="addressId is required"):
        c.call("get_food_cart", {})


def test_meal_addons_are_indian_sides_not_milk():
    im = dict(IM, curd=[{"id": "c1", "name": "Dahi 400g", "price": 35}],
              cucumber=[{"id": "k1", "name": "Cucumber 500g", "price": 30}],
              milk=[{"id": "m1", "name": "Milk Tetra", "price": 28}])
    profile = {"user_id": 1, "goal": "high_protein", "diet_type": "veg", "weekday_overrides": {}}
    gap = {"protein": 0.9, "vitd": 1.0, "calcium": 0.8, "fibre": 0.6}
    card = {"items": [{"source": "food", "name": "Dal Tadka"}], "nutrients": {}}
    for slot in ("lunch", "dinner"):
        add = daily._addon(None, profile, DAY, slot, card, gap, lambda q: im.get(q, []), {})
        assert add and add["name"] in ("Dahi 400g", "Cucumber 500g"), (slot, add)
    curd_rice = {"items": [{"source": "food", "name": "Curd Rice"}], "nutrients": {}}
    add = daily._addon(None, profile, DAY, "lunch", curd_rice, gap, lambda q: im.get(q, []), {})
    assert add is None or add["name"] != "Dahi 400g"
    add = daily._addon(None, profile, DAY, "breakfast", card, {"vitd": 1.0}, lambda q: im.get(q, []), {})
    assert add["name"] == "Milk Tetra"


def test_renamed_duplicates_count_as_the_same_dish():
    used = {"rajma chawal", "chole bhature"}
    assert daily._same_dish("Kadchi Plain Rajma-Chawal", used)
    assert daily._same_dish("Chole Bhature(2 Pcs)", used)
    assert not daily._same_dish("Paneer Tikka", {"paneer bhurji"})


def test_maggi_is_snack_only_and_indian_breakfast_ranks_first(conn):
    d = next(x for x in mock_catalog() if x.meal_type == "dinner" and x.course == "complete")
    maggi = replace(d, dish_id="mg", name="Masala Maggi", price=120)
    assert not daily._fits_slot(maggi, "dinner") and not daily._fits_slot(maggi, "lunch")
    assert daily._fits_slot(maggi, "snack")
    b = next(x for x in mock_catalog() if x.meal_type == "breakfast")
    sandwich = replace(b, dish_id="sw", name="Veg Sandwich", restaurant_id="rs", price=b.price)
    poha = replace(b, dish_id="ph", name="Kanda Poha", restaurant_id="rp", price=b.price)
    p = daily.get_profile(conn, 1)
    kept, _ = daily.filter_and_score(conn, 1, p, DAY, "breakfast",
                                     [{"items": [daily._dish_item(x)], "price": x.price} for x in (sandwich, poha)],
                                     daily.context(conn, 1, p, DAY))
    score = {c["items"][0]["name"]: c["score"] for c in kept}
    assert score["Kanda Poha"] > score["Veg Sandwich"]


def test_jain_day_needs_jain_label_or_safe_dish(conn):
    daily.save_profile(conn, 1, {"weekday_overrides": {str(DAY.weekday()): "jain"}})
    base = next(x for x in mock_catalog() if x.meal_type == "lunch" and x.course == "complete" and x.veg)
    names = ["Masala Curry Combo", "Jain Dal Makhani Combo", "Curd Rice", "Rajma Steamed Rice Bowl"]
    drafts = [{"items": [daily._dish_item(replace(base, dish_id=f"j{i}", name=n, restaurant_id=f"rj{i}"))],
               "price": base.price} for i, n in enumerate(names)]
    p = daily.get_profile(conn, 1)
    kept, _ = daily.filter_and_score(conn, 1, p, DAY, "lunch", drafts, daily.context(conn, 1, p, DAY))
    assert {c["items"][0]["name"] for c in kept} == {"Jain Dal Makhani Combo", "Curd Rice"}


def test_rules_that_empty_a_slot_replace_stale_cards(conn):
    before = view(conn)
    assert before["slots"][2]["cards"]
    daily.build_day(conn, 1, DAY, lambda veg: [d for d in dishes_fn(veg) if d.meal_type == "breakfast"], lambda q: [],
                    slots=["dinner"])   # dishes fetched, none fit dinner
    assert not next(s for s in view(conn)["slots"] if s["slot"] == "dinner")["cards"]


def _store_profiles(conn, rows):
    import dish_profile
    dish_profile.ensure_table(conn)
    for name, prof in rows.items():
        conn.execute("INSERT OR REPLACE INTO dish_profile (key, profile, source) VALUES (?,?,?)",
                     (dish_profile.key_of(name), json.dumps(prof), "llm"))
    conn.commit()


def _prof(kind, slots=("lunch", "dinner"), canonical=None, og=True, serves=1):
    return {"canonical": canonical, "kind": kind, "slots": list(slots), "diet": "veg",
            "onion_garlic": og, "serves": serves, "kcal": 400, "protein": 12, "allergens": []}


def test_quality_gate_flags_each_rule(conn):
    import plan_quality
    _store_profiles(conn, {"Aloo Gobi": _prof("curry"), "Masala Maggi": _prof("snack", ["snack"]),
                           "Rajma Chawal": _prof("meal", canonical="rajma chawal"),
                           "Kadchi Rajma-Chawal": _prof("meal", canonical="rajma chawal"),
                           "Family Thali": _prof("meal", serves=3), "Milk Tetra": _prof("drink", ["breakfast"]),
                           "Tawa Roti": _prof("bread")})
    food = lambda n, **k: {"source": "food", "name": n, **k}
    view = {"diet": "veg", "slots": [{"slot": "dinner", "cards": [
        {"id": 1, "items": [food("Aloo Gobi")]},
        {"id": 2, "items": [food("Masala Maggi")]},
        {"id": 3, "items": [food("Rajma Chawal"), {"source": "instamart", "name": "Milk Tetra", "addon": True}]},
        {"id": 4, "items": [food("Kadchi Rajma-Chawal")]},
        {"id": 5, "items": [food("Family Thali")]},
        {"id": 6, "items": [food("Aloo Gobi"), food("Tawa Roti", side=True, quantity=2)]},
    ]}]}
    rules = {(i["card_id"], i["rule"]) for i in plan_quality.check_day(conn, view)}
    assert {(1, "curry_without_carb"), (2, "not_a_meal"), (3, "odd_addon"), (4, "duplicate"),
            (5, "sharing_portion")} <= rules
    assert not any(cid == 6 and r == "curry_without_carb" for cid, r in rules)


def test_profile_driven_planning_fixes_name_gaps(conn, monkeypatch):
    """With stored profiles, a dish the keyword rules misread is still planned right."""
    _store_profiles(conn, {"Chef Special Veggie Delight": _prof("curry"),   # no keyword says curry
                           "Masala Maggi": _prof("snack", ["snack"]),
                           "Butter Roti": _prof("bread")})
    base = next(x for x in mock_catalog() if x.meal_type == "dinner" and x.course == "complete")
    pool = [replace(base, dish_id="cv", name="Chef Special Veggie Delight", restaurant_id="rx", price=180),
            replace(base, dish_id="br", name="Butter Roti", restaurant_id="rx", price=30, course="bread"),
            replace(base, dish_id="mg", name="Masala Maggi", restaurant_id="ry", price=150)]
    drafts = daily.candidates("dinner", DAY, daily.get_profile(conn, 1), lambda v: pool, lambda q: [], conn)
    names = [[i["name"] for i in d["items"]] for d in drafts]
    assert ["Chef Special Veggie Delight", "Butter Roti"] in names
    assert not any("Masala Maggi" in n for n in names)


def test_learning_generalises_across_restaurants_by_canonical_name(conn):
    a = {"name": "Rajma Chawal", "canonical": "rajma chawal", "cuisine": "north_indian", "restaurant_name": "A"}
    b = {"name": "Kadchi Plain Rajma-Chawal", "canonical": "rajma chawal", "cuisine": "x", "restaurant_name": "B"}
    daily.record_card(conn, 1, {"id": 0, "items": [a]}, "ordered")
    w, blocks = daily.weights(conn, 1)
    assert daily._pref(b, w) == pytest.approx(3, abs=0.01)   # other restaurant's version learns too
    daily.record(conn, 1, "never", "dish", "rajma chawal", value=0)
    _, blocks = daily.weights(conn, 1)
    assert daily._blocked(b, blocks)


def test_bread_sold_as_a_pack_is_ordered_once(conn):
    base = next(x for x in mock_catalog() if x.meal_type == "dinner" and x.course == "curry" and x.veg)
    pool = [replace(base, dish_id="cu", name="Dal Makhani", restaurant_id="rz"),
            replace(base, dish_id="gp", name="Ghee Paratha [Pack of 3]", restaurant_id="rz", price=90, course="bread")]
    drafts = daily.candidates("dinner", DAY, daily.get_profile(conn, 1), lambda v: pool, lambda q: [])
    side = next(i for d in drafts for i in d["items"] if i.get("side"))
    assert side["quantity"] == 1


def test_indb_nutrients_scale_by_piece_count():
    one = nutrition.lookup(None, "Idli", llm=False)
    four = nutrition.lookup(None, "Steamed Idli (4 Pcs)", llm=False)
    assert one["source"] == "indb" and four["nutrients"]["kcal"] == pytest.approx(4 * one["nutrients"]["kcal"], rel=0.01)
    assert nutrition.lookup(None, "Masala Dosa", llm=False)["nutrients"]["kcal"] < 400   # one dosa, not two
    assert nutrition.lookup(None, "Masala Dosa Paneer Fillings Special", llm=False)["canonical"].startswith("masala dosa paneer")


def test_passing_over_a_previously_ordered_dish_is_a_no_reorder_signal(conn):
    v = view(conn)
    lunch = next(s for s in v["slots"] if s["slot"] == "lunch")
    first, second = lunch["cards"][0], lunch["cards"][1]
    daily.record_card(conn, 1, first, "ordered")            # ordered it some earlier day
    daily.order(conn, 1, second["id"], OrderExecutor(mode="mock"), None, None, confirm=True)
    events = {r["type"] for r in conn.execute(
        "SELECT type FROM feedback_event WHERE key=?", (daily._norm(first["items"][0]["name"]),))}
    assert "no_reorder" in events


def test_mcp_client_honours_retry_after_once(monkeypatch):
    import io
    import urllib.error
    import swiggy_mcp
    calls, slept = [], []

    def fake_urlopen(req, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {"Retry-After": "1"}, io.BytesIO(b""))
        return io.BytesIO(b'{"jsonrpc":"2.0","id":1,"result":{"structuredContent":{"ok":1}}}')

    monkeypatch.setattr(swiggy_mcp.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(swiggy_mcp.time, "sleep", lambda s: slept.append(s))
    c = swiggy_mcp.SwiggyMCPClient.__new__(swiggy_mcp.SwiggyMCPClient)
    c.url, c.token, c._id, c.timeout = "https://x", "t", 0, 5
    assert c.call("search_menu", {}) == {"ok": 1} and slept == [1.0] and len(calls) == 2


def test_preview_builds_carts_but_records_nothing(conn):
    daily.save_profile(conn, 1, {"mode": "live"})
    card = view(conn)["slots"][1]["cards"][0]
    r = daily.order(conn, 1, card["id"], OrderExecutor(mode="mock"), None, None, confirm=True, preview=True)
    assert r["mode"] == "preview" and all(o["status"] == "dry_run" for o in r["orders"])
    assert conn.execute("SELECT COUNT(*) FROM order_record").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM consumption_log").fetchone()[0] == 0


def test_food_order_history_teaches_once_per_order(conn):
    class Food:
        def call(self, tool, args):
            assert tool == "get_food_orders" and args["orderCount"] == 15 and args["addressId"]
            return {"data": {"orders": [{"orderId": "o1", "restaurantName": "Haldiram",
                                         "orderedItems": "1 x Rajma Chawal, 2 x Butter Roti"}]}}
    assert daily.pull_food_orders(conn, 1, Food(), "a1") == 1
    assert daily.pull_food_orders(conn, 1, Food(), "a1") == 0          # same order not learned twice
    w, _ = daily.weights(conn, 1)
    assert w[("dish", "rajma chawal")] == pytest.approx(2, abs=0.01) and ("dish", "butter roti") in w


def test_meals_must_be_filling_and_soda_combos_are_out(conn):
    base = next(x for x in mock_catalog() if x.meal_type == "lunch" and x.course == "complete" and x.veg)
    names = ["Anna Idli Sambhar [1 Piece]", "Nachos + Coke Combo", "Rajma Chawal"]
    drafts = [{"items": [daily._dish_item(replace(base, dish_id=f"m{i}", name=n, restaurant_id=f"rm{i}"))],
               "price": base.price} for i, n in enumerate(names)]
    p = daily.get_profile(conn, 1)
    kept, _ = daily.filter_and_score(conn, 1, p, DAY, "lunch", drafts, daily.context(conn, 1, p, DAY))
    assert [c["items"][0]["name"] for c in kept] == ["Rajma Chawal"]


def test_removable_allergen_becomes_a_restaurant_note_core_is_hidden(conn):
    daily.save_profile(conn, 1, {"allergies": [{"name": "peanut", "severe": True}]})
    base = next(x for x in mock_catalog() if x.meal_type == "lunch" and x.course == "complete" and x.veg)
    mk = lambda n, al: {"items": [{**daily._dish_item(replace(base, dish_id=n, name=n, restaurant_id="r" + n)),
                                   "allergens": al}], "price": base.price}
    drafts = [mk("Veg Thali", [{"name": "peanut", "how": "removable"}]),
              mk("Peanut Chikki Meal", [{"name": "peanut", "how": "core"}]),
              mk("Dal Rice Meal", [])]
    p = daily.get_profile(conn, 1)
    kept, excluded = daily.filter_and_score(conn, 1, p, DAY, "lunch", drafts, daily.context(conn, 1, p, DAY))
    notes = {c["items"][0]["name"]: c["items"][0].get("note") for c in kept}
    assert notes == {"Veg Thali": "No peanut please, severe allergy", "Dal Rice Meal": None}
    assert [e["items"][0]["name"] for e in excluded] == ["Peanut Chikki Meal"]


def test_note_reaches_place_food_order():
    calls = []

    class FakeMCP:
        def call(self, tool, args):
            calls.append((tool, args))
            return {"data": {"pricing": {"to_pay": 200}}} if tool == "get_food_cart" else {"data": {"order_id": "1"}}

    OrderExecutor(mode="mcp", mcp_client=FakeMCP(), address_id="a").place("d", "r", 150, note="No peanut please")
    assert dict(calls)["place_food_order"]["noteToRestaurant"] == "No peanut please"


def test_delete_user_erases_every_row(conn):
    view(conn)
    daily.record(conn, 1, "up", "dish", "dal makhani")
    daily.delete_user(conn, 1)
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
        if "user_id" in cols:
            assert conn.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id = 1").fetchone()[0] == 0, t
    assert conn.execute("SELECT COUNT(*) FROM menu_card").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM users WHERE id = 1").fetchone()[0] == 0
    assert not (daily.MEMORY_DIR / "1.md").exists()
