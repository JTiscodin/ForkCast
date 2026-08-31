"""RED-first tests for the veg-heavy small-pool plan-quality bugs.

Each test reproduces one symptom of the live plan_id=20 failure (uid 6, heavy
appetite, veg-only, Rs 10000 budget, "at least 10 paneer meals"):

  - The plan came back feasible=False at Rs 13,559.78 -- 35% OVER budget --
    even though a cheaper assignment exists. Pass 1 force-placed the
    best-rated AFFORDABLE paneer dishes (Rs 881 Lababdar twice in a row)
    because its fallback ignored money, and pass 2's reserve only counted
    slots AFTER the current position, so early spending starved late days.
  - 'Nachos + Coke Combo @ Rs.49' served as DINNER nine times: the word
    "combo" is a COMPLETE form override, and nothing demoted the drink.
  - Curries and cheap staples hit 9-14 uses: when the affordable slice under
    a heavy appetite was EMPTY, ceil(days/len(eff)) exploded to days+1 -- a
    monthly cap that could never bind.
  - Day 1 == Day 2 exactly: pass 1 stacked every forced paneer pick onto the
    earliest grid positions with no spreading and no recency discipline.

Synthetic catalog only -- no network, no DB. Run:
    python test_veg_budget.py
"""
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from math import ceil

from appetite import build_profile
from catalog import Dish
import course
from optimizer import optimize, Constraint


DAYS = 30
MEALS = ("breakfast", "lunch", "dinner")
TIGHT_BUDGET = 11000.0   # cheapest cap-respecting fill ~Rs 9.2k; greedy overshoots
PACED_BUDGET = 18000.0   # comfortable enough that caps alone bind rotation
PANEER_NEED = 10


def _d(dish_id, name, rid, rname, meal, price, rating, tags=("veg",)):
    dish = Dish(dish_id=dish_id, name=name, restaurant_id=rid,
                restaurant_name=rname, meal_type=meal, price=float(price),
                rating=rating, cuisine="north_indian", tags=tags, veg=True,
                variants={"regular": float(price)})
    # classify from the NAME, same path the live Swiggy fetch uses — both axes
    return replace(dish, course=course.course_of(name),
                   dish_kind=course.dish_kind_of(name))


