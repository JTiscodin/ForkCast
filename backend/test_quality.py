"""FAILING (red) tests for plan-quality bugs seen in a live 30-day plan.

Each test reproduces one symptom observed in real optimizer output and asserts
the CORRECT behavior, so before the fix they FAIL and after the fix they PASS:

  - One dish appeared 9 times in a month, several others 7-8 times
    (weekly cap of 2 resets every week; W_TOTAL_REPEAT_PENALTY=0.4 is too weak
    against ratings ~4+).
  - Day1 == Day3 == Day8 == Day10 had identical menus (RECENT_WINDOW=7 penalty
    decays to exactly zero at day+7, matching the weekly reset -> fixed cycles).
  - "Masala Curry" Rs75 was paired with 2x Rumali Roti @Rs45 = Rs90 — the side
    cost MORE than the main. pick_side() minimises unit price s.price instead
    of total cost s.price * accompaniment_qty(s.name).

Synthetic catalogs only — no network, no DB. Run:
    python test_quality.py
"""
from collections import Counter
from dataclasses import replace

from appetite import build_profile
from catalog import Dish, mock_catalog
import course
from optimizer import optimize

MEALS = ("breakfast", "lunch", "dinner")
DAYS = 30
BUDGET = 20000  # generous: ~Rs13k realistic spend for these pools, so budget
                # pacing never confounds the variety assertions.

# Realistic Indian names whose FORM word makes course.classify return COMPLETE,
# so every synthetic main can headline its slot without pairing noise.
_BREAKFAST_BASES = (
    "Masala Dosa", "Poha Plate", "Idli Vada Combo", "Aloo Paratha",
    "Rava Dosa", "Upma Bowl", "Moong Dal Chilla", "Vegetable Khichdi",
    "Onion Uttapam", "Besan Chilla", "Sabudana Khichdi", "Idli Plate",
)
_MAIN_BASES = (
    "Chicken Biryani", "Paneer Thali", "Veg Fried Rice", "Hakka Noodles",
    "Steamed Momos", "Rajma Chawal", "Dal Khichdi", "Chole Bhature",
    "Curd Rice", "Veg Dum Biryani", "Egg Fried Rice", "Special Thali",
)


def _d(dish_id, name, restaurant_id, restaurant_name, meal_type, price, rating):
    dish = Dish(
        dish_id=dish_id, name=name, restaurant_id=restaurant_id,
        restaurant_name=restaurant_name, meal_type=meal_type, price=price,
        rating=rating, cuisine="north_indian", tags=("veg",), veg=True,
        variants={"regular": price},
    )
    # classify from the NAME, same path the live Swiggy fetch uses — both axes.
    return replace(dish, course=course.course_of(name),
                   dish_kind=course.dish_kind_of(name))


def _synth_catalog(n_per_meal, seed=0):
    """n_per_meal COMPLETE mains per meal slot, shaped like the live data that
    produced the bugs: ONE cheap 5-star standout per slot sitting above a
    mediocre, pricier crowd (the live neighbourhood had a few 4.5+ dishes over
    a sea of 3.x). Prices/ratings vary with seed via modular arithmetic (no
    random module) so each seed is a different but deterministic neighbourhood."""
    dishes = []
    for mi, meal in enumerate(MEALS):
        bases = (_BREAKFAST_BASES if meal == "breakfast" else _MAIN_BASES)
        for i in range(n_per_meal):
            base = bases[i % len(bases)]
            name = f"{base} {seed}-{i}"
            if i == 0:      # the standout the optimizer hammers (live: 9x)
                price = float(80 + ((seed * 17 + mi * 5) % 30))
                rating = 5.0
            else:
                price = float(170 + ((i * 23 + seed * 11 + mi * 7) % 90))
                rating = round(3.3 - 0.15 * (i % 3), 1)   # 3.3 .. 3.0
            dishes.append(_d(f"{meal[0]}{seed}_{i}", name,
                             f"r{(i % 3) + 1}", f"Rest {mi}{i % 3}",
                             meal, price, rating))
    return dishes


def run_plan(catalog_list, **kw):
    profile = build_profile(1, "moderate")
    return optimize(catalog_list, profile, BUDGET, days=DAYS, **kw)


def dish_use_counts(result):
    return Counter(s.dish_id for s in result.slots)


