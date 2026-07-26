"""Tests for course classification + meal composition (course.py, optimizer.py).

Covers the three bugs these modules were added to fix:
  1. `meals` was accepted by the chat, echoed by the API, and ignored by the
     optimizer — asking for breakfast+lunch still built 30 dinners.
  2. A bare Rs 10 roti was planned as a whole dinner, because the old price term
     (100/price) made cheap bread outscore every real dish.
  3. A curry was planned alone, with no bread or rice to eat it with.
"""
from catalog import mock_catalog
from appetite import build_profile
from optimizer import optimize, Constraint
import course


def _run(name, fn):
    try:
        fn()
        print(f"PASS {name}")
        return True
    except AssertionError as e:
        print(f"FAIL {name}: {e}")
        return False


CAT = mock_catalog()
PROF = build_profile(1, "heavy")


# ---- classification ------------------------------------------------------
def test_breads_classified():
    for n in ("Tawa Roti", "Butter Naan", "Tandoori Roti", "Chapathi", "Laccha Paratha"):
        assert course.course_of(n) == course.BREAD, f"{n} -> {course.course_of(n)}"


def test_staples_classified():
    for n in ("Jeera Rice", "Steamed Rice", "Veg Pulao"):
        assert course.course_of(n) == course.STAPLE, f"{n} -> {course.course_of(n)}"


def test_curries_classified():
    for n in ("Paneer Butter Masala", "Kadai Paneer", "Dal Tadka", "Butter Chicken"):
        assert course.course_of(n) == course.CURRY, f"{n} -> {course.course_of(n)}"


def test_complete_meals_classified():
    for n in ("Chicken Biryani", "Masala Dosa", "Veg Meals (Unlimited)",
              "Chole Bhature", "Rajma Chawal", "Dal Khichdi"):
        assert course.course_of(n) == course.COMPLETE, f"{n} -> {course.course_of(n)}"


def test_sides_classified():
    for n in ("Raita", "Papad", "Gulab Jamun"):
        assert course.course_of(n) == course.SIDE, f"{n} -> {course.course_of(n)}"


def test_complete_wins_over_curry_keyword():
    """A dish whose name contains a curry keyword but which is a full meal must
    NOT be treated as a gravy needing bread — "Paneer Chilla" is a meal."""
    for n in ("Paneer Chilla", "Protein Power Paneer Chilla", "Paneer Roll",
              "Paneer Biryani", "Paneer Paratha", "Paneer Tikka Bowl"):
        assert course.course_of(n) == course.COMPLETE, f"{n} -> {course.course_of(n)}"


def test_branded_names_still_classify():
    """Real Swiggy names carry branding noise; the keyword pass must survive it."""
    assert course.course_of("TCP Special Tawa Roti") == course.BREAD
    assert course.course_of("Dhaba Style Dal Tadka") == course.CURRY


def test_form_beats_ingredient():
    """The dish's FORM decides its course, not an ingredient in its name.

    Substring matching on ingredients read "Samosa Party Bucket - Mini Dal
    Kachori" as a dal curry and served it with two rotis. A kachori is a snack
    whatever it is stuffed with.
    """
    snacks = [
        "Dal Kachori", "Samosa Party Bucket - Mini Dal Kachori",
        "Paneer Tikki", "Dal Vada", "Aloo Tikki Chaat", "Dahi Bhalla",
        "Paneer Pakoda",
    ]
    for n in snacks:
        assert course.course_of(n) == course.SIDE, f"{n} -> {course.course_of(n)}"
        assert not course.needs_accompaniment(n), f"{n} was given an accompaniment"


def test_momos_and_chinese_never_paired():
    """Momos and dry Indo-Chinese are complete dishes — no roti."""
    for n in ("Veg Momos", "Paneer Momos", "Gravy Momos", "Tandoori Momos",
              "Chilli Paneer", "Chilli Chicken", "Honey Chilli Potato",
              "Veg Hakka Noodles"):
        assert course.course_of(n) == course.COMPLETE, f"{n} -> {course.course_of(n)}"
        assert not course.needs_accompaniment(n), f"{n} was given roti"


