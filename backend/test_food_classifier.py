"""Tests for food_classifier.py — bridges course.py and food_knowledge.py."""
from food_classifier import classify, classify_instamart, enrich_dish, main_meal_eligible
from catalog import Dish
import course as course_rules


def test_classifier_knowledge_wins():
    """food_knowledge entry overrides course.py for known items."""
    # Chhena Toast: course.py would default to COMPLETE/meal,
    # but food_knowledge says sweet/side/not-eligible
    info = classify("ct1", "Chena Toast")
    assert info.source == "food_knowledge"
    assert info.dish_kind == course_rules.KIND_SWEET
    assert info.course == course_rules.SIDE
    assert info.main_meal_eligible is False
    assert info.serving_unit == "piece"


def test_classifier_fallback_to_course():
    """Unknown item falls through to course.py."""
    info = classify("u1", "Some Random Unknown Dish 9000")
    assert info.source == "course_rules"
    # course.py classifies it based on name rules
    assert info.dish_kind in course_rules.KINDS
    assert info.confidence != "knowledge"


def test_classifier_gulab_jamun():
    """Gulab Jamun resolved via knowledge."""
    info = classify("gj1", "Gulab Jamun")
    assert info.source == "food_knowledge"
    assert info.dish_kind == course_rules.KIND_SWEET
    assert info.main_meal_eligible is False


def test_classifier_biryani():
    """Biryani resolved via knowledge as meal-eligible."""
    info = classify("br1", "Biryani")
    assert info.source == "food_knowledge"
    assert info.dish_kind == course_rules.KIND_MEAL
    assert info.main_meal_eligible is True


def test_classifier_paneer_butter_masala():
    """Paneer Butter Masala — known curry entry."""
    info = classify("pb1", "Paneer Butter Masala")
    assert info.source == "food_knowledge"
    assert info.dish_kind == course_rules.KIND_MEAL
    assert info.course == course_rules.CURRY
    assert info.main_meal_eligible is True


def test_main_meal_eligible_convenience():
    """Convenience function returns correct boolean."""
    assert main_meal_eligible("Chena Toast") is False
    assert main_meal_eligible("Biryani") is True
    assert main_meal_eligible("Gulab Jamun") is False
    assert main_meal_eligible("Dal Makhani") is True


def test_classify_instamart_knowledge():
    """Instamart items with knowledge entries get correct metadata."""
    item = {"id": "im123", "name": "Lassi"}
    info = classify_instamart(item, "beverage")
    assert info.source == "food_knowledge"
    assert info.dish_kind == course_rules.KIND_BEVERAGE
    assert info.main_meal_eligible is False


def test_classify_instamart_fallback():
    """Unknown grocery defaults to safe fallback."""
    item = {"id": "im456", "name": "Random Grocery Snack"}
    info = classify_instamart(item, "snack")
    # Should use query_kind as fallback for unknown groceries
    assert info.source == "course_rules"
    assert info.main_meal_eligible is False


def test_enrich_dish():
    """enrich_dish returns FoodInfo with knowledge when available."""
    dish = Dish(
        dish_id="ct1", name="Chena Toast", restaurant_id="r1",
        restaurant_name="Sweet Shop", meal_type="dinner",
        price=60.0, rating=4.0, cuisine="bengali", tags=("veg",), veg=True,
        variants={"regular": 60.0},
    )
    info = enrich_dish(dish)
    assert info.source == "food_knowledge"
    assert info.dish_kind == course_rules.KIND_SWEET
    assert info.main_meal_eligible is False


def test_enrich_dish_unknown():
    """Unknown dish falls through to course rules."""
    dish = Dish(
        dish_id="u1", name="Totally Unknown Dish", restaurant_id="r1",
        restaurant_name="Test", meal_type="lunch",
        price=100.0, rating=4.0, cuisine="north_indian", tags=(), veg=True,
        variants={"regular": 100.0},
    )
    info = enrich_dish(dish)
    assert info.source == "course_rules"
    # main_meal_eligible based on course
    assert isinstance(info.main_meal_eligible, bool)