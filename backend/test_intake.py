"""Test constraint parser for pairing patterns."""
from intake import fallback_parse, ParsedIntake


def test_dessert_with_dinner_always():
    """Parser should recognize 'dessert with dinner always' pattern."""
    result = fallback_parse("15k budget, I want dessert with dinner always")

    assert len(result.constraints) == 1, f"Expected 1 constraint, got {len(result.constraints)}"

    c = result.constraints[0]
    assert c.get("dish_kind") == "sweet", f"Expected dish_kind=sweet, got {c.get('dish_kind')}"
    assert c.get("slot_type") == "dinner", f"Expected slot_type=dinner, got {c.get('slot_type')}"
    assert c.get("frequency") == "always", f"Expected frequency=always, got {c.get('frequency')}"
    print("OK: 'dessert with dinner always' parsed correctly")


def test_drinks_with_lunch_every_day():
    """Parser should recognize 'drinks with lunch every day' pattern."""
    result = fallback_parse("15000 budget, drinks with lunch every day")

    assert len(result.constraints) == 1

    c = result.constraints[0]
    assert c.get("dish_kind") == "beverage", f"Expected dish_kind=beverage, got {c.get('dish_kind')}"
    assert c.get("slot_type") == "lunch", f"Expected slot_type=lunch, got {c.get('slot_type')}"
    assert c.get("frequency") == "always"
    print("OK: 'drinks with lunch every day' parsed correctly")


def test_sweet_after_dinner_daily():
    """Parser should recognize 'sweet after dinner daily' pattern."""
    result = fallback_parse("12k budget, sweet after dinner daily")

    assert len(result.constraints) == 1

    c = result.constraints[0]
    assert c.get("dish_kind") == "sweet"
    assert c.get("slot_type") == "dinner"
    assert c.get("frequency") == "always"
    print("OK: 'sweet after dinner daily' parsed correctly")


def test_relaxed_pattern_without_always():
    """Parser should catch 'drinks with lunch' even without explicit 'always'."""
    result = fallback_parse("10k budget, drinks with lunch")

    assert len(result.constraints) == 1

    c = result.constraints[0]
    assert c.get("dish_kind") == "beverage"
    assert c.get("slot_type") == "lunch"
    assert c.get("frequency") == "always"  # should default to always
    print("OK: Relaxed pattern 'drinks with lunch' parsed correctly")


def test_multiple_pairing_constraints():
    """Parser should handle multiple pairing constraints."""
    result = fallback_parse("20k budget, dessert with dinner always, drinks with lunch")

    assert len(result.constraints) == 2, f"Expected 2 constraints, got {len(result.constraints)}"

    # Find each constraint
    dessert = next((c for c in result.constraints if c.get("dish_kind") == "sweet"), None)
    drinks = next((c for c in result.constraints if c.get("dish_kind") == "beverage"), None)

    assert dessert is not None, "Dessert constraint not found"
    assert drinks is not None, "Drinks constraint not found"

    assert dessert.get("slot_type") == "dinner"
    assert drinks.get("slot_type") == "lunch"
    print("OK: Multiple pairing constraints parsed correctly")


def test_traditional_constraints_still_work():
    """Existing 'N dish_tag meals' pattern should still work."""
    result = fallback_parse("15k budget, at least 10 paneer meals")

    assert len(result.constraints) == 1

    c = result.constraints[0]
    assert c.get("dish_tag") == "paneer"
    assert c.get("min_count") == 10
    print("OK: Traditional constraint pattern still works")


def test_mixed_traditional_and_pairing():
    """Should handle both traditional and pairing constraints together."""
    result = fallback_parse("20k budget, 10 paneer meals, dessert with dinner always")

    assert len(result.constraints) == 2

    paneer = next((c for c in result.constraints if c.get("dish_tag") == "paneer"), None)
    dessert = next((c for c in result.constraints if c.get("dish_kind") == "sweet"), None)

    assert paneer is not None
    assert dessert is not None
    assert paneer.get("min_count") == 10
    assert dessert.get("slot_type") == "dinner"
    print("OK: Mixed traditional and pairing constraints work together")


if __name__ == "__main__":
    test_dessert_with_dinner_always()
    test_drinks_with_lunch_every_day()
    test_sweet_after_dinner_daily()
    test_relaxed_pattern_without_always()
    test_multiple_pairing_constraints()
    test_traditional_constraints_still_work()
    test_mixed_traditional_and_pairing()
    print("\nOK: All constraint parser tests passed")