def build_catalog():
    """Veg-heavy neighbourhood shaped like the live one: a handful of genuinely
    cheap mains, expensive Rs800+ paneer gravies, and promo junk (drinks,
    nachos combos, fried snacks) whose high ratings make them tempting."""
    cat = []
    # --- breakfast: 8 real mains ---
    bf = [
        ("bf1", "Poha Plate", 45, 4.1),
        ("bf2", "Masala Dosa", 80, 4.4),
        ("bf3", "Idli Vada Combo", 70, 4.2),
        ("bf4", "Upma Bowl", 50, 3.9),
        ("bf5", "Aloo Paratha", 90, 4.3),
        ("bf6", "Besan Chilla", 55, 3.8),
        ("bf7", "Vegetable Sandwich", 85, 4.0),
        ("bf8", "Paneer Paratha", 120, 4.5),      # the cheap paneer workhorse
    ]
    for i, (did, name, price, rating) in enumerate(bf):
        tags = ("paneer", "veg") if "Paneer" in name else ("veg",)
        cat.append(_d(did, name, f"r{i % 3}", f"RestB{i % 3}", "breakfast",
                      price, rating, tags))
    # --- lunch/dinner shared universe ---
    # A wide cheap-rice/staples tier (the honest way to feed a month), two mid
    # paneer completes, and EXPENSIVE Rs760+ paneer gravies (the live Rs881
    # problem). The tight-budget test below is only meaningful because a
    # genuinely feasible assignment exists: the cheapest CAP-RESPECTING fill
    # of this catalog lands near Rs 9.2k, comfortably under TIGHT_BUDGET --
    # anything over budget is the planner overspending, not physics.
    mains = [
        # cheap completes
        ("m1", "Curd Rice", 55, 3.7),
        ("m2", "Dal Khichdi", 65, 3.8),
        ("m3", "Lemon Rice", 70, 4.0),
        ("m4", "Sambar Rice", 80, 3.9),
        ("m5", "Moong Dal Khichdi", 85, 4.0),
        ("m6", "Masala Khichdi", 90, 4.1),
        ("m7", "Gujarati Khichdi", 95, 3.8),
        ("m8", "Bisi Bele Bath", 105, 4.2),
        ("m9", "Veg Fried Rice", 110, 4.0),
        ("m10", "Hakka Noodles", 115, 3.9),
        ("m11", "Rajma Chawal", 120, 4.0),
        ("m12", "Chole Bhature", 130, 4.1),
        ("m13", "Veg Dum Biryani", 140, 4.2),
        ("m14", "Special Veg Thali", 160, 4.3),
        # mid-price paneer completes
        ("p5", "Paneer Pulao", 150, 4.2),
        ("p6", "Paneer Tikka Bowl", 420, 4.4),
        # EXPENSIVE paneer gravies (the live Rs881 problem), need bread
        ("p1", "Paneer Butter Masala", 780, 4.8),
        ("p2", "Kadai Paneer", 760, 4.7),
        ("p3", "Shahi Paneer", 820, 4.9),
        ("p4", "Paneer Lababdar Curry", 881, 5.0),
    ]
    for i, (did, name, price, rating) in enumerate(mains):
        tags = ("paneer", "veg") if name.startswith("Paneer") else ("veg",)
        cat.append(_d(did, name, f"r{(i % 3) + 5}", f"RestD{i % 3}",
                      "dinner", price, rating, tags))
        cat.append(replace(cat[-1], dish_id=did + "L", meal_type="lunch"))
    # bread stock for the curries (same restaurant as p1..p4)
    cat.append(_d("br1", "Tawa Roti", "r5", "RestD0", "dinner", 15, 4.1))
    # --- promo junk that must NEVER be planned as a meal ---
    cat.append(_d("j1", "Nachos + Coke Combo @ Rs.49", "r9", "Promo Shack",
                  "dinner", 64, 4.9, ("combo", "veg")))
    cat.append(_d("j2", "Chena Toast", "r9", "Promo Shack", "dinner", 49, 4.8))
    cat.append(_d("j3", "Pepsi 500ml", "r9", "Promo Shack", "lunch", 45, 4.5,
                  ("drink", "veg")))
    cat.append(_d("j4", "French Fries", "r9", "Promo Shack", "dinner", 90, 4.6))
    cat.append(_d("j5", "Veg Nuggets", "r9", "Promo Shack", "lunch", 80, 4.5))
    cat.append(_d("j6", "Cheese Balls", "r9", "Promo Shack", "breakfast", 70, 4.4))
    cat.append(_d("j7", "Fresh Lemonade", "r9", "Promo Shack", "breakfast", 40, 4.3))
    return cat


CAT = build_catalog()
# Junk that must NEVER headline a slot: drink/snack/promo names.
JUNK_IDS = {"j1", "j3", "j4", "j5", "j6", "j7"}
# 'Chena Toast' is unrecognised, so it defaults to COMPLETE and MAY be
# planned -- but the monthly ceiling must bound it (the live plan served it 9x).
BOUNDED_IDS = {"j2"}


def _meal_pool(meal):
    """The dishes the optimizer would actually pool for `meal`: standalone-
    capable (sides/drinks/breads excluded), rated at or above MIN_RATING.
    Mirrors the mains gates in optimizer.optimize() — both course and dish_kind."""
    return [d for d in CAT
            if d.meal_type == meal
            and d.dish_kind == course.KIND_MEAL
            and d.rating >= 3.0
            and d.course not in course.NEVER_STANDALONE
            and (d.course != course.COMPLETE
                 or course.standalone_meal(d.name, d.price))]


# Per-meal-pool monthly ceilings, exactly the optimizer's formula:
# max(3, ceil(days / pool_size) + 1). The optimizer pools PER MEAL -- a lunch
# dish cannot fill a dinner slot -- so its binding cap for a 20-dish lunch pool
# is ceil(30/20)+1 = 3, not the pooled-lunch+dinner number an earlier draft of
# this test used.
MEAL_BOUNDS = {m: max(3, ceil(DAYS / len(_meal_pool(m))) + 1)
               for m in ("breakfast", "lunch", "dinner")}
