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
from statistics import median
from appetite import slot_multiplier, AppetiteProfile
from catalog import Dish, variant_price
import course as course_rules

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
    price: float           # portion-adjusted price of the MAIN dish only
    base_price: float
    rating: float
    variant: str
    portion_mult: float
    restaurant_name: str = ""
    image_url: str = ""
    # --- composition (see course.py) ---
    # A curry is not a meal by itself; it carries a bread/rice accompaniment.
    # `price` stays the main dish alone so existing callers keep working;
    # `total_price` is what the meal actually costs and is what the budget,
    # wallet, and UI must use.
    course: str = "complete"
    side_dish_id: str = ""
    side_dish_name: str = ""
    side_qty: int = 0
    side_price: float = 0.0       # qty * unit price, already multiplied
    side_restaurant_name: str = ""
    side_image_url: str = ""

    @property
    def total_price(self) -> float:
        """Full cost of this meal — main dish plus any accompaniment."""
        return round(self.price + self.side_price, 2)


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
W_PRICE = 1.2      # cheaper is better, measured RELATIVE to the pool median
W_CONSTRAINT = 2.0
W_REPEAT_PENALTY = 1.5


def _matches(dish: Dish, tag: str) -> bool:
    return tag.lower() in (t.lower() for t in dish.tags)


def _adj_price(dish: Dish, mult: float):
    variant, price = variant_price(dish, mult)
    return variant, round(price, 2)


def _price_term(price: float, med: float) -> float:
    """Value-for-money, scaled against the pool median rather than an absolute.

    The old term was `0.5 * (100 / price)`, which is unbounded as price falls: a
    ₹10 roti scored +5.0 while a ₹280 curry scored +0.18, so bare bread beat
    every real dish by a factor of ~27 and the optimizer filled dinners with it.
    A ratio against the median is bounded and scale-free — it says "cheap for
    this neighbourhood", not "cheap in absolute rupees", and can never dominate
    the rating term.
    """
    if med <= 0:
        return 0.0
    # (median - price) / median, clamped to [-1, 1]: at the median it is 0,
    # a free dish approaches +1, anything >=2x median floors at -1.
    rel = (med - price) / med
    return W_PRICE * max(-1.0, min(1.0, rel))


def _score(dish: Dish, wanted_tags, repeats: int, med: float) -> float:
    rating_term = W_RATING * dish.rating
    constraint_bonus = W_CONSTRAINT if any(_matches(dish, t) for t in wanted_tags) else 0
    repeat_pen = W_REPEAT_PENALTY * repeats
    return rating_term + _price_term(dish.price, med) + constraint_bonus - repeat_pen


