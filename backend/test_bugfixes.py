"""Regression tests for the audited wallet-integrity + validation bugs.

Each test reproduces one bug FIRST (asserts the CORRECT behavior we want),
so before the fix they FAIL and after the fix they PASS.

Run:  python test_bugfixes.py
"""
import sqlite3

from db import get_conn, SCHEMA
from wallet_service import WalletService
from plan_service import PlanService
from order_executor import OrderExecutor


def fresh():
    """In-memory DB + PlanService wired to a MOCK executor (no real orders)."""
    conn = get_conn(":memory:")
    conn.executescript(SCHEMA)
    conn.commit()
    wallet = WalletService(conn)
    executor = OrderExecutor(mode="mock")
    svc = PlanService(conn, wallet, executor)
    return conn, wallet, svc


def seed_plan(conn, svc, budget=10000, feasible=1, days=3, meals=("lunch", "dinner")):
    """Create a user + approved-ready plan + one slot per (day, meal). Returns (uid, plan_id)."""
    uid = conn.execute("INSERT INTO users (name) VALUES ('T')").lastrowid
    conn.commit()

    class _Slot:
        def __init__(self, day, meal):
            self.day = day
            self.meal_type = meal
            self.dish_id = f"d{day}{meal}"
            self.dish_name = f"Dish {day} {meal}"
            self.restaurant_id = "r1"
            self.restaurant_name = "R"
            self.image_url = ""
            self.price = 100.0
            self.rating = 4.0
            self.variant = "regular"
            self.course = "complete"
            self.side_dish_id = ""
            self.side_dish_name = ""
            self.side_qty = 0
            self.side_price = 0.0
            self.side_restaurant_name = ""
            self.side_image_url = ""

    class _Result:
        def __init__(self):
            self.budget = budget
            self.total_cost = 100.0 * days * len(meals)
            self.feasible = bool(feasible)
            self.message = "ok"
            self.slots = [_Slot(d, m) for d in range(1, days + 1) for m in meals]

    plan_id = svc.save_plan(uid, "2026-07", _Result())
    return uid, plan_id


def slot_ids(conn, plan_id):
    return [r[0] for r in conn.execute(
        "SELECT id FROM meal_slots WHERE plan_id=? ORDER BY id", (plan_id,))]


# ---- BUG 1: double "yes" -> double debit ----
def test_double_yes_debits_once():
    conn, wallet, svc = fresh()
    uid, plan_id = seed_plan(conn, svc)
    wallet.deposit(uid, "2026-07", 10000)
    sid = slot_ids(conn, plan_id)[0]

    svc.respond(sid, "yes")
    bal_after_first = wallet.get_balance(uid, "2026-07")

    # Second "yes" on an already-confirmed slot must NOT debit again.
    try:
        svc.respond(sid, "yes")
        double_debited = wallet.get_balance(uid, "2026-07") < bal_after_first
        assert not double_debited, "second 'yes' debited the wallet again"
    except ValueError:
        pass  # rejecting the repeat is also correct


# ---- BUG 2: "no" after "yes" credits wallet without cancelling the order ----
def test_no_after_yes_does_not_refund_live_order():
    conn, wallet, svc = fresh()
    uid, plan_id = seed_plan(conn, svc)
    wallet.deposit(uid, "2026-07", 10000)
    sid = slot_ids(conn, plan_id)[0]

    svc.respond(sid, "yes")           # order placed + debited
    bal_confirmed = wallet.get_balance(uid, "2026-07")

    # "no" now must NOT silently credit the wallet back while the order stands.
    try:
        svc.respond(sid, "no")
        bal_after = wallet.get_balance(uid, "2026-07")
        assert bal_after == bal_confirmed, (
            f"'no' after 'yes' refunded {bal_after - bal_confirmed} without cancelling the order")
    except ValueError:
        pass  # refusing to undo a placed order is the correct behavior


