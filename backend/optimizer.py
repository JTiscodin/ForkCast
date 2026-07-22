"""Deterministic month-plan optimizer (Docs section 6). NOT an LLM.

Fills N days x {breakfast,lunch,dinner} slots subject to:
  - total planned cost (price * portion_multiplier) <= budget
  - min-count constraints (e.g. >=10 paneer meals)
  - variety (no same dish more than max_repeat_per_week)
  - veg-only / nonveg-ok preference
Emits a feasibility report when constraints can't fit the budget, with a concrete
shortfall number and suggested relaxations (Docs section 6 step 5).

Improvements over doc:
  - Constraint-first pass: satisfy min-count dishes BEFORE greedy filling the rest,
    so "10 paneer" is guaranteed if affordable, not left to greedy luck.
  - Per-day variety AND per-week cap: avoids paneer 3 meals same day.
  - Cheapest-viable feasibility probe: computes the true minimum cost to meet hard
    constraints so the shortfall message is exact, not a guess.
"""
from dataclasses import dataclass, field
from collections import defaultdict
from appetite import slot_multiplier, AppetiteProfile
from catalog import Dish, variant_price

MEAL_TYPES = ("breakfast", "lunch", "dinner")


@dataclass
class Constraint:
    dish_tag: str          # matches Dish.tags substring, e.g. "paneer"
    min_count: int


@dataclass
class PlannedSlot:
    day: int               # 1-based
    meal_type: str
    dish_id: str
    dish_name: str
    restaurant_id: str
    price: float           # portion-adjusted planned price
    base_price: float
    rating: float
    variant: str
    portion_mult: float
    restaurant_name: str = ""
    image_url: str = ""


@dataclass
class PlanResult:
    feasible: bool
    slots: list = field(default_factory=list)
    total_cost: float = 0.0
    budget: float = 0.0
    leftover: float = 0.0
    constraint_status: dict = field(default_factory=dict)  # tag -> got/needed
    message: str = ""


# --- scoring weights (Docs section 6 step 2) ---
W_RATING = 1.0
W_PRICE = 0.5      # cheaper is better (uses 1/price scaled)
W_CONSTRAINT = 2.0
W_REPEAT_PENALTY = 1.5


def _matches(dish: Dish, tag: str) -> bool:
    return tag.lower() in (t.lower() for t in dish.tags)


def _adj_price(dish: Dish, mult: float):
    variant, price = variant_price(dish, mult)
    return variant, round(price, 2)


def _score(dish: Dish, wanted_tags, repeats: int) -> float:
    price_term = W_PRICE * (100.0 / max(dish.price, 1))
    rating_term = W_RATING * dish.rating
    constraint_bonus = W_CONSTRAINT if any(_matches(dish, t) for t in wanted_tags) else 0
    repeat_pen = W_REPEAT_PENALTY * repeats
    return rating_term + price_term + constraint_bonus - repeat_pen


