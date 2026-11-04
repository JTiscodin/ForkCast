"""User taste & diet preference profile for meal planning.

Collected at onboarding + supplemented by blueprint_chat. Drives hard filters
(the optimizer MUST respect veg_level, allergies, and health exclusions) and
soft ranking hints (cuisine preferences, spice level, disliked items).

Every function in this module is deterministic and zero-dependency — no LLM,
no network, no database.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ---- Constants ---------------------------------------------------------------

# Dietary levels — each implies a set of allowed dietary_flags.
VEG_LEVELS = {
    "veg":             ("veg",),
    "nonveg":          ("veg", "nonveg", "eggetarian"),
    "eggetarian":      ("veg", "eggetarian"),
    "jain":            ("veg",),
    "vegan":           ("veg",),
}

# Items blocked for Jain diet (no root vegetables, garlic, onion, etc.)
# This is a name-keyword list; items whose name contains these are excluded.
_JAIN_BLOCKED_KEYWORDS = (
    "garlic", "lassan", "lasan", "lehsun",
    "onion", "pyaz", "kanda", "onion",
    "potato", "aloo", "aalu",
    "carrot", "gajar",
    "radish", "mooli",
    "beetroot", "chukandar",
    "sweet potato", "shakarkandi",
    "ginger", "adrak",
    "turmeric", "haldi", "raw turmeric",
    "mushroom", "khumb",
    "cauliflower", "phool gobhi",
    "broccoli",
    "cabbage", "patta gobhi",
    "brinjal", "baingan", "eggplant",
)

# Health-goal -> excluded dish_kinds & satiety upper bounds.
_HEALTH_CONSTRAINTS = {
    "diabetic_friendly": {
        "exclude_kinds": ("sweet",),
        "max_satiety": None,
        "exclude_health_tags": ("sugary", "high_sugar"),
    },
    "low_sodium": {
        "exclude_kinds": ("condiment",),
        "max_satiety": None,
        "exclude_health_tags": ("salty",),
    },
    "high_protein": {
        "exclude_kinds": (),
        "max_satiety": None,
        "require_health_tags": ("high_protein", "protein_rich"),
    },
    "weight_loss": {
        "exclude_kinds": ("sweet", "beverage"),
        "max_satiety": 0.6,
        "exclude_health_tags": ("high_calorie", "sugary"),
    },
    "low_calorie": {
        "exclude_kinds": ("sweet",),
        "max_satiety": 0.5,
        "exclude_health_tags": ("high_calorie", "high_sugar"),
    },
}

# Spice level preferences sorted by intensity.
SPICE_LEVELS = ("mild", "medium", "spicy", "hot")


# ---- Data model -------------------------------------------------------------

@dataclass
class TasteProfile:
    """User's taste, diet, and health preference profile.

    Stored in-memory per session (like the existing plan state). A future
    enhancement can persist to SQLite by user_id.
    """
    user_id: int = 0

    # Diet — treated as hard filters by the optimizer
    veg_level: str = "veg"           # veg|nonveg|eggetarian|jain|vegan

    # Health — hard exclusions when flagged as allergy/intolerance
    allergies: tuple = ()            # ("peanut", "dairy", "gluten", "soy", "shellfish", …)
    health_goals: tuple = ()         # ("diabetic_friendly", "low_sodium", "high_protein", …)

    # Taste — soft preferences for ranking, not hard optimizer filters
    spice_preference: int = 3        # 1 (mild) — 5 (very hot)
    favorite_cuisines: tuple = ()    # ("north_indian", "south_indian", "chinese", …)
    disliked_foods: tuple = ()       # specific items or ingredients to avoid
    portion_size: str = "medium"     # small|medium|large

    # Free text — for AI interpretation
    notes: str = ""

    # Derived at build time — cached here so consumers don't recompute.
    _allowed_dietary_flags: tuple = ("veg",)

    def allowed_flags(self) -> tuple[str, ...]:
        """Return the dietary_flags this profile permits."""
        return self._allowed_dietary_flags or VEG_LEVELS.get(self.veg_level, ("veg",))


# ---- Public API -------------------------------------------------------------

def build_profile(user_id: int, raw: dict) -> TasteProfile:
    """Normalise UI/blueprint input into a TasteProfile.

    Expected raw keys (case-insensitive, all optional):
      veg_level, allergies (list), health_goals (list),
      spice_preference (int 1-5), favorite_cuisines (list),
      disliked_foods (list), portion_size, notes
    """
    raw = raw or {}
    veg = (raw.get("veg_level") or "veg").lower().strip()
    if veg not in VEG_LEVELS:
        veg = "veg"

    spice_preference = raw.get("spice_preference")
    if spice_preference is None:
        spice_preference = 3

    profile = TasteProfile(
        user_id=user_id,
        veg_level=veg,
        allergies=tuple(raw.get("allergies") or []),
        health_goals=tuple(g.lower().strip()
                           for g in (raw.get("health_goals") or [])
                           if g.strip()),
        spice_preference=max(1, min(5, int(spice_preference))),
        favorite_cuisines=tuple(
            c.lower().strip() for c in (raw.get("favorite_cuisines") or []) if c.strip()),
        disliked_foods=tuple(
            f.lower().strip() for f in (raw.get("disliked_foods") or []) if f.strip()),
        portion_size=(raw.get("portion_size") or "medium").lower().strip(),
        notes=(raw.get("notes") or "").strip(),
        _allowed_dietary_flags=VEG_LEVELS.get(veg, ("veg",)),
    )
    return profile


def hard_filters(profile: TasteProfile) -> dict:
    """Return a dict of filters the optimizer MUST enforce.

    Returns:
      {"veg_only": bool,
       "allowed_dietary_flags": [str, ...],
       "allergies": [str, ...],
       "health_exclusions": {"exclude_kinds": [str, ...],
                              "max_satiety": float|None,
                              "require_health_tags": [str, ...],
                              "exclude_health_tags": [str, ...]},
       "disliked_foods": [str, ...],
       "jain": bool}
    """
    veg_only = profile.veg_level in ("veg", "jain", "vegan")
    is_jain = profile.veg_level == "jain"

    # Merge health-goal exclusions.
    merged_excl = {"exclude_kinds": set(), "max_satiety": None,
                   "require_health_tags": set(), "exclude_health_tags": set()}
    for goal in profile.health_goals:
        rules = _HEALTH_CONSTRAINTS.get(goal, {})
        merged_excl["exclude_kinds"].update(rules.get("exclude_kinds", ()))
        sat = rules.get("max_satiety")
        if sat is not None and (merged_excl["max_satiety"] is None or sat < merged_excl["max_satiety"]):
            merged_excl["max_satiety"] = sat
        merged_excl["require_health_tags"].update(rules.get("require_health_tags", ()))
        merged_excl["exclude_health_tags"].update(rules.get("exclude_health_tags", ()))

    return {
        "veg_only": veg_only,
        "allowed_dietary_flags": list(profile.allowed_flags()),
        "allergies": list(profile.allergies),
        "health_exclusions": {k: list(v) if isinstance(v, set) else v
                              for k, v in merged_excl.items()},
        "disliked_foods": list(profile.disliked_foods),
        "jain": is_jain,
    }


def soft_hints(profile: TasteProfile) -> dict:
    """Return ranking hints for the AI/optimizer — not hard constraints.

    Returns:
      {"preferred_cuisines": [str, ...],
       "avoid_spice_above": int (max spice on 1-5 scale),
       "preferred_spice": int,
       "portion_multiplier": float,
       "disliked_foods": [str, ...]}
    """
    portion_map = {"small": 0.85, "medium": 1.0, "large": 1.2}
    return {
        "preferred_cuisines": list(profile.favorite_cuisines),
        "avoid_spice_above": profile.spice_preference,
        "preferred_spice": profile.spice_preference,
        "portion_multiplier": portion_map.get(profile.portion_size, 1.0),
        "disliked_foods": list(profile.disliked_foods),
    }


def adheres_to_diet(item, profile: TasteProfile) -> bool:
    """Check if a single item (Dish or FoodKnowledge) passes all diet filters.

    Args:
        item: must have .veg, .dietary_flags (tuple), .name (str),
              .dish_kind (str), .health_tags (tuple), .satiety (float)

    Returns: True if the item is safe for this profile.
    """
    filters = hard_filters(profile)
    if filters["jain"] and hasattr(item, "name"):
        n = (item.name or "").lower()
        if any(kw in n for kw in _JAIN_BLOCKED_KEYWORDS):
            return False
    if filters["veg_only"] and hasattr(item, "veg"):
        if not item.veg:
            return False
    # Health kind exclusions
    excl_kinds = filters["health_exclusions"].get("exclude_kinds", [])
    if item.dish_kind in excl_kinds:
        return False
    # Health tag requirements — only enforced on meal-kind items, not on
    # pairings (beverages, sweets, snacks, condiments). A gulab jamun doesn't
    # need to be high-protein; the protein constraint applies to the mains.
    req_tags = filters["health_exclusions"].get("require_health_tags", [])
    if req_tags and item.dish_kind in ("meal",):
        item_tags = set(item.health_tags if hasattr(item, "health_tags") else ())
        if not any(t in item_tags for t in req_tags):
            return False
    # Health tag exclusions
    excl_tags = filters["health_exclusions"].get("exclude_health_tags", [])
    if excl_tags:
        item_tags = set(item.health_tags if hasattr(item, "health_tags") else ())
        if any(t in item_tags for t in excl_tags):
            return False
    # Max satiety
    max_sat = filters["health_exclusions"].get("max_satiety")
    if max_sat is not None and hasattr(item, "satiety") and item.satiety is not None:
        if item.satiety > max_sat:
            return False
    # Allergy check — delegate to allergy_blocked so logic stays in one place
    if profile.allergies and allergy_blocked(item, profile) is not None:
        return False
    # Disliked foods (name check)
    if hasattr(item, "name") and profile.disliked_foods:
        n = item.name.lower()
        if any(df in n for df in profile.disliked_foods):
            return False
    return True


def allergy_blocked(item, profile: TasteProfile) -> str | None:
    """Return the allergen name if the item conflicts with an allergy.

    Checks the item name and dietary_flags against known allergen keywords.
    Returns the matched allergen string, or None if safe.
    """
    if not profile.allergies or not hasattr(item, "name"):
        return None
    n = (item.name or "").lower()
    item_words = set(n.split())
    for allergen in profile.allergies:
        allergen_lower = allergen.lower()
        if allergen_lower in item_words or allergen_lower in n:
            return allergen
        # Check allergy vs Jain-blocked keywords (e.g., "garlic")
        if allergen_lower in _JAIN_BLOCKED_KEYWORDS and allergen_lower in n:
            return allergen
    return None


def validate_compatibility(items: list, profile: TasteProfile) -> list[str]:
    """Return a list of incompatibility messages for a set of items.

    Each message describes why an item doesn't fit the profile.
    Empty list = all items compatible.
    """
    messages = []
    filters = hard_filters(profile)
    for item in items:
        if filters["jain"] and hasattr(item, "name"):
            n = (item.name or "").lower()
            for kw in _JAIN_BLOCKED_KEYWORDS:
                if kw in n:
                    messages.append(
                        f"{item.name} contains {kw} which is not allowed in a Jain diet")
                    break
        allergen = allergy_blocked(item, profile)
        if allergen:
            messages.append(f"{item.name} conflicts with your {allergen} allergy")
    return messages