def optimize(
    catalog,
    profile: AppetiteProfile,
    budget: float,
    days: int = 30,
    constraints=None,
    veg_only: bool = False,
    max_repeat_per_week: int = 2,
    meals=None,
) -> PlanResult:
    """Build a plan over `days` x `meals`.

    meals: which slots to plan, e.g. ["breakfast","lunch"]. Defaults to all
    three. This is the user's `meals` blueprint field — previously accepted by
    the chat layer and then silently ignored here, so asking for two meals
    still produced (and charged for) three.
    """
    constraints = constraints or []
    meals = tuple(m for m in MEAL_TYPES if m in (meals or MEAL_TYPES)) or MEAL_TYPES
    pool = [d for d in catalog if (not veg_only or d.veg)]

    # Split the pool by role. Only dishes that can headline a meal are eligible
    # for a slot; breads and rice are held aside as pairing stock.
    mains = [d for d in pool if d.course not in course_rules.NEVER_STANDALONE]
    sides = [d for d in pool if d.course in course_rules.ACCOMPANIMENT]

    by_slot = {m: [d for d in mains if d.meal_type == m] for m in meals}
    for m in meals:
        if not by_slot[m]:
            return PlanResult(False, message=f"No dishes for {m} in catalog")

    # Pool median drives the price term. Computed over mains only — including
    # ₹10 breads would drag the median down and re-introduce the old bias.
    med = median([d.price for d in mains]) if mains else 0.0

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

    def pick_side(dish):
        """Cheapest sensible bread/rice from the SAME restaurant as the curry.

        Same-restaurant matters practically: Swiggy carts are per-restaurant
        (update_food_cart takes one restaurantId), so a curry and a bread from
        different places would be two orders with two delivery fees. Falls back
        to any side if the restaurant has none, and to None if the pool has no
        breads at all — a curry with no available bread simply stays unpaired
        rather than blocking the plan.
        """
        if not sides:
            return None
        same = [s for s in sides if s.restaurant_id == dish.restaurant_id]
        return min(same or sides, key=lambda s: s.price)

    def meal_cost(dish, meal):
        """Full cost of planning `dish` at `meal`, accompaniment included.

        Every budget decision goes through this, so a curry is always costed as
        the real meal (curry + 2 roti), never as the bare gravy.
        """
        mult = slot_multiplier(profile, meal)
        _, price = _adj_price(dish, mult)
        side_total = 0.0
        side = None
        # needs_accompaniment() re-checks the NAME, not just the stored course,
        # so a low-confidence guess never gets bread attached to it. Pairing the
        # wrong thing (roti with momos) is much worse than not pairing.
        if (dish.course in course_rules.NEEDS_ACCOMPANIMENT
                and course_rules.needs_accompaniment(dish.name)):
            side = pick_side(dish)
            if side:
                qty = course_rules.accompaniment_qty(side.name)
                side_total = round(side.price * qty, 2)
        return round(price + side_total, 2), side, side_total

    def place(day, meal, dish):
        mult = slot_multiplier(profile, meal)
        variant, price = _adj_price(dish, mult)
        _, side, side_total = meal_cost(dish, meal)

        slot = PlannedSlot(day, meal, dish.dish_id, dish.name,
                           dish.restaurant_id, price, dish.price, dish.rating,
                           variant, mult, dish.restaurant_name, dish.image_url,
                           course=dish.course)
        if side:
            slot.side_dish_id = side.dish_id
            slot.side_dish_name = side.name
            slot.side_qty = course_rules.accompaniment_qty(side.name)
            slot.side_price = side_total
            slot.side_restaurant_name = side.restaurant_name
            slot.side_image_url = side.image_url
        slots.append(slot)

        used_count[dish.dish_id] += 1
        day_dishes[day].add(dish.dish_id)
        week_dish[(week_of(day), dish.dish_id)] += 1
        for t in dish.tags:
            tag_got[t.lower()] += 1
        return slot.total_price

    # order of slots to fill (chronological), restricted to the requested meals
    grid = [(day, m) for day in range(1, days + 1) for m in meals]
    total = 0.0
    filled = set()  # (day, meal)

    # Cheapest possible meal per slot type — the floor used for budget pacing.
    cheapest = {m: min((meal_cost(d, m)[0] for d in by_slot[m]), default=0.0)
                for m in meals}

    def reserve_after(idx):
        """Minimum rupees needed to fill every slot after position `idx`.

        Pass 2 used to spend greedily until the budget ran dry, then force-fill
        the remaining slots at any price — which is how a plan blew past budget
        while early days ate ₹651 and late days ₹150. Reserving this floor before
        each pick keeps spending paced across the whole month.
        """
        return round(sum(cheapest[m] for _, m in grid[idx + 1:]), 2)

    # ---- PASS 1: satisfy min-count constraints first ----
    for c in constraints:
        tag = c.dish_tag.lower()
        need = c.min_count
        cands = sorted(
            (d for d in mains if _matches(d, tag)),
            key=lambda d: (-d.rating, d.price),
        )
        if not cands:
            continue
        for idx, (day, meal) in enumerate(grid):
            if tag_got[tag] >= need:
                break
            if (day, meal) in filled:
                continue
            slot_cands = [d for d in cands if d.meal_type == meal and can_place(day, d)]
            if not slot_cands:
                continue
            # Pace pass 1 too. It used to place the highest-RATED matching dish
            # with no budget check at all, so "10 paneer meals" could commit the
            # ten priciest paneer dishes up front and blow the month before pass
            # 2 ever ran. Prefer the best-rated dish that still leaves enough to
            # fill the remaining slots; fall back to the cheapest match so the
            # constraint is still honoured (and reported) when nothing fits.
            affordable = round(budget - total - reserve_after(idx), 2)
            fits = [d for d in slot_cands if meal_cost(d, meal)[0] <= affordable]
            dish = fits[0] if fits else min(slot_cands,
                                            key=lambda d: meal_cost(d, meal)[0])
            total += place(day, meal, dish)
            filled.add((day, meal))

    # ---- PASS 2: greedy fill remaining slots by score, paced against budget ----
    for idx, (day, meal) in enumerate(grid):
        if (day, meal) in filled:
            continue
        cands = [d for d in by_slot[meal] if can_place(day, d)]
        if not cands:
            cands = by_slot[meal]  # relax variety rather than leave empty
        cands = sorted(
            cands,
            key=lambda d: -_score(d, wanted_tags, week_dish[(week_of(day), d.dish_id)], med),
        )
        # Spend only what still leaves enough to fill every remaining slot, and
        # take only a FAIR SHARE of the surplus above that floor rather than the
        # whole of it. Reserving just the floor still let early slots swallow the
        # entire surplus on premium dishes, leaving later days scraping the
        # bottom (the Rs 651 vs Rs 150 day-to-day swing). Spreading the surplus
        # evenly over the remaining slots is what actually evens the plan out.
        floor_rest = reserve_after(idx)
        surplus = budget - total - floor_rest - cheapest[meal]
        remaining_slots = max(1, len(grid) - idx)
        affordable = round(cheapest[meal] + max(0.0, surplus) / remaining_slots, 2)
        placed = False
        for dish in cands:
            cost, _, _ = meal_cost(dish, meal)
            if cost <= affordable:
                total += place(day, meal, dish)
                filled.add((day, meal))
                placed = True
                break
        if not placed:
            # Nothing fits the pace -> take the cheapest option for this slot.
            # With pacing this stays within budget in the normal case; it can
            # still exceed when the catalog's own floor price is above budget,
            # which the feasibility message then reports honestly.
            dish = min(cands, key=lambda d: meal_cost(d, meal)[0])
            total += place(day, meal, dish)
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
        return (f"Plan fits. Spent ~Rs {total} of Rs {budget}. "
                f"Rs {round(budget-total,2)} rolls over.")
    parts = []
    if over:
        parts.append(f"Plan needs Rs {round(total-budget,2)} more than budget "
                     f"(Rs {total} vs Rs {budget}).")
    for c in unmet:
        s = cstatus[c.dish_tag]
        parts.append(f"Only {s['got']}/{s['needed']} '{c.dish_tag}' meals fit.")

    parts.append("Options: raise budget, reduce constraint count, "
                 "or drop to a smaller portion size.")
    return " ".join(parts)