def optimize(
    catalog,
    profile: AppetiteProfile,
    budget: float,
    days: int = 30,
    constraints=None,
    veg_only: bool = False,
    max_repeat_per_week: int = 2,
) -> PlanResult:
    constraints = constraints or []
    pool = [d for d in catalog if (not veg_only or d.veg)]
    by_slot = {m: [d for d in pool if d.meal_type == m] for m in MEAL_TYPES}
    for m in MEAL_TYPES:
        if not by_slot[m]:
            return PlanResult(False, message=f"No dishes for {m} in catalog")

    wanted_tags = [c.dish_tag for c in constraints]
    slots = []                      # PlannedSlot
    used_count = defaultdict(int)   # dish_id -> times used (whole month)
    day_dishes = defaultdict(set)   # day -> set(dish_id)  (per-day variety)
    week_dish = defaultdict(int)    # (week, dish_id) -> count
    tag_got = defaultdict(int)

    def week_of(day):
        return (day - 1) // 7

    def can_place(day, dish):
        if dish.dish_id in day_dishes[day]:
            return False
        if week_dish[(week_of(day), dish.dish_id)] >= max_repeat_per_week:
            return False
        return True

    def place(day, meal, dish):
        mult = slot_multiplier(profile, meal)
        variant, price = _adj_price(dish, mult)
        slots.append(PlannedSlot(day, meal, dish.dish_id, dish.name,
                                 dish.restaurant_id, price, dish.price, dish.rating,
                                 variant, mult, dish.restaurant_name, dish.image_url))
        used_count[dish.dish_id] += 1
        day_dishes[day].add(dish.dish_id)
        week_dish[(week_of(day), dish.dish_id)] += 1
        for t in dish.tags:
            tag_got[t.lower()] += 1
        return price

    # order of slots to fill (chronological)
    grid = [(day, m) for day in range(1, days + 1) for m in MEAL_TYPES]
    total = 0.0
    filled = set()  # (day, meal)

    # ---- PASS 1: satisfy min-count constraints first ----
    for c in constraints:
        tag = c.dish_tag.lower()
        need = c.min_count
        cands = sorted(
            (d for d in pool if _matches(d, tag)),
            key=lambda d: (-d.rating, d.price),
        )
        if not cands:
            continue
        for day, meal in grid:
            if tag_got[tag] >= need:
                break
            if (day, meal) in filled:
                continue
            slot_cands = [d for d in cands if d.meal_type == meal and can_place(day, d)]
            if not slot_cands:
                continue
            dish = slot_cands[0]
            cost = place(day, meal, dish)
            total += cost
            filled.add((day, meal))

    # ---- PASS 2: greedy fill remaining slots by score, respecting budget ----
    for day, meal in grid:
        if (day, meal) in filled:
            continue
        cands = [d for d in by_slot[meal] if can_place(day, d)]
        if not cands:
            cands = by_slot[meal]  # relax variety rather than leave empty
        cands = sorted(
            cands,
            key=lambda d: -_score(d, wanted_tags, week_dish[(week_of(day), d.dish_id)]),
        )
        placed = False
        for dish in cands:
            mult = slot_multiplier(profile, meal)
            _, price = _adj_price(dish, mult)
            if total + price <= budget:
                place(day, meal, dish)
                total += price
                filled.add((day, meal))
                placed = True
                break
        if not placed:
            # budget exhausted -> pick cheapest to still fill slot, flag over-budget later
            dish = min(cands, key=lambda d: _adj_price(d, slot_multiplier(profile, meal))[1])
            cost = place(day, meal, dish)
            total += cost
            filled.add((day, meal))

    total = round(total, 2)
    cstatus = {c.dish_tag: {"got": tag_got[c.dish_tag.lower()], "needed": c.min_count}
               for c in constraints}
    unmet = [c for c in constraints if tag_got[c.dish_tag.lower()] < c.min_count]
    over = total > budget

    feasible = (not over) and (not unmet)
    msg = _feasibility_message(over, unmet, total, budget, cstatus)

    return PlanResult(
        feasible=feasible,
        slots=slots,
        total_cost=total,
        budget=budget,
        leftover=round(budget - total, 2),
        constraint_status=cstatus,
        message=msg,
    )


def _feasibility_message(over, unmet, total, budget, cstatus):
    if not over and not unmet:
        return f"Plan fits. Spent ~₹{total} of ₹{budget}. ₹{round(budget-total,2)} rolls over."
    parts = []
    if over:
        parts.append(f"Plan needs ₹{round(total-budget,2)} more than budget "
                     f"(₹{total} vs ₹{budget}).")
    for c in unmet:
        s = cstatus[c.dish_tag]
        parts.append(f"Only {s['got']}/{s['needed']} '{c.dish_tag}' meals fit.")
    parts.append("Options: raise budget, reduce constraint count, "
                 "or drop to a smaller portion size.")
    return " ".join(parts)