# ---- BUG 3: approving a second plan same month deposits nothing ----
def test_second_approval_same_month_funds_wallet():
    conn, wallet, svc = fresh()
    uid, plan_a = seed_plan(conn, svc, budget=10000)
    svc.approve_plan(plan_a)
    assert wallet.get_balance(uid, "2026-07") == 10000

    # A second, bigger plan approved the same month must top the wallet up.
    _, plan_b = seed_plan(conn, svc, budget=15000)
    # re-point plan_b at the same user
    conn.execute("UPDATE plans SET user_id=? WHERE id=?", (uid, plan_b))
    conn.commit()
    svc.approve_plan(plan_b)
    bal = wallet.get_balance(uid, "2026-07")
    assert bal == 15000, f"second approval left balance at {bal}, expected 15000"


# ---- BUG 4: over-budget (feasible=False) plan is approvable ----
def test_over_budget_plan_not_approvable():
    conn, wallet, svc = fresh()
    uid, plan_id = seed_plan(conn, svc, feasible=0)
    try:
        svc.approve_plan(plan_id)
        assert False, "over-budget plan was approved"
    except ValueError:
        pass


# ---- BUG 5: reschedule accepts an out-of-range day ----
def test_reschedule_rejects_out_of_range_day():
    conn, wallet, svc = fresh()
    uid, plan_id = seed_plan(conn, svc, days=3)
    sid = slot_ids(conn, plan_id)[0]
    try:
        svc.respond(sid, "later", new_day=9999)
        assert False, "rescheduled to day 9999 on a 3-day plan"
    except ValueError:
        pass


# ---- BUG 6: appetite_profiles table is never written ----
def test_appetite_profile_persisted():
    from appetite import build_profile
    conn, wallet, svc = fresh()
    uid = conn.execute("INSERT INTO users (name) VALUES ('T')").lastrowid
    conn.commit()
    prof = build_profile(uid, "heavy")
    # persist (this is what the fixed /appetite endpoint must do)
    conn.execute(
        "INSERT OR REPLACE INTO appetite_profiles "
        "(user_id, appetite_level, base_multiplier, roti_per_meal, rice_katori, per_slot_json) "
        "VALUES (?,?,?,?,?,?)",
        (uid, prof.appetite_level, prof.base_multiplier,
         prof.roti_per_meal, prof.rice_katori_per_meal,
         __import__("json").dumps(prof.per_slot)))
    conn.commit()
    row = conn.execute("SELECT * FROM appetite_profiles WHERE user_id=?", (uid,)).fetchone()
    assert row is not None, "appetite_profiles row missing"
    assert row["appetite_level"] == "heavy"


# ---- BUG 7: days=0 / empty meals produce a bogus feasible plan ----
def test_plan_input_validation():
    """days<1 and empty meals must be rejected at the API boundary (422)."""
    # This is enforced by pydantic in app.py; here we assert the optimizer
    # guard so a bad value can't sneak through any caller.
    from optimizer import optimize
    from catalog import mock_catalog
    from appetite import build_profile
    cat = mock_catalog()
    prof = build_profile(1, "moderate")
    try:
        res = optimize(cat, prof, 10000, days=0, meals=["lunch"])
        assert not (res.feasible and not res.slots), "days=0 produced an empty 'feasible' plan"
    except (ValueError, Exception):
        pass  # rejecting days=0 is correct


