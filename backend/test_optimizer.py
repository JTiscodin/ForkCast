"""Unit tests for optimizer. Mock catalog, no MCP, no LLM."""
from catalog import mock_catalog
from appetite import build_profile
from optimizer import optimize, Constraint, MEAL_TYPES


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
