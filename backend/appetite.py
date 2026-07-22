"""Appetite / portion calculator (Docs section 4, Option A + light Option B).

Produces a per-user portion_multiplier the optimizer uses to size per-slot cost.

Improvement over doc:
  - Doc gives one flat multiplier. Real Indian eating varies by MEAL: breakfast is
    light (poha/idli), lunch heavy (thali), dinner medium. So we return per-slot
    multipliers, not one number. Optimizer can still collapse to a single number.
  - Added optional roti/rice anchor -> nudges multiplier, since "moderate" for a
    6-roti eater != "moderate" for a 2-roti eater.
"""
from dataclasses import dataclass, field, asdict

# Base multipliers per appetite level (Docs section 4).
LEVEL_MULT = {
    "light": 0.75,
    "moderate": 1.0,
    "heavy": 1.3,
    "very_heavy": 1.6,
}

# Meal-slot weighting for Indian eating pattern. Lunch heaviest.
# These scale the base multiplier per slot (sum-neutral-ish around 1.0).
SLOT_WEIGHT = {
    "breakfast": 0.8,
    "lunch": 1.2,
    "dinner": 1.0,
}


@dataclass
class AppetiteProfile:
    user_id: int
    appetite_level: str = "moderate"          # light|moderate|heavy|very_heavy
    base_multiplier: float = 1.0              # derived from level (+ anchor nudge)
    roti_per_meal: int = None                 # optional concrete anchor
    rice_katori_per_meal: int = None          # optional (1 katori ~ 1 serving rice)
    per_slot: dict = field(default_factory=dict)  # {breakfast,lunch,dinner: mult}

    def to_row(self):
        return asdict(self)


def _anchor_nudge(level: str, roti: int, rice: int) -> float:
    """Small correction from concrete quantity. Neutral if no anchor given."""
    if roti is None and rice is None:
        return 0.0
    units = (roti or 0) + (rice or 0) * 1.5  # 1 katori rice ~ 1.5 roti energy
    # typical moderate ~ 4 units/meal. Deviation nudges +/- up to ~0.25.
    if units == 0:
        return 0.0
    delta = (units - 4) * 0.06
    return max(-0.25, min(0.25, round(delta, 3)))


def build_profile(user_id, appetite_level="moderate",
                  roti_per_meal=None, rice_katori_per_meal=None) -> AppetiteProfile:
    level = appetite_level.lower().strip()
    if level not in LEVEL_MULT:
        raise ValueError(f"bad appetite_level: {appetite_level}")
    base = LEVEL_MULT[level] + _anchor_nudge(level, roti_per_meal, rice_katori_per_meal)
    base = round(max(0.5, base), 3)
    per_slot = {slot: round(base * w, 3) for slot, w in SLOT_WEIGHT.items()}
    return AppetiteProfile(
        user_id=user_id,
        appetite_level=level,
        base_multiplier=base,
        roti_per_meal=roti_per_meal,
        rice_katori_per_meal=rice_katori_per_meal,
        per_slot=per_slot,
    )


def slot_multiplier(profile: AppetiteProfile, meal_type: str) -> float:
    return profile.per_slot.get(meal_type, profile.base_multiplier)


if __name__ == "__main__":
    for lvl in LEVEL_MULT:
        p = build_profile(1, lvl)
        print(lvl, "base", p.base_multiplier, "slots", p.per_slot)
    print("anchor 8 roti:", build_profile(1, "moderate", roti_per_meal=8).base_multiplier)