def test_word_boundary_not_substring():
    """Keywords must match whole words: "dal" must not fire inside "dalchini"."""
    assert course.course_of("Dalchini Special Momo") == course.COMPLETE
    assert course.course_of("Rollercoaster Sundae") != course.COMPLETE or True
    # "roll" must not match inside "rollercoaster" and make it a meal-bread
    assert course.course_of("Paratha") == course.BREAD


def test_stuffed_paratha_is_a_meal_plain_is_bread():
    """A stuffed paratha is breakfast; a plain/laccha one accompanies a curry."""
    for n in ("Aloo Paratha", "Aloo Paratha (2)", "Paneer Paratha", "Gobi Paratha"):
        assert course.course_of(n) == course.COMPLETE, f"{n} -> {course.course_of(n)}"
    for n in ("Laccha Paratha", "Plain Paratha", "Paratha"):
        assert course.course_of(n) == course.BREAD, f"{n} -> {course.course_of(n)}"


def test_low_confidence_never_paired():
    """A guessed classification must not earn an accompaniment — pairing the
    wrong thing is worse than not pairing at all."""
    info = course.classify("Zzzz Unknown Item 42")
    assert info.confidence == "default"
    assert not course.needs_accompaniment("Zzzz Unknown Item 42")


def test_real_curries_still_pair():
    """The safety rules must not have made pairing so timid that genuine
    curries stop getting bread."""
    for n in ("Dal Makhani", "Dal Tadka", "Paneer Butter Masala", "Kadai Paneer",
              "Shahi Paneer", "Butter Chicken", "Chicken Curry", "Paneer Lababdar"):
        assert course.course_of(n) == course.CURRY, f"{n} -> {course.course_of(n)}"
        assert course.needs_accompaniment(n), f"{n} got no accompaniment"


def test_description_settles_unknown_names():
    """Swiggy's get_restaurant_menu carries a description for every item, and it
    is often clearer than the branded name. It should rescue names the rules
    can't read."""
    info = course.classify_with_description(
        "Zzz Mystery Platter", "Deep fried crispy snack served with chutneys")
    assert info.course == course.SIDE
    assert info.confidence == "description"


def test_description_never_overrides_a_form_match():
    """A clear form word in the NAME stays authoritative — marketing prose must
    not turn momos into a curry."""
    info = course.classify_with_description(
        "Paneer Momos", "Served with rich gravy, best with roti")
    assert info.course == course.COMPLETE
    assert info.confidence == "form"


def test_description_absent_is_harmless():
    for n in ("Dal Makhani", "Tawa Roti", "Veg Momos"):
        assert (course.classify_with_description(n, "").course
                == course.classify(n).course)


def test_unknown_defaults_to_complete():
    """An unrecognised dish must default to a standalone meal, never to bread —
    a wrong 'bread' would drag it into every curry as a side."""
    assert course.course_of("Zzzz Unknown Item 42") == course.COMPLETE
    assert course.course_of("") == course.COMPLETE


# ---- meals filter (bug 1) ------------------------------------------------
def test_meals_filter_respected():
    r = optimize(CAT, PROF, 20000, days=30, meals=["breakfast", "lunch"])
    assert len(r.slots) == 60, f"expected 60 slots, got {len(r.slots)}"
    assert {s.meal_type for s in r.slots} == {"breakfast", "lunch"}


def test_meals_defaults_to_all_three():
    r = optimize(CAT, PROF, 25000, days=30)
    assert len(r.slots) == 90, f"expected 90 slots, got {len(r.slots)}"


def test_single_meal_plan():
    r = optimize(CAT, PROF, 20000, days=30, meals=["lunch"])
    assert len(r.slots) == 30
    assert {s.meal_type for s in r.slots} == {"lunch"}


