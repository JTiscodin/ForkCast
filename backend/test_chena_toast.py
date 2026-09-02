"""Test that sweets never land in meal slots after classification filter fix."""
from catalog import Dish, mock_catalog
from optimizer import optimize
from appetite import build_profile
import course


def test_chena_toast_classification():
    """Chena Toast is a Bengali sweet (mithai) - should be kind=sweet."""
    result = course.classify("Chena Toast")
    assert result.dish_kind == course.KIND_SWEET, \
        f"Chena Toast classified as {result.dish_kind}, expected {course.KIND_SWEET}"


def test_sweets_rejected_from_meal_slots():
    """Sweets with course=complete should NEVER pass the meal filter."""
    # Create a catalog with a sweet that has course=complete
    # Use course.course_of() and course.dish_kind_of() which handle the classification
    from dataclasses import replace

    dishes_raw = [
        Dish(
            dish_id="ct1", name="Chena Toast", restaurant_id="r1",
            restaurant_name="Bengali Sweet House", meal_type="lunch",
            price=60.0, rating=4.2, cuisine="bengali", tags=("veg",), veg=True,
            variants={"regular": 60.0},
        ),
        # Add actual meal options so the optimizer has valid choices
        Dish(
            dish_id="pb1", name="Paneer Butter Masala", restaurant_id="r2",
            restaurant_name="North Indian", meal_type="lunch",
            price=180.0, rating=4.3, cuisine="north_indian", tags=("veg",), veg=True,
            variants={"regular": 180.0},
        ),
        Dish(
            dish_id="r1", name="Tawa Roti", restaurant_id="r2",
            restaurant_name="North Indian", meal_type="lunch",
            price=15.0, rating=4.0, cuisine="north_indian", tags=("veg",), veg=True,
            variants={"regular": 15.0},
        ),
        Dish(
            dish_id="md1", name="Masala Dosa", restaurant_id="r3",
            restaurant_name="South Indian", meal_type="breakfast",
            price=80.0, rating=4.5, cuisine="south_indian", tags=("veg",), veg=True,
            variants={"regular": 80.0},
        ),
    ]

    # Classify all dishes using replace to create new instances with classification
    dishes = [
        replace(d, course=course.course_of(d.name), dish_kind=course.dish_kind_of(d.name))
        for d in dishes_raw
    ]

    # Plan for 7 days, veg only, budget should allow many dishes
    prof = build_profile(1, "moderate")
    result = optimize(
        catalog=dishes,
        profile=prof,
        budget=15000.0,
        days=7,
        constraints=[],
        veg_only=True,
        meals=("breakfast", "lunch", "dinner"),
    )

    # Check that Chena Toast never appears in any meal slot
    # PlanResult has .slots list, not .days
    chena_found = False
    for slot in result.slots:
        if slot and slot.dish_id == "ct1":
            chena_found = True
            print(f"FAIL: Chena Toast (sweet) was planned as a meal: {slot}")
            break

    assert not chena_found, "Chena Toast (sweet) should never be planned as a meal"
    print(f"OK: Tested {len(result.slots)} meal slots - no sweets found")


def test_gulab_jamun_rejected_from_meal_slots():
    """Gulab Jamun should also never be a meal."""
    from dataclasses import replace

    dishes_raw = [
        Dish(
            dish_id="gj1", name="Gulab Jamun", restaurant_id="r1",
            restaurant_name="Sweet Shop", meal_type="lunch",
            price=40.0, rating=4.0, cuisine="indian", tags=("veg",), veg=True,
            variants={"regular": 40.0},
        ),
        Dish(
            dish_id="cb1", name="Chole Bhature", restaurant_id="r2",
            restaurant_name="Punjabi", meal_type="lunch",
            price=120.0, rating=4.4, cuisine="north_indian", tags=("veg",), veg=True,
            variants={"regular": 120.0},
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
        days=7,
        constraints=[],
        veg_only=True,
        meals=("lunch",),
    )

    for slot in result.slots:
        if slot and slot.dish_id == "gj1":
            raise AssertionError(f"Gulab Jamun (sweet) was planned as lunch: {slot}")

    print("OK: Gulab Jamun correctly excluded from meal slots")


if __name__ == "__main__":
    test_chena_toast_classification()
    test_sweets_rejected_from_meal_slots()
    test_gulab_jamun_rejected_from_meal_slots()
    print("\nOK: All sweet exclusion tests passed")

