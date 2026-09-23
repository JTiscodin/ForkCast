"""Pairing system for adding desserts/drinks to meal slots.

PASS 4 of the optimizer: After main meals are placed (PASS 1-3), add optional
pairings like "dessert with dinner always" or "drinks with lunch" within the
remaining budget.

This is SEPARATE from the curry+bread composition system (course.py) which is
structural - curries MUST have bread. Pairings are optional extras that enhance
the meal when budget allows.
"""
from catalog import Dish, variant_price
from appetite import slot_multiplier
import course as course_rules


def _add_pairings(slots, pairing_constraints, pool, budget, current_total, profile,
                  extra_pairing_dishes=None, taste_profile=None):
    """Add desserts/drinks to slots based on pairing constraints.

    Args:
        slots: list of PlannedSlot - MUTATED in place with pairing additions
        pairing_constraints: list of Constraint with dish_kind + slot_type + frequency
        pool: full catalog (already veg-filtered)
        budget: total monthly budget
        current_total: cost so far (from PASS 1-3)
        profile: AppetiteProfile for portion multipliers
        extra_pairing_dishes: optional extra Dish candidates (Instamart
            groceries). Merged into the kind pools ONLY — they never join
            `pool`, so the main placement/bread/repair passes can't see them.

    Returns:
        new total cost after adding pairings
    """
    remaining = budget - current_total
    if remaining <= 0:
        return current_total

    # Diet-filter the pairing candidates against taste_profile when given, so
    # a veg-only / Jain / health-restricted user never has a non-compliant
    # dessert or drink offered, even when the main meal is fine.
    if taste_profile is not None:
        from taste_profile import adheres_to_diet
        filtered_pool = [d for d in pool if adheres_to_diet(d, taste_profile)]
        filtered_extra = [d for d in (extra_pairing_dishes or [])
                        if adheres_to_diet(d, taste_profile)]
    else:
        filtered_pool = list(pool)
        filtered_extra = list(extra_pairing_dishes or [])
    candidates_all = filtered_pool + filtered_extra

    # Build pairing pools by kind. Groceries join here on equal footing:
    # same rating bar, same variety rotation — a Rs17 Instamart milk vs a
    # Rs80 restaurant lassi competes on (least-used, rating, price), and the
    # better one wins per slot rather than by source.
    sweets = [d for d in candidates_all
              if d.dish_kind == course_rules.KIND_SWEET
              and d.rating >= 3.5]  # Higher bar for desserts
    beverages = [d for d in candidates_all
                if d.dish_kind == course_rules.KIND_BEVERAGE
                and d.rating >= 3.5]
    snacks = [d for d in candidates_all
              if d.dish_kind == course_rules.KIND_SNACK
              and d.rating >= 3.5]
    if taste_profile is not None:
        from taste_profile import soft_hints
        _hints = soft_hints(taste_profile)
        _pref = set(_hints.get("preferred_cuisines", []))
        _dislike = set(_hints.get("disliked_foods", []))
    else:
        _pref, _dislike = set(), set()

    pairing_pool = {
        "sweet": sweets,
        "beverage": beverages,
        "snack": snacks,
    }

    # Group constraints by slot type
    by_slot_type = {}
    for c in pairing_constraints:
        if c.slot_type not in by_slot_type:
            by_slot_type[c.slot_type] = []
        by_slot_type[c.slot_type].append(c)

    # Track what we've added to avoid duplicates
    added_cost = 0.0
    used_dishes = {}  # dish_id -> count this month

    # Process each slot that matches a constraint
    for slot in slots:
        if slot.meal_type not in by_slot_type:
            continue

        constraints_for_this_slot = by_slot_type[slot.meal_type]

        for c in constraints_for_this_slot:
            # Only "always" frequency for now - could extend to "optional"
            if c.frequency != "always":
                continue

            pool_for_kind = pairing_pool.get(c.dish_kind, [])
            if not pool_for_kind:
                continue  # No dishes of this kind available

            # Pick the best-rated dish we haven't overused
            # Sort by: taste preference (preferred cuisine first, disliked
            # last), least-used first, then highest-rated, then cheapest.
            def _pref_key(d):
                c = d.cuisine.lower()
                if _pref and c in _pref:
                    return 0
                if _dislike and any(x in d.name.lower() for x in _dislike):
                    return 2
                return 1
            candidates = sorted(
                pool_for_kind,
                key=lambda d: (
                    _pref_key(d),
                    used_dishes.get(d.dish_id, 0),  # variety: least-used first
                    -d.rating,  # quality: highest-rated
                    d.price,  # value: cheapest
                )
            )

            # Try each candidate until we find one that fits budget
            for dish in candidates:
                # Calculate portion-adjusted price for this pairing
                mult = slot_multiplier(profile, slot.meal_type)
                variant, price = variant_price(dish, mult * 0.5)  # Half portion for pairings

                if added_cost + price > remaining:
                    continue  # Too expensive, try next

                # Add this pairing to the slot
                # Use side2 fields since side/side2 are for bread/rice
                # NOTE: This is a temporary hack - proper solution is to add
                # dedicated pairing fields to PlannedSlot
                if not slot.side_dish_id:
                    # Use side fields if empty (curry has no bread yet)
                    slot.side_dish_id = dish.dish_id
                    slot.side_dish_name = dish.name
                    slot.side_qty = 1
                    slot.side_price = price
                    slot.side_restaurant_name = dish.restaurant_name
                    slot.side_image_url = dish.image_url or ""
                    slot.side_source = getattr(dish, "source", "")
                elif not slot.side2_dish_id:
                    # Use side2 fields
                    slot.side2_dish_id = dish.dish_id
                    slot.side2_dish_name = dish.name
                    slot.side2_qty = 1
                    slot.side2_price = price
                    slot.side2_restaurant_name = dish.restaurant_name
                    slot.side2_image_url = dish.image_url or ""
                    slot.side2_source = getattr(dish, "source", "")
                else:
                    # Both side slots full (curry has bread + already has a pairing)
                    # Skip this pairing
                    break

                added_cost += price
                used_dishes[dish.dish_id] = used_dishes.get(dish.dish_id, 0) + 1
                remaining = budget - current_total - added_cost
                break  # Found a pairing for this constraint

    return current_total + added_cost