def day_signatures(result):
    """Per-day menu signature: sorted (meal, dish_id) pairs."""
    per_day = {}
    for s in result.slots:
        per_day.setdefault(s.day, []).append((s.meal_type, s.dish_id))
    return {d: tuple(sorted(v)) for d, v in per_day.items()}


def max_repeats(result):
    counts = dish_use_counts(result)
    return max(counts.values()), counts.most_common(3)


def worst_duplicate_days(result):
    sigs = Counter(day_signatures(result).values())
    if not sigs:
        return 0, None
    sig, count = sigs.most_common(1)[0]
    return count, sig


# ---- 1. monthly repeat ceiling --------------------------------------------
# Live symptom: one dish 9x, several 7-8x over 30 days. The weekly cap of 2
# resets every week, so 2/week * ~5 weeks lets a favourite hit double digits.
def test_monthly_repeat_ceiling_small_pool():
    for n in (5, 6):
        res = run_plan(_synth_catalog(n, seed=1))
        ceiling = -(-DAYS // n) + 2          # ceil(30/n)+2
        worst, top = max_repeats(res)
        assert worst <= ceiling, (
            f"N={n}: worst dish used {worst}x, ceiling {ceiling}; top uses {top}")
    for n in (8, 12):
        res = run_plan(_synth_catalog(n, seed=1))
        worst, top = max_repeats(res)
        assert worst <= 6, f"N={n}: worst dish used {worst}x (> 6); top uses {top}"


# ---- 2. identical day menus -------------------------------------------------
# Live symptom: Day1 == Day3 == Day8 == Day10, byte-identical menus. The
# recency penalty fades to zero at exactly RECENT_WINDOW=7 days while the
# weekly cap resets too, so greedy scoring re-picks the same winners on the
# same weekday forever.
def test_no_identical_day_menus_beyond_two():
    res = run_plan(_synth_catalog(6, seed=0))
    dup_count, sig = worst_duplicate_days(res)
    assert dup_count <= 2, (
        f"a menu signature occurs {dup_count}x in the month (max allowed 2); "
        f"example signature {sig}")


# ---- 3. consecutive-day overlap ---------------------------------------------
# Live symptom: back-to-back days shared 2-3 items. For MAINS alone the "not
# served yesterday" preference already rotates (a same-main repeat is only
# possible if a slot's whole pool was eaten yesterday, which cannot happen at
# one meal per slot) — but the user eats the ACCOMPANIMENT too, and pick_side()
# returns the same cheapest bread for a curry every single day. So adjacent
# days keep serving the identical rotis alongside their curries.
#
# This catalog puts one top-rated curry per meal, each at a restaurant with TWO
# bread options — rotation is POSSIBLE, it just never happens today. The day's
# consumed set therefore counts mains AND their accompaniments.
def test_no_consecutive_day_overlap():
    cat = [
        # breakfast: standout curry + its restaurant's two breads + filler mains
        _d("cb1", "Paneer Butter Masala", "rb", "Bhoj", "breakfast", 150.0, 4.9),
        _d("sb1", "Tawa Roti", "rb", "Bhoj", "breakfast", 14.0, 4.0),
        _d("sb2", "Butter Naan", "rb", "Bhoj", "breakfast", 50.0, 4.2),
        _d("bc1", "Masala Dosa", "rx", "Udupi", "breakfast", 90.0, 4.2),
        _d("bc2", "Poha Plate", "rx", "Udupi", "breakfast", 60.0, 4.0),
        # lunch
        _d("cl1", "Kadai Paneer", "rl", "Rasoi", "lunch", 180.0, 4.9),
        _d("sl1", "Missi Roti", "rl", "Rasoi", "lunch", 16.0, 4.0),
        _d("sl2", "Laccha Paratha", "rl", "Rasoi", "lunch", 55.0, 4.2),
        _d("lc1", "Chicken Biryani", "ry", "Paradise", "lunch", 220.0, 4.2),
        _d("lc2", "Veg Dum Biryani", "ry", "Paradise", "lunch", 160.0, 4.0),
        # dinner
        _d("cd1", "Dal Makhani", "rd", "Dhaba", "dinner", 160.0, 4.9),
        _d("sd1", "Rumali Roti", "rd", "Dhaba", "dinner", 20.0, 4.0),
        _d("sd2", "Tandoori Roti", "rd", "Dhaba", "dinner", 35.0, 4.2),
        _d("dc1", "Chole Bhature", "rz", "Punjabi", "dinner", 140.0, 4.2),
        _d("dc2", "Curd Rice", "rz", "Punjabi", "dinner", 100.0, 4.0),
    ]
    res = run_plan(cat)
    paired = [s for s in res.slots if s.side_price > 0]
    assert paired, "no curry was ever paired — catalog setup broken"

    consumed = {}   # day -> everything the user eats: mains + sides
    for s in res.slots:
        consumed.setdefault(s.day, set()).add(s.dish_id)
        if s.side_dish_id:
            consumed[s.day].add(s.side_dish_id)
    worst_day, worst = max(
        ((d, len(consumed[d] & consumed[d + 1])) for d in range(1, DAYS)),
        key=lambda t: t[1])
    assert worst <= 1, (
        f"days {worst_day} and {worst_day + 1} share {worst} eaten items "
        f"(mains + breads; max 1): "
        f"{sorted(consumed[worst_day] & consumed[worst_day + 1])}")


# ---- 4. side must never cost more than the main ------------------------------
# Live symptom: Masala Curry Rs75 paired with 2x Rumali Roti @Rs45 = Rs90 side.
# pick_side() takes the cheapest UNIT price among SAME-restaurant sides only;
# it falls back to other restaurants when the curry's restaurant has NO bread,
# but not when that restaurant merely has an EXPENSIVE one — exactly the gap
# this catalog exercises (the cheap Tawa Roti lives at a different restaurant).
def test_side_cost_never_exceeds_main():
    cat = [
        _d("bq1", "Masala Dosa", "r1", "Udupi", "breakfast", 90.0, 4.4),
        _d("bq2", "Poha Plate", "r2", "Tiffin", "breakfast", 60.0, 4.2),
        _d("lq1", "Paneer Thali", "r3", "Rasoi", "lunch", 180.0, 4.5),
        _d("lq2", "Veg Dum Biryani", "r1", "Udupi", "lunch", 160.0, 4.3),
        # the offender: cheap curry whose own restaurant only has pricey bread
        _d("cq1", "Malai Kofta Curry", "r9", "Curry House", "dinner", 75.0, 4.9),
        _d("sq1", "Rumali Roti", "r9", "Curry House", "dinner", 45.0, 4.0),
        # the affordable bread exists — but at ANOTHER restaurant
        _d("sq2", "Tawa Roti", "r8", "Rotiwala", "dinner", 12.0, 4.1),
        # filler dinner mains so the pool isn't just the curry
        _d("dq1", "Chicken Biryani", "r8", "Rotiwala", "dinner", 220.0, 4.4),
        _d("dq2", "Curd Rice", "r2", "Tiffin", "dinner", 100.0, 4.0),
    ]
    res = run_plan(cat)
    paired = [s for s in res.slots if s.side_price > 0]
    assert any(s.dish_id == "cq1" for s in paired), \
        "the Rs75 curry was never planned — catalog setup broken"
    for s in paired:
        assert s.side_price <= s.price * 0.9, (
            f"day {s.day} {s.meal_type}: '{s.dish_name}' Rs{s.price} got side "
            f"'{s.side_dish_name}' x{s.side_qty} = Rs{s.side_price} "
            f"(ratio {s.side_price / s.price:.2f})")


# ---- 5. minimise TOTAL side cost, not unit price -----------------------------
# Live symptom root cause: pick_side() sorts by s.price alone. Butter Naan
# Rs55 x1 (Rs55 total) loses to Rumali Roti Rs40 x2 (Rs80 total) even though
# both are same-restaurant options — the user pays Rs25 extra every time.
def test_cheap_unit_vs_cheap_total_side():
    cat = [
        _d("bu1", "Masala Dosa", "r1", "Udupi", "breakfast", 90.0, 4.4),
        _d("bu2", "Poha Plate", "r2", "Tiffin", "breakfast", 60.0, 4.2),
        _d("lu1", "Paneer Thali", "r3", "Rasoi", "lunch", 180.0, 4.5),
        _d("lu2", "Veg Dum Biryani", "r1", "Udupi", "lunch", 160.0, 4.3),
        _d("cw1", "Shahi Paneer Curry", "r7", "Gravy Co", "dinner", 200.0, 4.9),
        _d("sw1", "Butter Naan", "r7", "Gravy Co", "dinner", 55.0, 4.3),  # 55 total
        _d("sw2", "Rumali Roti", "r7", "Gravy Co", "dinner", 40.0, 4.1),  # 80 total!
        _d("du1", "Chicken Biryani", "r8", "Paradise", "dinner", 220.0, 4.4),
        _d("du2", "Curd Rice", "r2", "Tiffin", "dinner", 100.0, 4.0),
    ]
    res = run_plan(cat)
    curry_slots = [s for s in res.slots if s.dish_id == "cw1"]
    assert curry_slots, "the Shahi Paneer Curry was never planned — setup broken"
    for s in curry_slots:
        assert s.side_price <= 60, (
            f"day {s.day}: curry picked side '{s.side_dish_name}' "
            f"x{s.side_qty} = Rs{s.side_price} total; correct choice "
            f"(Butter Naan x1 = Rs55) is cheaper")


# ---- 6. rating floor holds when alternatives exist ---------------------------
# REGRESSION GUARD: this test is expected to PASS against the current code —
# keep it anyway. It pins the fallback behaviour: if the MIN_RATING=3.0 floor
# is ever relaxed "too eagerly" when alternatives exist (e.g. by a future
# fallback path), a 2.5-star dish must still never be planned while >=3.0
# candidates remain for the slot. Sub-3.0 dishes here are deliberately CHEAP
# so any eager relaxation would find them attractive.
def test_rating_floor_not_bypassed_when_alternatives_exist():
    cat = [
        _d("bf1", "Masala Dosa", "r1", "Udupi", "breakfast", 90.0, 4.4),
        _d("bf2", "Poha Plate", "r2", "Tiffin", "breakfast", 50.0, 2.5),  # cheap+bad
        _d("bf3", "Idli Vada Combo", "r3", "Rasoi", "breakfast", 85.0, 4.1),
        _d("ln1", "Paneer Thali", "r3", "Rasoi", "lunch", 180.0, 4.5),
        _d("ln2", "Veg Fried Rice", "r1", "Udupi", "lunch", 70.0, 2.5),   # cheap+bad
        _d("ln3", "Veg Dum Biryani", "r1", "Udupi", "lunch", 160.0, 4.2),
        _d("dn1", "Chicken Biryani", "r8", "Paradise", "dinner", 220.0, 4.4),
        _d("dn2", "Dal Khichdi", "r2", "Tiffin", "dinner", 65.0, 2.5),    # cheap+bad
        _d("dn3", "Chole Bhature", "r3", "Rasoi", "dinner", 140.0, 4.0),
    ]
    res = run_plan(cat)
    bad = [s for s in res.slots if s.rating < 3.0]
    assert not bad, (
        f"sub-3.0 dishes planned despite good alternatives: "
        f"{[(s.day, s.dish_name, s.rating) for s in bad[:5]]}")


# ---- 7. composition purity: no sweets/snacks/beverages as meals --------------
# The optimizer's hard filter must keep dish_kind != meal out of meal slots
# for EVERY appetite level. Build a mixed catalog that deliberately includes
# sweets/snacks/beverages and verify zero leak.

def _purity_catalog():
    """Mixed catalog: mock base mains + non-meal kinds that must be filtered."""
    base = mock_catalog()
    extras = [
        _d("sw1", "Gulab Jamun", "r9", "Sweet Shop", "dinner", 50, 4.9),
        _d("sw2", "Rasgulla", "r9", "Sweet Shop", "lunch", 45, 4.6),
        _d("sw3", "Ice Cream Sundae", "r9", "Sweet Shop", "dinner", 60, 4.7),
        _d("sw4", "Brownie", "r9", "Sweet Shop", "lunch", 55, 4.5),
        _d("sn1", "Samosa", "r9", "Snack Corner", "lunch", 30, 4.5),
        _d("sn2", "Pakora", "r9", "Snack Corner", "dinner", 35, 4.4),
        _d("sn3", "Pani Puri", "r9", "Snack Corner", "dinner", 40, 4.3),
        _d("bv1", "Pepsi", "r9", "Drinks", "lunch", 40, 4.2),
        _d("bv2", "Mango Shake", "r9", "Drinks", "dinner", 50, 4.3),
        _d("cb1", "Cold Drink Nachos + Coke Combo", "r9", "Promo", "dinner", 49, 4.9),
        _d("th1", "Paneer Thali", "r9", "Meals", "dinner", 180, 4.6),
        _d("th2", "Combo Meal", "r9", "Meals", "lunch", 150, 4.4),
    ]
    return base + extras


def _meal_pool(meal):
    """Helper that mirrors optimizer's eligible pool but keeps dish_kind parity."""
    cat = _purity_catalog()
    return [d for d in cat if d.meal_type == meal and d.dish_kind == course.KIND_MEAL
            and d.course not in course.NEVER_STANDALONE]


def _assert_purity(res, level):
    bad = [s for s in res.slots if s.dish_kind != "meal"]
    assert not bad, (
        f"{level}: non-meal kinds leaked into meal slots: "
        f"{[(s.dish_name, s.dish_kind, s.course) for s in bad[:5]]}")
    forbidden = {course.KIND_SWEET, course.KIND_SNACK, course.KIND_BEVERAGE}
    assert not any(s.dish_kind in forbidden for s in res.slots), \
        f"{level}: forbidden kind in slots"
    # also assert via dish_kind field present and correct
    assert all(getattr(s, "dish_kind", "meal") == "meal" for s in res.slots)


def test_composition_purity_light():
    cat = _purity_catalog()
    prof = build_profile(1, "light")
    res = optimize(cat, prof, BUDGET, days=7)
    _assert_purity(res, "light")


def test_composition_purity_moderate():
    cat = _purity_catalog()
    prof = build_profile(1, "moderate")
    res = optimize(cat, prof, BUDGET, days=7)
    _assert_purity(res, "moderate")


def test_composition_purity_heavy():
    cat = _purity_catalog()
    prof = build_profile(1, "heavy")
    res = optimize(cat, prof, BUDGET, days=7)
    _assert_purity(res, "heavy")
    # heavy should get extra component for curries but still no sweet leak
    curries = [s for s in res.slots if s.course == course.CURRY]
    # existence check only if curries were picked
    if curries:
        assert all(s.dish_kind == "meal" for s in curries)


def test_composition_purity_very_heavy():
    cat = _purity_catalog()
    prof = build_profile(1, "very_heavy")
    res = optimize(cat, prof, BUDGET, days=7)
    _assert_purity(res, "very_heavy")


def test_mock_catalog_purity_across_appetites():
    """Directly use mock_catalog plus one sweet per meal to ensure filter holds
    even when sweets are top-rated and cheap."""
    def _cheap_sweet_catalog():
        base = mock_catalog()
        base = list(base)
        # inject top-rated cheap sweets that would dominate on price/rating if not filtered
        base.append(_d("cheap_sw1", "Gulab Jamun", "r9", "Sweet", "breakfast", 30, 5.0))
        base.append(_d("cheap_sw2", "Samosa", "r9", "Snack", "lunch", 25, 5.0))
        base.append(_d("cheap_sw3", "Pepsi", "r9", "Drink", "dinner", 20, 5.0))
        return base
    for lvl in ("light", "moderate", "heavy", "very_heavy"):
        prof = build_profile(1, lvl)
        res = optimize(_cheap_sweet_catalog(), prof, 15000, days=5)
        bad = [s for s in res.slots if s.dish_kind != "meal"]
        assert not bad, f"{lvl} leaked {[(s.dish_name, s.dish_kind) for s in bad]}"


# ---- 8. variety bounds across several seeded neighborhoods -------------------
# Same symptoms as tests 1-2, checked across 5 differently-seeded catalogs so
# the fix can't just be tuned to one pool. Deterministic modular arithmetic
# varies prices/ratings per seed — no random module, fully reproducible.
def test_diversity_holds_across_multiple_random_catalogs():
    for seed in range(5):
        res = run_plan(_synth_catalog(6, seed=seed))
        worst, top = max_repeats(res)
        dup, sig = worst_duplicate_days(res)
        assert worst <= 7, (
            f"seed {seed}: worst dish used {worst}x (ceiling 7); top uses {top}")
        assert dup <= 2, (
            f"seed {seed}: a menu signature occurs {dup}x (max 2); example {sig}")


if __name__ == "__main__":
    import sys

    def _run(name, fn):
        try:
            fn()
            print(f"PASS {name}")
            return True
        except AssertionError as e:
            print(f"FAIL {name}: {e}")
            return False
        except Exception as e:  # noqa: BLE001 — report unexpected crashes too
            print(f"FAIL {name}: UNEXPECTED {type(e).__name__}: {e}")
            return False

    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = sum(_run(name, fn) for name, fn in tests)
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