CHENA_CAP = MEAL_BOUNDS["dinner"]
PROF = build_profile(6, "heavy")


def _run(**kw):
    kw.setdefault("constraints", [Constraint("paneer", PANEER_NEED)])
    kw.setdefault("veg_only", True)
    return optimize(CAT, PROF, kw.pop("budget"), days=DAYS, **kw)


# ---- classification (root cause D) ----------------------------------------
def test_drink_and_snack_promo_names_classify_as_side():
    """'Nachos + Coke Combo @ Rs.49' contains the COMPLETE form word 'combo',
    which made a nachos-and-soda promo a full dinner. A name carrying a DRINK
    word must classify as a side unless it also names real food."""
    info = course.classify("Nachos + Coke Combo @ Rs.49")
    assert info.course == course.SIDE, \
        f"nachos+coke promo -> {info.course}/{info.confidence}"
    assert not course.standalone_meal("Nachos + Coke Combo @ Rs.49", 64)
    for n in ("Pepsi", "Cola", "Fresh Lemonade", "Iced Tea", "Sprite",
              "Thums Up 750ml"):
        assert course.course_of(n) == course.SIDE, f"{n} -> {course.course_of(n)}"
    # fried snack sides too (live: 'Veg Nuggets' defaulted to COMPLETE)
    for n in ("Nachos", "Cheese Nachos", "Hash Brown", "Potato Chips",
              "Veg Nuggets", "French Fries"):
        assert course.course_of(n) == course.SIDE, f"{n} -> {course.course_of(n)}"


def test_real_food_with_a_drink_stays_a_complete_meal():
    """The drink rule must not swallow genuine combo meals: a burger/biryani/
    chicken bucket plus a Coke IS dinner."""
    for n in ("Burger + Coke Combo", "Chicken Biryani Combo with Pepsi",
              "Chicken Bucket + Pepsi 750ml", "Paneer Wrap + Cola"):
        assert course.course_of(n) == course.COMPLETE, \
            f"{n} -> {course.course_of(n)}"


def test_optimizer_never_plans_snacks_or_drinks_as_mains():
    r = _run(budget=TIGHT_BUDGET)
    planned = [s.dish_name for s in r.slots if s.dish_id in JUNK_IDS]
    assert not planned, f"promo junk planned as meals: {Counter(planned)}"
    # unrecognised names may fill a slot, but only within the monthly ceiling
    chena = Counter(s.dish_id for s in r.slots if s.dish_id in BOUNDED_IDS)
    worst = max(chena.values(), default=0)
    assert worst <= CHENA_CAP, (
        f"'Chena Toast' (unrecognised, default-complete) used {worst}x "
        f"(ceiling {CHENA_CAP})")


# ---- budget guarantee (root cause B) ---------------------------------------
def test_tight_veg_budget_is_met_when_feasible():
    """A feasible assignment exists (the cheapest cap-respecting fill of this
    catalog is ~Rs 9.2k, paneer premium included < Rs 11k), so the plan MUST
    come back inside the budget instead of 35% over it."""
    r = _run(budget=TIGHT_BUDGET)
    assert r.feasible, (
        f"feasible=False though an assignment fits: total={r.total_cost}; "
        f"{r.message}")
    assert r.total_cost <= TIGHT_BUDGET, (
        f"total {r.total_cost} exceeded budget {TIGHT_BUDGET}")


# ---- consecutive-day variety (root cause A) --------------------------------
def test_no_consecutive_day_overlap_of_two_or_more():
    r = _run(budget=TIGHT_BUDGET)
    by_day = defaultdict(set)
    for s in r.slots:
        by_day[s.day].add(s.dish_id)
    worst_day, overlap = max(
        ((d, by_day[d] & by_day[d + 1]) for d in range(1, DAYS)),
        key=lambda t: len(t[1]))
    assert len(overlap) <= 1, (
        f"days {worst_day} and {worst_day + 1} share {len(overlap)} dishes "
        f"(max 1): {sorted(overlap)}")
    assert by_day[1] != by_day[2], "day 1 menu is identical to day 2"