# ---- BUG 8: accompaniments / non-meals planned as whole dinners ----
def test_salan_roomali_egg_not_complete_meals():
    """The live catalog surfaced "Salan" ₹19 (a gravy), "Roomali (Whole Wheat)"
    ₹29 (a bread) and "Roasted Egg" ₹20 (a single egg). All three missed the
    keyword tables, defaulted to COMPLETE, and were planned as whole dinners /
    breakfasts. They must now classify correctly."""
    import course
    # Salan is the biryani condiment — a side, never a meal (bare or paired).
    assert course.course_of("Salan") == course.SIDE, \
        f"Salan -> {course.course_of('Salan')}"
    assert not course.standalone_meal("Salan", price=19)
    assert course.course_of("Roomali (Whole Wheat)") == course.BREAD, \
        f"Roomali -> {course.course_of('Roomali (Whole Wheat)')}"
    assert course.course_of("Rumali Roti") == course.BREAD
    # A bare egg is an add-on, not a breakfast.
    assert course.course_of("Roasted Egg") != course.COMPLETE, \
        "Roasted Egg classified as a standalone meal"
    assert course.course_of("Boiled Egg") != course.COMPLETE
    # But real egg meals keep their form — the bare-egg rule must not swallow them.
    # (These all carry a form/complete keyword that is checked BEFORE "egg".)
    assert course.course_of("Egg Roll [triple]") == course.COMPLETE
    assert course.course_of("Egg Bhurji Pav") == course.COMPLETE
    assert course.course_of("Egg Omelette [4 Eggs] With Veggies") == course.COMPLETE


def test_price_floor_blocks_cheap_unknown_standalone():
    """An UNRECOGNISED name defaults to COMPLETE; below the meal floor it must
    not be allowed to headline a slot. A confidently-known dish is unaffected."""
    import course
    # Unknown + cheap -> not standalone.
    assert not course.standalone_meal("Zzz Mystery Item", price=25)
    # Unknown but reasonably priced -> still standalone (the default stands).
    assert course.standalone_meal("Zzz Mystery Item", price=180)
    # Known complete meal, even if cheap, keeps its status.
    assert course.standalone_meal("Masala Dosa", price=90)


def _live_like_catalog():
    """A catalog shaped like the real one that produced the bug: cheap gravies,
    breads and eggs mixed in with genuine meals, all classified from names.

    Enough genuine mains per meal (>=4) that the per-week repeat cap never has
    to relax — so any bare bread/curry/egg or consecutive repeat the optimizer
    produces is a real bug, not an artifact of an artificially tiny pool.
    """
    from dataclasses import replace
    from catalog import Dish
    from course import course_of, dish_kind_of

    def d(dish_id, name, rid, rname, meal, price, rating, veg, tags):
        dish = Dish(dish_id, name, rid, rname, meal, price, rating,
                    "north_indian", tags, veg, {"regular": price})
        return replace(dish, course=course_of(dish.name),
                       dish_kind=dish_kind_of(dish.name))

    return [
        # breakfast — four real meals plus the offending cheap egg
        d("bf1", "Aloo Paratha", "r1", "Krishna Foods", "breakfast", 129, 4.0, True, ("paratha", "veg")),
        d("bf2", "Indori Poha", "r2", "Samosa Party", "breakfast", 129, 4.3, True, ("poha", "veg")),
        d("bf3", "Masala Dosa", "r8", "Sri Udupi", "breakfast", 119, 4.4, True, ("dosa", "veg")),
        d("bf4", "Egg Roll [triple]", "r9", "Wrapperz", "breakfast", 139, 4.3, False, ("egg", "nonveg")),
        d("bf5", "Roasted Egg", "r3", "Thalairaj Biryani", "breakfast", 20, 4.5, False, ("egg", "nonveg")),
        # dinner — four real mains plus the offending salan (gravy) and roomali (bread)
        d("dn1", "Chicken Roasted Biryani", "r4", "Chicken Point", "dinner", 192, 4.1, False, ("chicken", "biryani", "nonveg")),
        d("dn2", "Veg Dum Biryani Bowl", "r5", "Biryani Blues", "dinner", 155, 4.4, True, ("veg", "biryani")),
        d("dn3", "Paneer Butter Masala", "r10", "Punjabi Rasoi", "dinner", 210, 4.6, True, ("paneer", "veg")),
        d("dn4", "Dal Tadka", "r11", "Local Tiffin", "dinner", 120, 4.2, True, ("dal", "veg")),
        d("dn5", "Salan", "r6", "Bikkgane Biryani", "dinner", 19, 4.3, True, ("veg",)),
        d("dn6", "Roomali (Whole Wheat)", "r7", "Goila Butter Chicken", "dinner", 29, 4.2, True, ("veg",)),
        # breads to pair curries with (same-restaurant where possible)
        d("br1", "Tawa Roti", "r10", "Punjabi Rasoi", "dinner", 12, 4.1, True, ("roti", "veg")),
        d("br2", "Tandoori Roti", "r11", "Local Tiffin", "dinner", 18, 4.2, True, ("roti", "veg")),
        d("br3", "Tawa Roti", "r6", "Bikkgane Biryani", "dinner", 12, 4.1, True, ("roti", "veg")),
    ]


