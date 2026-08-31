"""Tests for the swap path quality fixes.

Covers:
  - alternatives() applies the optimizer's quality gates (MIN_RATING floor,
    NEVER_STANDALONE, price-aware COMPLETE standalone check, meal_type,
    current-dish exclusion)
  - veg_only filters meat candidates
  - used_counts demotes dishes the rest of the plan already hammers
  - /swap validation: unknown dish, tampered fields and bare breads rejected
  - a swapped-in curry gets a recomputed bread pairing instead of losing it
  - plans.total_cost / feasible are refreshed so the approve guard stays honest

Plain-function style, in-memory SQLite, synthetic Dish catalogs — no network,
no MockMCPClient, no disk DB. Run:
    python test_swap.py
"""
from dataclasses import replace

from catalog import Dish, variant_price
import course as course_rules
from course import course_of
from db import get_conn, SCHEMA
from optimizer import MIN_RATING
from order_executor import OrderExecutor
from plan_service import PlanService
from wallet_service import WalletService
from swap_service import (alternatives, apply_swap, pick_side, recompute_plan_totals,
                          SwapError)


# ---- helpers -----------------------------------------------------------------

def _d(dish_id, name, restaurant_id, restaurant_name, meal_type, price, rating,
       veg=True):
    """Synthetic Dish classified from its NAME, same path as live/mock fetches."""
    dish = Dish(
        dish_id=dish_id, name=name, restaurant_id=restaurant_id,
        restaurant_name=restaurant_name, meal_type=meal_type, price=price,
        rating=rating, cuisine="north_indian",
        tags=("veg",) if veg else ("nonveg",), veg=veg,
        variants={"regular": price},
    )
    return replace(dish, course=course_of(dish.name),
                   dish_kind=course_rules.dish_kind_of(dish.name))


def fresh_db():
    conn = get_conn(":memory:")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def mk_plan(conn, budget=5000):
    uid = conn.execute("INSERT INTO users(name) VALUES ('Tester')").lastrowid
    pid = conn.execute(
        "INSERT INTO plans (user_id, month, budget, total_cost, feasible, status) "
        "VALUES (?, '2026-07', ?, 0, 1, 'draft')", (uid, budget)).lastrowid
    conn.commit()
    return uid, pid


def mk_slot(conn, plan_id, day, meal_type, dish_id, name, price, rating=4.0,
            restaurant_id="r1", restaurant_name="Rest One", course="complete",
            side_dish_id="", side_dish_name="", side_qty=0, side_price=0.0):
    cur = conn.execute(
        "INSERT INTO meal_slots (plan_id, day, meal_type, dish_id, dish_name, "
        "restaurant_id, restaurant_name, image_url, price, rating, variant, "
        "status, course, side_dish_id, side_dish_name, side_qty, side_price, "
        "side_restaurant_name, side_image_url) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,'regular','planned',?,?,?,?,?,?,?)",
        (plan_id, day, meal_type, dish_id, name, restaurant_id,
         restaurant_name, "", price, rating, course,
         side_dish_id, side_dish_name, side_qty, side_price, "", ""))
    conn.commit()
    return cur.lastrowid


def body_for(dish, mult=1.0, **overrides):
    """A well-formed swap body for a catalog dish — what the UI would echo
    back from an /alternatives candidate."""
    variant, price = variant_price(dish, mult)
    b = {"dish_id": dish.dish_id, "name": dish.name,
         "restaurant_id": dish.restaurant_id,
         "restaurant_name": dish.restaurant_name,
         "image_url": getattr(dish, "image_url", ""),
         "price": price, "rating": dish.rating, "variant": variant}
    b.update(overrides)
    return b


# ---- catalogs ------------------------------------------------------------------

def alt_catalog():
    """Dinner pool mixing clean alternatives with the junk the old code offered:
    a 1.9-star curry and in-band bread/staple that would win on raw proximity."""
    return [
        _d("comp1", "Veg Dum Biryani Bowl", "r7", "Bowl Co", "dinner", 150, 4.5),
        _d("dm1", "Dal Makhani", "r2", "Local Tiffin", "dinner", 151, 4.0),
        _d("rm1", "Rajma Masala", "r2", "Local Tiffin", "dinner", 154, 4.0),
        _d("meat1", "Butter Chicken", "r5", "Paradise", "dinner", 155, 4.7, veg=False),
        _d("low1", "Lemon Fish Curry", "r8", "Fish Corner", "dinner", 149, 1.9, veg=False),
        _d("rum1", "Rumali Roti", "r3", "Punjabi Rasoi", "dinner", 148, 4.6),
        _d("st1", "Jeera Rice", "r3", "Punjabi Rasoi", "dinner", 150, 4.5),
        _d("cur1", "Paneer Butter Masala", "r3", "Punjabi Rasoi", "dinner", 210, 4.6),
        # wrong meal slot entirely — must never surface for dinner
        _d("brk1", "Masala Dosa", "r1", "Sri Udupi", "breakfast", 150, 4.8),
    ]


