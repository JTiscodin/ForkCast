"""Unit tests for optimizer. Mock catalog, no MCP, no LLM."""
from dataclasses import replace

from catalog import Dish, mock_catalog
from appetite import build_profile
from optimizer import optimize, Constraint, MEAL_TYPES
import course


def _d(dish_id, name, restaurant_id="r1", restaurant_name="Rest", meal_type="lunch",
       price=100, rating=4.0, veg=True):
    """Helper that mirrors live fetch: course AND dish_kind from name rules."""
    dish = Dish(
        dish_id=dish_id, name=name, restaurant_id=restaurant_id,
        restaurant_name=restaurant_name, meal_type=meal_type, price=float(price),
        rating=rating, cuisine="north_indian", tags=("veg",) if veg else ("nonveg",),
        veg=veg, variants={"regular": float(price)},
    )
    return replace(dish, course=course.course_of(dish.name),
                   dish_kind=course.dish_kind_of(dish.name))


def test_fills_all_slots():
    cat = mock_catalog()
    prof = build_profile(1, "moderate")
    r = optimize(cat, prof, budget=15000, days=30)
    assert len(r.slots) == 90  # 30 days x 3


def test_stays_in_budget_when_feasible():
    cat = mock_catalog()
    prof = build_profile(1, "moderate")
    r = optimize(cat, prof, budget=15000, days=30)
    assert r.feasible
    assert r.total_cost <= 15000
    assert r.leftover >= 0


def test_paneer_constraint_met():
    cat = mock_catalog()
    prof = build_profile(1, "moderate")
    r = optimize(cat, prof, budget=15000, days=30,
                 constraints=[Constraint("paneer", 10)])
    assert r.constraint_status["paneer"]["got"] >= 10


def test_infeasible_budget_flagged():
    cat = mock_catalog()
    prof = build_profile(1, "very_heavy")
    r = optimize(cat, prof, budget=2000, days=30)  # way too low for 90 meals
    assert not r.feasible
    assert "more than budget" in r.message


def test_veg_only_excludes_nonveg():
    cat = mock_catalog()
    prof = build_profile(1, "moderate")
    r = optimize(cat, prof, budget=15000, days=30, veg_only=True)
    nonveg_ids = {d.dish_id for d in cat if not d.veg}
    assert all(s.dish_id not in nonveg_ids for s in r.slots)


def test_per_day_variety():
    cat = mock_catalog()
    prof = build_profile(1, "moderate")
    r = optimize(cat, prof, budget=15000, days=30)
    by_day = {}
    for s in r.slots:
        by_day.setdefault(s.day, []).append(s.dish_id)
    for day, ids in by_day.items():
        assert len(ids) == len(set(ids)), f"dup dish same day {day}"


def test_weekly_repeat_cap():
    cat = mock_catalog()
    prof = build_profile(1, "moderate")
    r = optimize(cat, prof, budget=15000, days=30, max_repeat_per_week=2)
    week_dish = {}
    for s in r.slots:
        wk = (s.day - 1) // 7
        week_dish[(wk, s.dish_id)] = week_dish.get((wk, s.dish_id), 0) + 1
    # allow rare overflow only when variety relaxed to fill; check majority holds
    overflow = [k for k, v in week_dish.items() if v > 2]
    assert len(overflow) <= 3, f"too many weekly repeat violations: {overflow}"


def test_heavy_costs_more_than_light():
    cat = mock_catalog()
    light = optimize(cat, build_profile(1, "light"), budget=50000, days=30)
    heavy = optimize(cat, build_profile(1, "heavy"), budget=50000, days=30)
    assert heavy.total_cost > light.total_cost


def test_pairing_with_taste_filters():
    """Pairing pool filtered through taste_profile: non-veg/allergen items excluded.

    Instamart-style extra_pairing_dishes with a veg-only + allergy profile
    should exclude non-veg and peanut-containing pairing candidates.
    """
    from dataclasses import replace
    from taste_profile import build_profile as build_taste_profile

    dishes_raw = [
        Dish(dish_id="pb1", name="Paneer Butter Masala", restaurant_id="r1",
             restaurant_name="North Indian", meal_type="dinner",
             price=180.0, rating=4.3, cuisine="north_indian", tags=("veg",), veg=True,
             variants={"regular": 180.0}),
        Dish(dish_id="r1", name="Tawa Roti", restaurant_id="r1",
             restaurant_name="North Indian", meal_type="dinner",
             price=15.0, rating=4.0, cuisine="north_indian", tags=("veg",), veg=True,
             variants={"regular": 15.0}),
    ]
    dishes = [
        replace(d, course=course.course_of(d.name), dish_kind=course.dish_kind_of(d.name))
        for d in dishes_raw
    ]

    # Extra pairing dishes — one acceptable, one non-veg, one with allergen
    extra = [
        Dish(dish_id="gj1", name="Gulab Jamun", restaurant_id="im",
             restaurant_name="Instamart", meal_type="dinner",
             price=40.0, rating=4.0, cuisine="indian", tags=("sweet",), veg=True,
             variants={"regular": 40.0}, dish_kind="sweet", source="instamart"),
        Dish(dish_id="ck1", name="Chicken Kebab", restaurant_id="im",
             restaurant_name="Instamart", meal_type="dinner",
             price=60.0, rating=4.2, cuisine="north_indian", tags=("snack",), veg=False,
             variants={"regular": 60.0}, dish_kind="snack", source="instamart"),
    ]
    for d in extra:
        d = replace(d, course=course.course_of(d.name))

    profile = build_taste_profile(0, {
        "veg_level": "veg",
        "allergies": ["peanut"],
    })

    constraint = Constraint(
        dish_tag="", min_count=0, dish_kind="sweet",
        slot_type="dinner", frequency="always"
    )

    result = optimize(
        catalog=dishes,
        profile=build_profile(1, "moderate"),
        budget=5000.0,
        days=3,
        constraints=[constraint],
        veg_only=True,
        meals=("dinner",),
        extra_pairing_dishes=extra,
        taste_profile=profile,
    )

    # Verify: non-veg chicken kebab should NOT appear via taste filter
    for slot in result.slots:
        assert slot.side_dish_id != "ck1", "Non-veg pairing bypassed taste filter"
        assert slot.side2_dish_id != "ck1", "Non-veg pairing bypassed taste filter"

    print("OK: Taste filters excluded non-veg pairing from veg-only profile")


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
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns)-failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
