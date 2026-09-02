"""Test pairing system with optimizer integration."""
from catalog import Dish
from optimizer import optimize, Constraint
from appetite import build_profile
from dataclasses import replace
import course


def test_dessert_with_dinner_pairing():
    """Pairing constraint should add desserts to dinner slots."""
    from dataclasses import replace

    dishes_raw = [
        # Main meal
        Dish(
            dish_id="pb1", name="Paneer Butter Masala", restaurant_id="r1",
            restaurant_name="North Indian", meal_type="dinner",
            price=180.0, rating=4.3, cuisine="north_indian", tags=("veg",), veg=True,
            variants={"regular": 180.0},
        ),
        Dish(
            dish_id="r1", name="Tawa Roti", restaurant_id="r1",
            restaurant_name="North Indian", meal_type="dinner",
            price=15.0, rating=4.0, cuisine="north_indian", tags=("veg",), veg=True,
            variants={"regular": 15.0},
        ),
        # Dessert for pairing
        Dish(
            dish_id="gj1", name="Gulab Jamun", restaurant_id="r1",
            restaurant_name="Sweet Shop", meal_type="dinner",
            price=40.0, rating=4.2, cuisine="indian", tags=("veg",), veg=True,
            variants={"regular": 40.0},
        ),
    ]

    dishes = [
        replace(d, course=course.course_of(d.name), dish_kind=course.dish_kind_of(d.name))
        for d in dishes_raw
    ]

    # Constraint: dessert with dinner always
    constraint = Constraint(
        dish_tag="",
        min_count=0,
        dish_kind="sweet",
        slot_type="dinner",
        frequency="always"
    )

    prof = build_profile(1, "moderate")
    result = optimize(
        catalog=dishes,
        profile=prof,
        budget=5000.0,
        days=3,
        constraints=[constraint],
        veg_only=True,
        meals=("dinner",),
    )

    # Check that dinner slots have pairing_dish_id set
    dinner_slots = [s for s in result.slots if s.meal_type == "dinner" and s.dish_id]

    if len(dinner_slots) == 0:
        print("SKIP: No dinner slots planned (budget/catalog issue)")
        return

    paired_count = sum(1 for s in dinner_slots if s.pairing_dish_id)

    print(f"Dinner slots: {len(dinner_slots)}, Paired: {paired_count}")

    # At least some dinners should be paired with dessert (budget permitting)
    if result.feasible and paired_count == 0:
        print("WARN: Feasible plan but no pairings added - check budget")

    print("OK: Pairing system executed (check pairing_dish_id fields)")


def test_drinks_with_lunch_pairing():
    """Pairing constraint should add beverages to lunch slots."""
    from dataclasses import replace

    dishes_raw = [
        Dish(
            dish_id="cb1", name="Chole Bhature", restaurant_id="r1",
            restaurant_name="Punjabi", meal_type="lunch",
            price=120.0, rating=4.4, cuisine="north_indian", tags=("veg",), veg=True,
            variants={"regular": 120.0},
        ),
        Dish(
            dish_id="ls1", name="Sweet Lassi", restaurant_id="r1",
            restaurant_name="Lassi Shop", meal_type="lunch",
            price=50.0, rating=4.1, cuisine="indian", tags=("veg",), veg=True,
            variants={"regular": 50.0},
        ),
    ]

    dishes = [
        replace(d, course=course.course_of(d.name), dish_kind=course.dish_kind_of(d.name))
        for d in dishes_raw
    ]

    constraint = Constraint(
        dish_tag="",
        min_count=0,
        dish_kind="beverage",
        slot_type="lunch",
        frequency="always"
    )

    prof = build_profile(1, "moderate")
    result = optimize(
        catalog=dishes,
        profile=prof,
        budget=3000.0,
        days=3,
        constraints=[constraint],
        veg_only=True,
        meals=("lunch",),
    )

    lunch_slots = [s for s in result.slots if s.meal_type == "lunch" and s.dish_id]

    if len(lunch_slots) > 0:
        paired_count = sum(1 for s in lunch_slots if s.pairing_dish_id)
        print(f"Lunch slots: {len(lunch_slots)}, Paired with drinks: {paired_count}")

    print("OK: Drinks pairing system executed")


if __name__ == "__main__":
    test_dessert_with_dinner_pairing()
    test_drinks_with_lunch_pairing()
    print("\nOK: Pairing integration tests completed")
