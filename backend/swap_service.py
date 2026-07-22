"""Swap Engine (Docs section 8 'other' branch).

Given a slot the user rejected, return alternatives in the same meal type within
a ± price band, preserving the user's portion multiplier (Docs section 4 note:
swap must respect appetite, not just price).
"""
from catalog import variant_price


def alternatives(slot, catalog, profile_mult=1.0, band=100, veg_only=False, limit=5):
    """slot: dict with meal_type, dish_id, price. Returns ranked alt dishes."""
    meal_type = slot["meal_type"]
    target = slot["price"]
    cur_id = slot["dish_id"]
    cands = []
    for d in catalog:
        if d.meal_type != meal_type or d.dish_id == cur_id:
            continue
        if veg_only and not d.veg:
            continue
        variant, price = variant_price(d, profile_mult)
        if abs(price - target) <= band:
            cands.append({
                "dish_id": d.dish_id,
                "name": d.name,
                "restaurant_id": d.restaurant_id,
                "restaurant_name": d.restaurant_name,
                "image_url": d.image_url,
                "price": price,
                "variant": variant,
                "rating": d.rating,
                "veg": d.veg,
            })
    # rank: higher rating, then closer to target price
    cands.sort(key=lambda c: (-c["rating"], abs(c["price"] - target)))
    return cands[:limit]
