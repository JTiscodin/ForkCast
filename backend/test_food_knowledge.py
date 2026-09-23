"""Tests for food_knowledge.py — curated Indian food ontology."""
from food_knowledge import (
    lookup, CHENNA_TOAST, GULAB_JAMUN, SAMOSA,
    KIND_SWEET, KIND_SNACK, KIND_MEAL, KIND_BEVERAGE, KIND_CONDIMENT,
    SIDE, COMPLETE, BREAD,
    classify_meal_suitability, filter_by_diet, search_by_tags, stats,
)


def test_knowledge_lookup_chenna_toast():
    """Chenna Toast → sweet, not meal-eligible, served as piece."""
    entry = lookup("Chena Toast")
    assert entry is not None
    assert entry.dish_kind == KIND_SWEET
    assert entry.main_meal_eligible is False
    assert entry.serving_unit == "piece"
    assert entry.course == SIDE
    # Also match by alias
    alias = lookup("chhena toast mithai")
    assert alias is entry


def test_knowledge_lookup_samosa():
    """Samosa → snack, not meal-eligible."""
    entry = lookup("samosa")
    assert entry is not None
    assert entry.dish_kind == KIND_SNACK
    assert entry.main_meal_eligible is False
    assert entry.course == SIDE


def test_knowledge_lookup_gulab_jamun():
    """Gulab Jamun → sweet, side course."""
    entry = lookup("Gulab Jamun")
    assert entry is not None
    assert entry.dish_kind == KIND_SWEET
    assert entry.course == SIDE
    assert entry.main_meal_eligible is False


def test_knowledge_lookup_biryani():
    """Biryani → meal-eligible, complete course."""
    entry = lookup("biryani")
    assert entry is not None
    assert entry.dish_kind == KIND_MEAL
    assert entry.course == COMPLETE
    assert entry.main_meal_eligible is True


def test_knowledge_lookup_unknown():
    """Unknown item → None."""
    assert lookup("made up dish xyz123") is None
    assert lookup("") is None


def test_knowledge_lookup_lassi():
    """Lassi → beverage."""
    entry = lookup("lassi")
    assert entry is not None
    assert entry.dish_kind == KIND_BEVERAGE
    assert entry.main_meal_eligible is False


def test_knowledge_lookup_raita():
    """Raita → condiment."""
    entry = lookup("raita")
    assert entry is not None
    assert entry.dish_kind == KIND_CONDIMENT
    assert entry.main_meal_eligible is False


def test_classify_meal_suitability_known():
    """Known item returns full metadata with known=True."""
    meta = classify_meal_suitability("gulab jamun")
    assert meta["known"] is True
    assert meta["main_meal_eligible"] is False
    assert meta["dish_kind"] == KIND_SWEET
    assert meta["serving_unit"] == "piece"
    assert meta["satiety"] > 0


def test_classify_meal_suitability_unknown():
    """Unknown item returns defaults and known=False."""
    meta = classify_meal_suitability("nonexistent dish 9000")
    assert meta["known"] is False
    assert meta["main_meal_eligible"] is True  # default: allow through
    assert meta["dish_kind"] == ""


def test_search_by_tags_kind():
    """Search by kind returns matching entries (no dups)."""
    results = search_by_tags(kind=KIND_SWEET)
    assert len(results) >= 20  # many sweets registered
    # No duplicates despite alias keys
    assert len(results) == len(set(id(r) for r in results))


def test_search_by_tags_cuisine():
    """Search by cuisine returns matching entries."""
    results = search_by_tags(cuisine="bengali")
    assert len(results) >= 3  # at least rasgulla, chhena toast, sandesh


def test_filter_by_diet_veg():
    """Veg-only profile filters out non-veg items."""
    biryani = lookup("biryani")
    chicken_biryani = lookup("chicken biryani")
    profile = {"veg_only": True, "allowed_dietary_flags": ["veg"]}
    items = [b for b in (biryani, chicken_biryani) if b is not None]
    filtered = filter_by_diet(items, profile)
    # Veg biryani stays, chicken biryani goes
    for item in filtered:
        assert "nonveg" not in item.dietary_flags


def test_filter_by_diet_allergy():
    """Peanut allergy filters out peanut chikki."""
    profile = {"veg_only": False, "allowed_dietary_flags": [], "allergies": ["peanut"]}
    chikki = lookup("Peanut Chikki")
    items = [i for i in (chikki,) if i is not None]
    filtered = filter_by_diet(items, profile)
    assert len(filtered) == 0


def test_stats():
    """Stats returns correct counts."""
    s = stats()
    assert s["total_unique"] >= 50  # plently of entries
    assert "sweet" in s["by_kind"]
    assert "meal" in s["by_kind"]
    assert "veg" in s["by_diet"]