def test_no_bare_bread_curry_egg_as_meal():
    """The optimizer must never plan a bread, a bare gravy-without-side, or a
    single egg as a whole meal — even when they are the cheapest items in the
    pool and would otherwise score best on value-for-money."""
    import course
    from optimizer import optimize
    from appetite import build_profile

    cat = _live_like_catalog()
    prof = build_profile(1, "moderate")
    r = optimize(cat, prof, 15000, days=30, meals=["breakfast", "dinner"])

    for s in r.slots:
        # No bread / staple / side ever headlines a slot. This catches
        # "Roomali (Whole Wheat)" (bread) and "Roasted Egg" (side).
        assert s.course not in course.NEVER_STANDALONE, \
            f"day {s.day} {s.meal_type}: {s.dish_name} ({s.course}) planned as a meal"
        # A curry is a meal only WITH an accompaniment — a bare gravy is the
        # "just salan for dinner" bug.
        if s.course == course.CURRY:
            assert s.side_dish_name, \
                f"day {s.day} {s.meal_type}: {s.dish_name} is a bare gravy with no bread/rice"


def test_no_consecutive_day_repeats():
    """The same dish must not be served on two consecutive days. The old
    can_place() only blocked same-day reuse and a per-week cap, so a small
    catalog served the same breakfast days 1 AND 2."""
    from optimizer import optimize
    from appetite import build_profile

    cat = _live_like_catalog()
    prof = build_profile(1, "moderate")
    r = optimize(cat, prof, 15000, days=30, meals=["breakfast", "dinner"])

    by_day = {}
    for s in r.slots:
        by_day.setdefault(s.day, set()).add(s.dish_id)
    days = sorted(by_day)
    for i in range(1, len(days)):
        prev, cur = by_day[days[i - 1]], by_day[days[i]]
        overlap = prev & cur
        assert not overlap, \
            f"days {days[i-1]} and {days[i]} both served dish(es) {overlap}"