def test_forced_paneer_spreads_across_the_month():
    """Pass 1 used to stack every forced paneer pick onto the earliest grid
    positions (Day1 == Day2, all paneer). Ten required paneer meals must be
    distributed over the month, not dumped into the first few days."""
    r = _run(budget=TIGHT_BUDGET)
    got = r.constraint_status["paneer"]["got"]
    assert got >= PANEER_NEED, f"only {got}/{PANEER_NEED} paneer meals fit"
    # count via the dish ids we know carry the paneer tag
    paneer_ids = {d.dish_id for d in CAT if "paneer" in d.tags}
    paneer_days = {s.day for s in r.slots if s.dish_id in paneer_ids}
    assert len(paneer_days) >= 7, (
        f"{got} paneer meals squeezed into only {len(paneer_days)} distinct "
        f"days: {sorted(paneer_days)}")


# ---- monthly repeat ceiling (root cause C) ---------------------------------
def test_monthly_cap_binds_under_pacing():
    """No dish may exceed ceil(days / pool_size(its meal)) + 1 uses. Under the
    old math the affordable slice was empty at heavy appetite and the cap
    exploded to days+1 -- Curd Rice x14, junk x9."""
    r = _run(budget=PACED_BUDGET)
    pool_sizes = {m: len(_meal_pool(m))
                  for m in ("breakfast", "lunch", "dinner")}
    uses = Counter(s.dish_id for s in r.slots)
    for did, count in uses.items():
        dish = next(x for x in CAT if x.dish_id == did)
        bound = MEAL_BOUNDS[dish.meal_type]
        assert count <= bound, (
            f"{dish.name} used {count}x (cap {bound} for a "
            f"{pool_sizes[dish.meal_type]}-dish {dish.meal_type} pool)")


# ---- feasibility floor honesty (root cause E) ------------------------------
def test_feasibility_floor_includes_forced_constraint_cost():
    """The floor probe ran the optimizer at budget=1, where pass 1 grabbed the
    CHEAPEST paneer; the real run at the user's budget grabs the best-rated
    AFFORDABLE ones. Result: 'minimum Rs 10,501' while the real plan cost
    Rs 13,560. The floor must reflect what the constraint actually forces and
    be achievable at the quoted number."""
    import feasibility

    cons = [Constraint("paneer", PANEER_NEED)]
    res_c = feasibility.analyse(
        catalog=CAT, profile_builder=build_profile, user_id=6,
        appetite_level="heavy", budget=6000.0, days=DAYS,
        constraints=[{"dish_tag": "paneer", "min_count": PANEER_NEED}],
        veg_only=True)
    res_p = feasibility.analyse(
        catalog=CAT, profile_builder=build_profile, user_id=6,
        appetite_level="heavy", budget=6000.0, days=DAYS,
        constraints=[], veg_only=True)

    assert res_c["feasible"] is False
    assert res_c["shortfall"] == round(res_c["floor"] - 6000.0, 2)
    # Whether the constraint RAISES the net floor depends on the catalog:
    # forced paneer rotation can satisfy whole-day variety more cheaply than
    # free choice can, so a strict premium over the unconstrained probe is no
    # longer universal. What must hold for BOTH runs is that the quoted floor
    # is real money a guards-on plan can honour — verified below for the
    # constrained run, and sanity-checked here for the unconstrained one.
    assert res_p["floor"] >= 1000, (
        f"unconstrained floor collapsed to {res_p['floor']}")
    # and the quoted floor must actually deliver: running the planner AT the
    # floor meets the constraint without exceeding it
    prof = build_profile(6, "heavy")
    r = optimize(CAT, prof, res_c["floor"], days=DAYS, constraints=cons,
                 veg_only=True)
    assert r.constraint_status["paneer"]["got"] >= PANEER_NEED, (
        f"floor {res_c['floor']} cannot actually meet the constraint")
    assert r.total_cost <= res_c["floor"] + 0.01, (
        f"real plan at the quoted floor costs {r.total_cost} "
        f"> {res_c['floor']}")


if __name__ == "__main__":
    def _run_test(name, fn):
        try:
            fn()
            print(f"PASS {name}")
            return True
        except AssertionError as e:
            print(f"FAIL {name}: {e}")
            return False
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {name}: UNEXPECTED {type(e).__name__}: {e}")
            return False

    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = sum(_run_test(name, fn) for name, fn in tests)
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