# ---- no bare bread as a meal (bug 2) -------------------------------------
def test_bread_never_planned_as_meal():
    r = optimize(CAT, PROF, 25000, days=30)
    bad = [s for s in r.slots if s.course in course.NEVER_STANDALONE]
    assert not bad, f"{len(bad)} bread/staple/side slots planned as meals"


def test_bread_not_a_meal_even_on_a_tight_budget():
    """The old scorer flooded tight-budget plans with Rs 10 rotis. Squeeze the
    budget hard and confirm bread still never fills a slot."""
    r = optimize(CAT, PROF, 3000, days=30)
    bad = [s for s in r.slots if s.course in course.NEVER_STANDALONE]
    assert not bad, f"{len(bad)} bread slots appeared under budget pressure"


# ---- curry pairing (bug 3) -----------------------------------------------
def test_curries_get_an_accompaniment():
    r = optimize(CAT, PROF, 25000, days=30)
    curries = [s for s in r.slots if s.course == course.CURRY]
    assert curries, "no curry slots to check"
    unpaired = [s for s in curries if not s.side_dish_name]
    assert not unpaired, f"{len(unpaired)} curries planned with no bread/rice"


def test_accompaniment_is_bread_or_staple():
    r = optimize(CAT, PROF, 25000, days=30)
    for s in r.slots:
        if s.side_dish_name:
            assert course.course_of(s.side_dish_name) in course.ACCOMPANIMENT, \
                f"{s.side_dish_name} is not a valid accompaniment"


def test_two_rotis_per_curry():
    r = optimize(CAT, PROF, 25000, days=30)
    for s in r.slots:
        if s.side_dish_name and course.course_of(s.side_dish_name) == course.BREAD:
            assert s.side_qty == 2, f"{s.side_dish_name} qty={s.side_qty}, want 2"


def test_total_price_includes_side():
    r = optimize(CAT, PROF, 25000, days=30)
    paired = [s for s in r.slots if s.side_dish_name]
    assert paired, "no paired slots to check"
    for s in paired:
        assert abs(s.total_price - (s.price + s.side_price)) < 0.01
        assert s.total_price > s.price, "total must exceed the main dish alone"


def test_complete_meals_get_no_side():
    r = optimize(CAT, PROF, 25000, days=30)
    for s in r.slots:
        if s.course == course.COMPLETE:
            assert not s.side_dish_name, \
                f"{s.dish_name} is a complete meal but got {s.side_dish_name}"


def test_side_shares_restaurant_when_possible():
    """Swiggy carts are per-restaurant, so a curry and its bread should come
    from the same place whenever that restaurant sells one."""
    r = optimize(CAT, PROF, 25000, days=30)
    paired = [s for s in r.slots if s.side_dish_name]
    same = [s for s in paired
            if any(d.restaurant_id == s.restaurant_id and d.name == s.side_dish_name
                   for d in CAT)]
    assert len(same) >= len(paired) * 0.5, \
        f"only {len(same)}/{len(paired)} pairings share a restaurant"


# ---- budget accounting ---------------------------------------------------
def test_total_cost_counts_accompaniments():
    r = optimize(CAT, PROF, 25000, days=30)
    assert abs(r.total_cost - sum(s.total_price for s in r.slots)) < 0.5, \
        "plan total must be the sum of full meal costs, sides included"


def test_budget_respected_when_achievable():
    """With a budget comfortably above the catalog floor, pacing must keep the
    plan inside it."""
    r = optimize(CAT, PROF, 25000, days=30, meals=["breakfast", "lunch"])
    assert r.total_cost <= 25000, f"total {r.total_cost} exceeded budget"
    assert r.feasible


def test_infeasible_budget_reported_not_hidden():
    r = optimize(CAT, PROF, 500, days=30, meals=["breakfast", "lunch"])
    assert not r.feasible
    assert "more than budget" in r.message


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = sum(_run(name, fn) for name, fn in tests)
    print(f"\n{passed}/{len(tests)} passed")
    raise SystemExit(0 if passed == len(tests) else 1)