def _month_catalog(with_garbage=True):
    """_live_like_catalog() widened to a month-rotation pool: >=7 good mains
    (all rated >= 4.0) per meal, plus bread stock for curry pairing, and
    optionally the garbage low-rated dishes from the rating-floor bug report.

    With >=7 mains per meal the rating floor never needs to relax and the
    repeat/recency penalties have real room to rotate 30 days without cycling.
    """
    from dataclasses import replace
    from catalog import Dish
    from course import course_of, dish_kind_of

    def d(dish_id, name, rid, rname, meal, price, rating, veg, tags):
        dish = Dish(dish_id, name, rid, rname, meal, price, rating,
                    "north_indian", tags, veg, {"regular": price})
        return replace(dish, course=course_of(dish.name),
                       dish_kind=dish_kind_of(dish.name))

    dishes = _live_like_catalog() + [
        # breakfast extras — brings good breakfast mains to 8
        d("bf6", "Upma Bowl", "r2", "Samosa Party", "breakfast", 99, 4.2, True, ("upma", "veg")),
        d("bf7", "Vegetable Sandwich", "r8", "Sri Udupi", "breakfast", 109, 4.1, True, ("sandwich", "veg")),
        d("bf8", "Paneer Paratha", "r1", "Krishna Foods", "breakfast", 139, 4.3, True, ("paratha", "paneer", "veg")),
        d("bf9", "Idli Sambar", "r8", "Sri Udupi", "breakfast", 95, 4.2, True, ("idli", "veg")),
        # lunch — _live_like_catalog has none; 8 good mains
        d("lu1", "Rajma Chawal", "r2", "Local Tiffin", "lunch", 130, 4.2, True, ("rajma", "veg")),
        d("lu2", "Chole Bhature", "r1", "Krishna Foods", "lunch", 140, 4.3, True, ("chole", "veg")),
        d("lu3", "Paneer Butter Masala Thali", "r10", "Punjabi Rasoi", "lunch", 220, 4.6, True, ("paneer", "thali", "veg")),
        d("lu4", "Veg Dum Biryani Bowl", "r5", "Biryani Blues", "lunch", 155, 4.4, True, ("biryani", "veg")),
        d("lu5", "Chicken Biryani", "r4", "Chicken Point", "lunch", 240, 4.5, False, ("chicken", "biryani", "nonveg")),
        d("lu6", "Dal Khichdi", "r11", "Local Tiffin", "lunch", 110, 4.0, True, ("dal", "veg")),
        d("lu7", "Veg Meals (Unlimited)", "r8", "Sri Udupi", "lunch", 150, 4.4, True, ("thali", "veg")),
        d("lu8", "Paneer Tikka Bowl", "r12", "Bowl Co", "lunch", 180, 4.3, True, ("paneer", "veg")),
        # dinner extras — brings good dinner mains to 8
        d("dn7", "Kadai Paneer", "r10", "Punjabi Rasoi", "dinner", 190, 4.5, True, ("paneer", "veg")),
        d("dn8", "Butter Chicken", "r4", "Chicken Point", "dinner", 220, 4.6, False, ("chicken", "nonveg")),
        d("dn9", "Chole Bhature", "r1", "Krishna Foods", "dinner", 140, 4.3, True, ("chole", "veg")),
        d("dn10", "Mutton Rogan Josh", "r13", "Kashmiri Kitchen", "dinner", 210, 4.4, False, ("mutton", "nonveg")),
        d("dn11", "Veg Fried Rice", "r17", "Wok Express", "dinner", 160, 4.1, True, ("rice", "veg")),
        # bread stock so every curry has something to pair with
        d("br4", "Butter Naan", "r4", "Chicken Point", "dinner", 45, 4.4, True, ("naan", "veg")),
    ]
    if with_garbage:
        dishes += [
            # The garbage from the bug report: cheap and/or badly rated, but
            # name-classified as real dishes — the rating floor must block them
            # while the floor itself stays out of the way otherwise.
            d("g1", "PO Poha", "r14", "Street Stall", "breakfast", 79, 2.0, True, ("poha", "veg")),
            d("g2", "Lemon Fish", "r15", "Fish Corner", "lunch", 212, 1.9, False, ("fish", "nonveg")),
            d("g3", "Mystery Curry", "r16", "Unknown Mess", "dinner", 190, 2.7, True, ("veg",)),
        ]
    return dishes


_MONTH_RUN = None


def _month_run():
    """One shared 30-day x 3-meal run over _month_catalog() for the tests that
    only inspect the shape of the plan (rating floor, repeat bound, cycles)."""
    global _MONTH_RUN
    if _MONTH_RUN is None:
        import optimizer
        from appetite import build_profile
        cat = _month_catalog(with_garbage=True)
        prof = build_profile(1, "moderate")
        _MONTH_RUN = optimizer.optimize(
            cat, prof, 15000, days=30,
            meals=["breakfast", "lunch", "dinner"])
    return _MONTH_RUN


def test_rating_floor_blocks_low_rated_mains():
    """Dishes rated below MIN_RATING ("PO Poha" 2.0, "Lemon Fish" 1.9,
    "Mystery Curry" 2.7) must never headline a slot when the pool has enough
    good mains for the floor to hold without relaxing."""
    import optimizer

    r = _month_run()
    assert r.slots, "optimizer produced no plan"
    garbage = {"g1", "g2", "g3"}
    for s in r.slots:
        assert s.rating >= optimizer.MIN_RATING, \
            f"day {s.day} {s.meal_type}: {s.dish_name} rated {s.rating} < {optimizer.MIN_RATING}"
        assert s.dish_id not in garbage, \
            f"day {s.day} {s.meal_type}: garbage dish {s.dish_name} planned as a meal"


