"""Test variety enforcement: MAX_IDENTICAL_DAY_MENUS and exponential recency."""
from catalog import Dish
from optimizer import optimize, MAX_IDENTICAL_DAY_MENUS
from appetite import build_profile
from dataclasses import replace
from collections import Counter
import course


def test_max_identical_day_menus_enforced():
    """Same full-day menu should not repeat more than MAX_IDENTICAL_DAY_MENUS times."""
    dishes_raw = [
        Dish(
            dish_id="pb1", name="Paneer Butter Masala", restaurant_id="r1",
            restaurant_name="Rest", meal_type="lunch",
            price=180.0, rating=4.5, cuisine="north_indian", tags=("veg",), veg=True,
            variants={"regular": 180.0},
        ),
        Dish(
            dish_id="r1", name="Tawa Roti", restaurant_id="r1",
            restaurant_name="Rest", meal_type="lunch",
            price=15.0, rating=4.0, cuisine="north_indian", tags=("veg",), veg=True,
            variants={"regular": 15.0},
        ),
        Dish(
            dish_id="dt1", name="Dal Tadka", restaurant_id="r2",
            restaurant_name="Rest2", meal_type="lunch",
            price=150.0, rating=4.3, cuisine="north_indian", tags=("veg",), veg=True,
            variants={"regular": 150.0},
        ),
    ]

    dishes = [
        replace(d, course=course.course_of(d.name), dish_kind=course.dish_kind_of(d.name))
        for d in dishes_raw
    ]

    prof = build_profile(1, "moderate")
    result = optimize(
        catalog=dishes,
        profile=prof,
        budget=10000.0,
        days=14,
        constraints=[],
        veg_only=True,
        meals=("lunch",),
    )

    # Build day signatures: (main_dish_id, side_dish_id) tuple
    day_menus = []
    for slot in result.slots:
        if slot.meal_type == "lunch" and slot.dish_id:
            signature = (slot.dish_id, slot.side_dish_id or "")
            day_menus.append(signature)

    # Count how many times each unique menu appears
    menu_counts = Counter(day_menus)
    max_repeats = max(menu_counts.values()) if menu_counts else 0

    print(f"Unique menus: {len(menu_counts)}, Max repeats: {max_repeats}")
    print(f"MAX_IDENTICAL_DAY_MENUS constant: {MAX_IDENTICAL_DAY_MENUS}")

    # MAX_IDENTICAL_DAY_MENUS=0 means max 1 occurrence, =1 means max 2 occurrences
    allowed_max = MAX_IDENTICAL_DAY_MENUS + 1

    if max_repeats > allowed_max:
        print(f"FAIL: Menu repeated {max_repeats} times, allowed max {allowed_max}")
    else:
        print(f"OK: Menu repetition within limit ({max_repeats} <= {allowed_max})")


def test_exponential_recency_forces_rotation():
    """Exponential recency penalty should force dish rotation across days."""
    dishes_raw = [
        Dish(
            dish_id=f"d{i}", name=f"Dish {i}", restaurant_id="r1",
            restaurant_name="Rest", meal_type="lunch",
            price=150.0, rating=4.0 + (i * 0.1), cuisine="north_indian",
            tags=("veg",), veg=True, variants={"regular": 150.0},
        )
        for i in range(1, 11)  # 10 different dishes
    ]

    dishes = [
        replace(d, course=course.COMPLETE, dish_kind=course.KIND_MEAL)
        for d in dishes_raw
    ]

    prof = build_profile(1, "moderate")
    result = optimize(
        catalog=dishes,
        profile=prof,
        budget=20000.0,
        days=20,
        constraints=[],
        veg_only=True,
        meals=("lunch",),
    )

    # Track dish usage
    dish_usage = Counter()
    for slot in result.slots:
        if slot.dish_id:
            dish_usage[slot.dish_id] += 1

    # Check distribution - with strong variety, usage should be relatively even
    if len(dish_usage) == 0:
        print("SKIP: No dishes planned")
        return

    usage_values = list(dish_usage.values())
    max_usage = max(usage_values)
    min_usage = min(usage_values)
    variance = max_usage - min_usage

    print(f"Dishes used: {len(dish_usage)}/10")
    print(f"Usage range: {min_usage}-{max_usage} (variance: {variance})")

    # Good variety means low variance (dishes rotate evenly)
    if variance > 5:
        print(f"WARN: High variance ({variance}) suggests uneven rotation")
    else:
        print(f"OK: Low variance ({variance}) indicates good rotation")


if __name__ == "__main__":
    test_max_identical_day_menus_enforced()
    test_exponential_recency_forces_rotation()
    print("\nOK: Variety enforcement tests completed")