def pair_catalog(with_roti=True):
    """Curry + its potential accompaniments at one restaurant."""
    dishes = [
        _d("cur1", "Paneer Butter Masala", "r3", "Punjabi Rasoi", "dinner", 210, 4.6),
        _d("naan1", "Butter Naan", "r3", "Punjabi Rasoi", "dinner", 45, 4.4),
        _d("rice1", "Jeera Rice", "r3", "Punjabi Rasoi", "dinner", 90, 4.3),
    ]
    if with_roti:
        dishes.insert(1, _d("rot1", "Tawa Roti", "r3", "Punjabi Rasoi", "dinner", 12, 4.1))
    return dishes


# ---- alternatives gates --------------------------------------------------------

def test_alternatives_exclude_low_rated_breads_and_wrong_slot():
    slot = {"meal_type": "dinner", "dish_id": "comp1", "price": 150}
    res = alternatives(slot, alt_catalog(), 1.0, band=100)
    ids = [c["dish_id"] for c in res]
    assert "low1" not in ids, f"rating {MIN_RATING} floor let sub-rated dish in"
    assert "rum1" not in ids, "bare bread offered as a meal (it was closest in price)"
    assert "st1" not in ids, "staple rice offered as a meal"
    assert "brk1" not in ids, "wrong meal_type leaked into dinner alternatives"
    assert "comp1" not in ids, "current dish offered as its own alternative"
    assert "meat1" in ids and "cur1" in ids, "legitimate curries were filtered too"
    # ranking still prefers closeness to target among clean candidates
    assert ids.index("meat1") < ids.index("cur1")


def test_alternatives_veg_only_filters_meat():
    slot = {"meal_type": "dinner", "dish_id": "comp1", "price": 150}
    res = alternatives(slot, alt_catalog(), 1.0, band=100, veg_only=True)
    ids = [c["dish_id"] for c in res]
    assert "meat1" not in ids and "low1" not in ids
    assert all(c["veg"] for c in res)
    assert "dm1" in ids and "cur1" in ids


def test_used_counts_demotes_repeated_dishes():
    slot = {"meal_type": "dinner", "dish_id": "comp1", "price": 150}
    # without counts, Dal Makhani (Rs1 away) beats Rajma Masala (Rs4 away)
    base = [c["dish_id"] for c in alternatives(slot, alt_catalog(), 1.0)]
    assert base.index("dm1") < base.index("rm1")
    # hammered across the month -> sinks behind the farther neighbour
    used = {"Dal Makhani": 10}
    demoted = [c["dish_id"] for c in alternatives(slot, alt_catalog(), 1.0,
                                                  used_counts=used)]
    assert demoted.index("rm1") < demoted.index("dm1"), \
        "repetition penalty did not demote the hammered dish"
    # keying by dish_id must work identically to keying by name
    by_id = [c["dish_id"] for c in alternatives(slot, alt_catalog(), 1.0,
                                                used_counts={"dm1": 10})]
    assert by_id == demoted


# ---- swap validation ------------------------------------------------------------

def test_swap_rejects_unknown_and_tampered_fields():
    conn = fresh_db()
    _, pid = mk_plan(conn)
    sid = mk_slot(conn, pid, 1, "dinner", "old1", "Old Dish", 150)
    cat = pair_catalog()
    slot = conn.execute("SELECT * FROM meal_slots WHERE id=?", (sid,)).fetchone()

    for bad, why in [
        (body_for(_d("ghost", "Ghost Curry", "r3", "Punjabi Rasoi", "dinner", 200, 4.0)),
         "dish_id not in catalog"),
        (body_for(cat[0], price=999.0), "tampered price"),
        (body_for(cat[0], rating=5.0), "tampered rating"),
        (body_for(cat[0], name="Totally Different"), "tampered name"),
    ]:
        try:
            apply_swap(conn, slot, bad, cat)
            assert False, f"expected SwapError for {why}"
        except SwapError as e:
            assert str(e) == "Unknown dish", f"{why}: wrong message {e}"


def test_swap_rejects_bare_roti_as_main():
    conn = fresh_db()
    _, pid = mk_plan(conn)
    sid = mk_slot(conn, pid, 1, "dinner", "old1", "Old Dish", 150)
    roti = _d("rot1", "Tawa Roti", "r3", "Punjabi Rasoi", "dinner", 12, 4.1)
    slot = conn.execute("SELECT * FROM meal_slots WHERE id=?", (sid,)).fetchone()
    try:
        apply_swap(conn, slot, body_for(roti), [roti])
        assert False, "expected SwapError for bare bread"
    except SwapError as e:
        assert str(e) == "Tawa Roti can't be a meal on its own"


# ---- re-pairing + totals ---------------------------------------------------------