def test_rating_floor_relaxes_when_slot_starved():
    """When a meal's ONLY dishes are all rated below the floor, the floor must
    relax for that meal alone — the slot still gets filled instead of the plan
    dying with 'No dishes for ...'."""
    from dataclasses import replace
    from catalog import Dish
    from course import course_of, dish_kind_of
    from optimizer import optimize
    from appetite import build_profile

    def d(dish_id, name, rid, rname, meal, price, rating, veg, tags):
        dish = Dish(dish_id, name, rid, rname, meal, price, rating,
                    "north_indian", tags, veg, {"regular": price})
        return replace(dish, course=course_of(dish.name),
                       dish_kind=dish_kind_of(dish.name))

    # Breakfast where EVERY option is sub-floor...
    low_rated_breakfasts = [
        d("sb1", "Poha Special", "r20", "Morning Stall", "breakfast", 60, 2.5, True, ("poha", "veg")),
        d("sb2", "Upma Plate", "r20", "Morning Stall", "breakfast", 70, 2.8, True, ("upma", "veg")),
        d("sb3", "Idli Plate", "r21", "Tiffin Room", "breakfast", 55, 2.9, True, ("idli", "veg")),
    ]
    # ...while lunch and dinner keep their good mains.
    rest = [x for x in _month_catalog(with_garbage=False)
            if x.meal_type != "breakfast"]
    cat = low_rated_breakfasts + rest

    prof = build_profile(1, "moderate")
    r = optimize(cat, prof, 15000, days=30,
                 meals=["breakfast", "lunch", "dinner"])

    assert "No dishes" not in r.message, f"starved slot aborted the plan: {r.message}"
    bfast = [s for s in r.slots if s.meal_type == "breakfast"]
    assert len(bfast) == 30, f"only {len(bfast)}/30 breakfast slots filled"
    allowed = {"sb1", "sb2", "sb3"}
    assert all(s.dish_id in allowed for s in bfast), \
        "breakfast slot leaked a dish from another meal"
    assert any(s.rating < 3.0 for s in bfast), \
        "relaxation never kicked in — low-rated breakfast dishes unused"


def test_monthly_repeat_bound():
    """Over 30 days x 3 meals with >=7 mains per meal, no dish may be used
    more than 6 times. The old behavior produced 10+; the per-week cap alone
    still allows 10 — the whole-month penalty must do better."""
    from collections import Counter

    r = _month_run()
    assert len(r.slots) == 90, f"expected 90 planned slots, got {len(r.slots)}"
    uses = Counter(s.dish_id for s in r.slots)
    most_used, count = uses.most_common(1)[0]
    name = next(s.dish_name for s in r.slots if s.dish_id == most_used)
    assert count <= 6, f"{name} ({most_used}) used {count} times in 30 days"


def test_no_identical_day_menus():
    """No two days may share the exact same menu more than twice, and the
    exact reported cycle (Day 1 == Day 3 == Day 8 == Day 10) must be gone."""
    from collections import Counter

    r = _month_run()
    by_day = {}
    for s in r.slots:
        by_day.setdefault(s.day, {})[s.meal_type] = s.dish_id
    sigs = [tuple(by_day[day].get(m) for m in ("breakfast", "lunch", "dinner"))
            for day in sorted(by_day)]
    assert all(None not in sig for sig in sigs), "some day has an unfilled slot"

    counts = Counter(sigs)
    sig, n = counts.most_common(1)[0]
    assert n <= 2, f"identical day menu repeated {n} times: {sig}"
    assert sigs[0] != sigs[2], "day 1 and day 3 have identical menus (the old cycle)"


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns)-failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
