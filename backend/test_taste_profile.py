"""Tests for taste_profile.py — user preference model."""
from taste_profile import (
    build_profile, hard_filters, soft_hints, adheres_to_diet,
    allergy_blocked, validate_compatibility, TasteProfile,
)
from types import SimpleNamespace


def _item(name="test dish", veg=True, dish_kind="meal", health_tags=(),
          satiety=0.5):
    return SimpleNamespace(
        name=name, veg=veg, dish_kind=dish_kind,
        health_tags=health_tags, satiety=satiety,
    )


def test_build_profile_from_ui():
    """Structured UI input produces correct TasteProfile."""
    raw = {
        "veg_level": "jain",
        "allergies": ["peanut", "dairy"],
        "health_goals": ["diabetic_friendly"],
        "spice_preference": 2,
        "favorite_cuisines": ["north_indian", "south_indian"],
        "disliked_foods": ["okra", "mushroom"],
        "portion_size": "small",
        "notes": "I like light meals",
    }
    p = build_profile(1, raw)
    assert p.veg_level == "jain"
    assert "peanut" in p.allergies
    assert "dairy" in p.allergies
    assert "diabetic_friendly" in p.health_goals
    assert p.spice_preference == 2
    assert "north_indian" in p.favorite_cuisines
    assert "okra" in p.disliked_foods
    assert p.portion_size == "small"


def test_build_profile_defaults():
    """Minimal input fills defaults."""
    p = build_profile(0, {})
    assert p.veg_level == "veg"
    assert p.spice_preference == 3
    assert p.portion_size == "medium"
    assert p.allergies == ()


def test_build_profile_null_optional_preferences_use_defaults():
    """Explicitly unset UI taste values use the same defaults as omitted keys."""
    p = build_profile(0, {
        "veg_level": None,
        "allergies": None,
        "health_goals": None,
        "spice_preference": None,
        "favorite_cuisines": None,
        "disliked_foods": None,
        "portion_size": None,
        "notes": None,
    })
    assert p.veg_level == "veg"
    assert p.allergies == ()
    assert p.health_goals == ()
    assert p.spice_preference == 3
    assert p.favorite_cuisines == ()
    assert p.disliked_foods == ()
    assert p.portion_size == "medium"
    assert p.notes == ""


def test_hard_filters_veg_only():
    """veg_level=veg produces veg_only=True."""
    p = build_profile(0, {"veg_level": "veg"})
    f = hard_filters(p)
    assert f["veg_only"] is True


def test_hard_filters_nonveg():
    """veg_level=nonveg produces veg_only=False."""
    p = build_profile(0, {"veg_level": "nonveg"})
    f = hard_filters(p)
    assert f["veg_only"] is False


def test_hard_filters_jain():
    """Jain level sets jain=True."""
    p = build_profile(0, {"veg_level": "jain"})
    f = hard_filters(p)
    assert f["jain"] is True


def test_health_goal_diabetic_excludes_sweet():
    """diabetic_friendly excludes sweet items."""
    p = build_profile(0, {"health_goals": ["diabetic_friendly"]})
    sweet = _item(name="gulab jamun", dish_kind="sweet")
    assert adheres_to_diet(sweet, p) is False
    meal = _item(name="dal khichdi", dish_kind="meal")
    assert adheres_to_diet(meal, p) is True


def test_health_goal_diabetic_excludes_sugary():
    """diabetic_friendly excludes items tagged sugary/high_sugar."""
    p = build_profile(0, {"health_goals": ["diabetic_friendly"]})
    sugary = _item(name="cola", dish_kind="beverage", health_tags=("sugary",))
    assert adheres_to_diet(sugary, p) is False


def test_health_goal_weight_loss_excludes_sweet_and_beverage():
    """weight_loss excludes sweet and beverage kinds."""
    p = build_profile(0, {"health_goals": ["weight_loss"]})
    sweet = _item(name="gulab jamun", dish_kind="sweet")
    bev = _item(name="lassi", dish_kind="beverage")
    meal = _item(name="dal khichdi", dish_kind="meal")
    assert adheres_to_diet(sweet, p) is False
    assert adheres_to_diet(bev, p) is False
    assert adheres_to_diet(meal, p) is True


def test_health_goal_weight_loss_max_satiety():
    """weight_loss caps satiety at 0.6."""
    p = build_profile(0, {"health_goals": ["weight_loss"]})
    filling = _item(name="heavy meal", dish_kind="meal", satiety=0.8)
    light = _item(name="light meal", dish_kind="meal", satiety=0.5)
    assert adheres_to_diet(filling, p) is False
    assert adheres_to_diet(light, p) is True


def test_adheres_diet_veg_rejects_nonveg():
    """veg-level item check rejects non-veg items."""
    p = build_profile(0, {"veg_level": "veg"})
    nonveg = _item(name="chicken curry", veg=False, dish_kind="meal")
    veg = _item(name="dal makhani", veg=True, dish_kind="meal")
    assert adheres_to_diet(nonveg, p) is False
    assert adheres_to_diet(veg, p) is True


def test_adheres_diet_jain_keyword():
    """Jain profile rejects items with garlic/onion/potato in name."""
    p = build_profile(0, {"veg_level": "jain"})
    with_garlic = _item(name="garlic naan", dish_kind="meal")
    with_onion = _item(name="onion uttapam", dish_kind="meal")
    safe = _item(name="dal khichdi", dish_kind="meal")
    assert adheres_to_diet(with_garlic, p) is False
    assert adheres_to_diet(with_onion, p) is False
    assert adheres_to_diet(safe, p) is True


def test_adheres_diet_disliked_foods():
    """Disliked foods in name are rejected."""
    p = build_profile(0, {"disliked_foods": ["okra", "mushroom"]})
    okra = _item(name="okra fry", dish_kind="meal")
    mushroom = _item(name="mushroom curry", dish_kind="meal")
    safe = _item(name="dal makhani", dish_kind="meal")
    assert adheres_to_diet(okra, p) is False
    assert adheres_to_diet(mushroom, p) is False
    assert adheres_to_diet(safe, p) is True


def test_allergy_exclusion():
    """Peanut allergy blocks items containing peanut in name."""
    p = build_profile(0, {"allergies": ["peanut"]})
    item = _item(name="peanut chikki", dish_kind="snack")
    blocked = allergy_blocked(item, p)
    assert blocked == "peanut"


def test_allergy_exclusion_safe():
    """No allergy match returns None."""
    p = build_profile(0, {"allergies": ["peanut"]})
    item = _item(name="samosa", dish_kind="snack")
    assert allergy_blocked(item, p) is None


def test_validate_compatibility():
    """Returns messages for incompatible items."""
    p = build_profile(0, {"allergies": ["peanut"], "veg_level": "jain"})
    items = [
        _item(name="peanut chikki", dish_kind="snack"),
        _item(name="garlic naan", dish_kind="meal"),
        _item(name="dal khichdi", dish_kind="meal"),
    ]
    msgs = validate_compatibility(items, p)
    assert len(msgs) == 2  # peanut allergy + garlic jain violation


def test_soft_hints_shape():
    """soft_hints returns expected keys."""
    p = build_profile(0, {
        "favorite_cuisines": ["north_indian"],
        "portion_size": "large",
    })
    h = soft_hints(p)
    assert "preferred_cuisines" in h
    assert "portion_multiplier" in h
    assert h["portion_multiplier"] == 1.2