def test_swap_pairs_swapped_in_curry_with_cheapest_total_side():
    conn = fresh_db()
    _, pid = mk_plan(conn, budget=5000)
    # start from a complete dish with NO side
    sid = mk_slot(conn, pid, 1, "dinner", "old1", "Old Dish", 150)
    cat = pair_catalog()
    slot = conn.execute("SELECT * FROM meal_slots WHERE id=?", (sid,)).fetchone()

    updated = apply_swap(conn, slot, body_for(cat[0]), cat)  # Paneer Butter Masala

    # Tawa Roti Rs12 x2 = Rs24 beats Naan Rs45x1 and Jeera Rice Rs90x1 on TOTAL,
    # and 24 <= 0.9 * 210 so the pairing cap doesn't bite.
    assert updated["side_dish_id"] == "rot1"
    assert updated["side_dish_name"] == "Tawa Roti"
    assert updated["side_qty"] == 2
    assert updated["side_price"] == 24.0
    assert updated["course"] == "curry"
    assert round(updated["price"] + updated["side_price"], 2) == 234.0
    assert updated["why_text"] is None  # cached why invalidated on swap


def test_swap_clears_side_when_no_affordable_accompaniment():
    conn = fresh_db()
    _, pid = mk_plan(conn, budget=5000)
    # previous dish HAD a side; new curry is cheap, sides are all above 0.9x
    sid = mk_slot(conn, pid, 1, "dinner", "cur1", "Dal Tadka", 30,
                  side_dish_id="naan1", side_dish_name="Butter Naan",
                  side_qty=1, side_price=45.0)
    dal = _d("dal1", "Dal Tadka", "r3", "Punjabi Rasoi", "dinner", 30, 4.2)
    cat = [_d("naan1", "Butter Naan", "r3", "Punjabi Rasoi", "dinner", 45, 4.4), dal]
    slot = conn.execute("SELECT * FROM meal_slots WHERE id=?", (sid,)).fetchone()

    updated = apply_swap(conn, slot, body_for(dal), cat)
    assert updated["side_dish_id"] == "" and updated["side_price"] == 0.0, \
        "stale expensive side kept after swap to cheap curry"


def test_pick_side_prefers_same_restaurant_then_crosses():
    main = _d("cur1", "Paneer Butter Masala", "r3", "Punjabi Rasoi", "dinner", 100, 4.6)
    same_expensive = _d("rot_hi", "Rumali Roti", "r3", "Punjabi Rasoi", "dinner", 90, 4.5)
    other_cheap = _d("rot_lo", "Tandoori Roti", "r5", "Paradise", "lunch", 10, 4.2)
    # same-restaurant option busts the 0.9x cap (90 > 90? no: 2x90=180 > 90);
    # the affordable one comes from another restaurant -> cross over.
    side = pick_side(main, 100, [same_expensive, other_cheap])
    assert side is not None and side.dish_id == "rot_lo"


def test_swap_recomputes_plan_totals_and_feasible():
    conn = fresh_db()
    w = WalletService(conn)
    plan_svc = PlanService(conn, w, OrderExecutor(mode="mock"))
    _, pid = mk_plan(conn, budget=200)
    mk_slot(conn, pid, 1, "lunch", "a1", "Thali A", 120)
    sid2 = mk_slot(conn, pid, 1, "dinner", "b1", "Thali B", 60)

    biryani = _d("cb1", "Chicken Biryani", "r5", "Paradise", "dinner", 95, 4.5,
                 veg=False)
    slot = conn.execute("SELECT * FROM meal_slots WHERE id=?", (sid2,)).fetchone()
    apply_swap(conn, slot, body_for(biryani), [biryani])

    p = conn.execute("SELECT total_cost, feasible FROM plans WHERE id=?",
                     (pid,)).fetchone()
    assert p["total_cost"] == 215.0, "plans.total_cost not refreshed after swap"
    assert p["feasible"] == 0, "over-budget plan still flagged feasible"

    # the approve guard now sees the truth instead of stale draft numbers
    try:
        plan_svc.approve_plan(pid)
        assert False, "over-budget plan was approved after swap"
    except ValueError as e:
        assert "over budget" in str(e).lower()

    # swapping back under budget flips feasibility again
    cheap = _d("cc1", "Curd Rice", "r1", "Sri Udupi", "dinner", 70, 4.0)
    row = conn.execute("SELECT * FROM meal_slots WHERE id=?", (sid2,)).fetchone()
    apply_swap(conn, row, body_for(cheap), [cheap])
    p = conn.execute("SELECT total_cost, feasible FROM plans WHERE id=?",
                     (pid,)).fetchone()
    assert p["total_cost"] == 190.0 and p["feasible"] == 1


def test_recompute_totals_counts_sides_not_just_mains():
    conn = fresh_db()
    _, pid = mk_plan(conn, budget=1000)
    mk_slot(conn, pid, 1, "dinner", "cur1", "Paneer Butter Masala", 210,
            side_dish_id="rot1", side_dish_name="Tawa Roti", side_qty=2,
            side_price=24.0)
    total = recompute_plan_totals(conn, pid)
    assert total == 234.0, "side_price excluded from plans.total_cost"


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns)-failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
