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
from itertools import accumulate
from math import ceil
from statistics import median
from appetite import slot_multiplier, component_plan, AppetiteProfile
from catalog import Dish, variant_price
import course as course_rules
from optimizer_pairing import _add_pairings

MEAL_TYPES = ("breakfast", "lunch", "dinner")


@dataclass
class Constraint:
    dish_tag: str          # matches Dish.tags substring, e.g. "paneer"
    min_count: int
    # NEW: pairing constraints for desserts/drinks with specific meal slots
    dish_kind: str = ""    # "sweet", "snack", "beverage" for pairing constraints
    slot_type: str = ""    # "breakfast", "lunch", "dinner" - which meal(s) to pair with
    frequency: str = ""    # "always" = every occurrence, "optional" = when budget allows


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
    pairing_dish_id: str = ""  # NEW: optional dessert/drink paired with this meal
    pairing_cost: float = 0.0  # NEW: cost of the pairing item
    restaurant_name: str = ""
    image_url: str = ""
    # --- composition (see course.py) ---
    # A curry is not a meal by itself; it carries a bread/rice accompaniment.
    # `price` stays the main dish alone so existing callers keep working;
    # `total_price` is what the meal actually costs and is what the budget,
    # wallet, and UI must use.
    course: str = "complete"
    dish_kind: str = "meal"
    side_dish_id: str = ""
    side_dish_name: str = ""
    side_qty: int = 0
    side_price: float = 0.0       # qty * unit price, already multiplied
    side_restaurant_name: str = ""
    side_image_url: str = ""
    side2_dish_id: str = ""
    side2_dish_name: str = ""
    side2_qty: int = 0
    side2_price: float = 0.0
    side2_restaurant_name: str = ""
    side2_image_url: str = ""
    # Source of the side/side2 entry when it is a PAIRING (dessert/drink) rather
    # than a composed accompaniment (bread/rice): "" = restaurant accompaniment
    # or pairing, "instamart" = grocery item from Swiggy Instamart. Lets the UI
    # badge grocery pairings and lets flows that assume restaurant dishes (the
    # order executor) treat them as display-only.
    side_source: str = ""
    side2_source: str = ""

    @property
    def total_price(self) -> float:
        """Full cost of this meal — main dish plus any accompaniment."""
        return round(self.price + self.side_price + self.side2_price, 2)


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
# Whole-month repeat penalty. The live catalog near a user can be small (a
# dozen-ish dishes per meal), so the per-week cap alone still let the optimizer
# hammer the same top-rated few dishes 20+ times a month. Charging a growing
# penalty for EVERY prior use forces rotation through the whole pool.
W_TOTAL_REPEAT_PENALTY = 0.75
# Rating floor for MAINS. Dishes below this are the "PO Poha" (2.0) /
# "Lemon Fish" (1.9) problem — planned as recurring meals only because they
# are cheap. Pairing stock (breads/rice) is EXEMPT so a curry is never left
# breadless just because the roti is rated 2.9.
MIN_RATING = 3.0
# Sliding-scale recency penalty. This is what breaks the fixed cycles the
# 1-day "fresh" filter could not — with a small pool, remembering only
# yesterday let least-used-first rotation loop with a short period (real
# plan: Day 1 == Day 3 == Day 8 == Day 10, identical menus). Full penalty
# right after a use, decaying linearly to zero RECENT_WINDOW days later.
RECENT_WINDOW = 10
W_RECENT_PENALTY = 2.6
# An accompaniment may never cost more than this fraction of its curry's main.
# The live plan served "Masala Curry" Rs75 with Rs90 of rumali roti — sauce that
# costs more than the food it accompanies. Above the ratio we simply serve the
# curry unpaired rather than a worse meal than no pairing at all.
SIDE_COST_RATIO = 0.9
# How many times the SAME full-day menu (every meal slot's dish identical) may
# recur across the month. Recency penalties and monthly caps rotate DISHES, but
# greedy scoring can still quietly reassemble the same combination on distant
# days (live symptom: Day 1 == Day 8 == Day 22, byte-identical menus). A menu
# you liked twice is variety; three times is a loop.
# CRITICAL FIX: The guards below demote-not-ban via `prior_copies >= MAX` —
# with MAX=0 every completing pick flags (>=0 is always true), making the
# whole-day variety guard a silent no-op. The flag must fire only on a
# would-be (MAX+1)-th copy, so 2 means: a menu may appear at most twice,
# a 3rd copy is demoted behind fresher alternatives. User reported
# "some dishes repeated aloot" (whole-day menus cloning 3+ times).
MAX_IDENTICAL_DAY_MENUS = 2

# Exponential recency penalty multiplier - penalizes recent dish use heavily
EXPONENTIAL_RECENCY_BASE = 1.8


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


def _score(dish: Dish, wanted_tags, repeats: int, med: float,
           total_repeats: int = 0, days_since=None) -> float:
    rating_term = W_RATING * dish.rating
    constraint_bonus = W_CONSTRAINT if any(_matches(dish, t) for t in wanted_tags) else 0
    repeat_pen = W_REPEAT_PENALTY * repeats + W_TOTAL_REPEAT_PENALTY * total_repeats
    score = rating_term + _price_term(dish.price, med) + constraint_bonus - repeat_pen
    # Recent-use penalty on top: full weight the day after a use, fading to
    # nothing RECENT_WINDOW days out (see RECENT_WINDOW above).
    if days_since is not None and 0 <= days_since <= RECENT_WINDOW:
        score -= W_RECENT_PENALTY * (RECENT_WINDOW - days_since + 1) / RECENT_WINDOW
    elif days_since is not None and days_since <= 2 * RECENT_WINDOW:
        # A quarter-strength tail through a SECOND window. The hard zero at
        # exactly RECENT_WINDOW synchronised with the weekly repeat-cap reset:
        # the same high-rated dish came back on a ~weekly cycle and whole day
        # menus re-formed identically three-plus times a month.
        score -= (W_RECENT_PENALTY * 0.25
                  * (2 * RECENT_WINDOW - days_since) / RECENT_WINDOW)
    return score


def optimize(
    catalog,
    profile: AppetiteProfile,
    budget: float,
    days: int = 30,
    constraints=None,
    veg_only: bool = False,
    max_repeat_per_week: int = 2,
    meals=None,
    variety_guards: bool = True,
    extra_pairing_dishes=None,
    taste_profile=None,
) -> PlanResult:
    """Build a plan over `days` x `meals`.

    meals: which slots to plan, e.g. ["breakfast","lunch"]. Defaults to all
    three. This is the user's `meals` blueprint field — previously accepted by
    the chat layer and then silently ignored here, so asking for two meals
    still produced (and charged for) three.

    variety_guards: the whole-day anti-repeat disciplines (day-menu signature
    ceiling, consecutive-day cap). Pass False when probing the CHEAPEST
    possible month (feasibility floors): those guards are preferences that
    legitimately cost rupees on small catalogs, and a floor that pays a
    variety premium stops being a floor.
    """
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ValueError(f"days must be a whole number >= 1, got {days!r}")
    req = tuple(meals) if meals is not None else MEAL_TYPES
    if not req:
        # An explicitly-empty list used to fall through to "all three" — asking
        # for nothing got everything (and was budgeted for it).
        raise ValueError("pick at least one meal to plan")
    unknown = [m for m in req if m not in MEAL_TYPES]
    if unknown:
        raise ValueError(f"unknown meal(s): {', '.join(unknown)}")
    constraints = constraints or []
    meals = tuple(m for m in MEAL_TYPES if m in req)
    pool = [d for d in catalog if (not veg_only or d.veg)]

    # Split the pool by role. Only dishes that can headline a meal are eligible
    # for a slot; breads and rice are held aside as pairing stock.
    #
    # The stored course is trusted for breads/staples/sides (it may have come
    # from description or LLM enrichment, which a name-only re-check can't see).
    # COMPLETE dishes get one extra gate — standalone_meal() is price-aware: an
    # UNRECOGNISED name defaults to "complete", and that default is how a ₹19
    # salan and a ₹20 roasted egg got planned as whole dinners. Anything below
    # the meal floor is dropped unless the rules confidently know what it is.
    #
    # CRITICAL FIX: dish_kind MUST be KIND_MEAL. "Chena Toast" was classified as
    # course=complete + kind=sweet, passing the old filter but landing a dessert
    # in lunch slots. The kind gate is absolute: sweets/snacks/beverages are
    # NEVER mains regardless of course value.
    from food_classifier import FoodInfo
    def _meal_eligible(d):
        """A dish may headline a meal slot only if it's kind=meal AND the
        food-knowledge layer doesn't explicitly forbid it. The course-rule gates
        below already block most non-meals; this is the extra guard for items the
        name-rules got wrong (e.g. a Chhena Toast that course.py defaulted to
        COMPLETE)."""
        return (d.dish_kind == course_rules.KIND_MEAL
                and getattr(d, "main_meal_eligible", True))

    mains = [d for d in pool
             if _meal_eligible(d)
             and d.course not in course_rules.NEVER_STANDALONE
             and (d.course != course_rules.COMPLETE
                  or course_rules.standalone_meal(d.name, d.price))
             and d.rating >= MIN_RATING]
    sides = [d for d in pool if d.course in course_rules.ACCOMPANIMENT]

    by_slot = {m: [d for d in mains if d.meal_type == m] for m in meals}
    for m in meals:
        if not by_slot[m]:
            # The floor is per-meal, not global: if it emptied a slot, relax
            # it for THIS meal only — same course gates, no rating filter. A
            # neighbourhood where everything is under 3 stars still has to eat.
            relaxed = [d for d in pool
                       if _meal_eligible(d)
                       and d.course not in course_rules.NEVER_STANDALONE
                       and (d.course != course_rules.COMPLETE
                            or course_rules.standalone_meal(d.name, d.price))
                       and d.meal_type == m]
            # Even the relaxed path keeps an ABSOLUTE floor: the live plan once
            # served "Lemon Fish" (rated 1.9) eight times because a thin fetch
            # dropped every >=3.0 dish and this branch reinstated everything.
            by_slot[m] = ([d for d in relaxed if d.rating >= 2.5] or relaxed)
        if not by_slot[m]:
            return PlanResult(False, message=f"No dishes for {m} in catalog")

    # Widen thin pools: breakfast foods are distinct, but lunch and dinner draw
    # from the same universe — a paneer curry works at either. When one slot's
    # pool comes up thin (partial catalog fetch, aggressive diet filter), share
    # the other's mains rather than cycle five dishes across thirty days.
    MIN_POOL_SIZE = 8
    non_breakfast = [m for m in meals if m != "breakfast"]
    merged_pool = {}
    for m in non_breakfast:
        for d in by_slot[m]:
            merged_pool.setdefault(d.dish_id, d)
    widened = list(merged_pool.values())
    for m in non_breakfast:
        if len(by_slot[m]) < MIN_POOL_SIZE and len(widened) > len(by_slot[m]):
            by_slot[m] = list(widened)

    # Pool median drives the price term. Computed over mains only — including
    # ₹10 breads would drag the median down and re-introduce the old bias.
    med = median([d.price for d in mains]) if mains else 0.0

    # Pairing constraints carry an EMPTY dish_tag — "" is a substring of
    # everything, so including them here would give every dish the constraint
    # bonus. Tag-driven logic below must only see real must-have tags.
    wanted_tags = [c.dish_tag for c in constraints if c.dish_tag]
    slots = []                      # PlannedSlot
    used_count = defaultdict(int)   # dish_id -> times used (whole month)
    last_used = {}                  # dish_id -> most recent day placed
    day_dishes = defaultdict(set)   # day -> set(dish_id)  (per-day variety)
    week_dish = defaultdict(int)    # (week, dish_id) -> count
    tag_got = defaultdict(int)
    side_used = defaultdict(int)    # side dish_id -> times paired (bread rotation)
    caps = {}                       # dish_id -> whole-month use ceiling

    def week_of(day):
        return (day - 1) // 7

    def can_place(day, dish):
        if dish.dish_id in day_dishes[day]:
            return False
        if week_dish[(week_of(day), dish.dish_id)] >= max_repeat_per_week:
            return False
        cap = caps.get(dish.dish_id)
        if cap is not None and used_count[dish.dish_id] >= cap:
            return False
        return True

    def pick_side(dish, main_price):
        """Cheapest-TOTAL bread/rice for this curry, capped against its price.

        Two fixes over the old version, both straight off the live plan:
        1. Ranked by TOTAL cost (price x qty), not unit price. Rumali Roti
           Rs40x2=Rs80 beat Butter Naan Rs55x1 on unit price alone and the
           meal paid Rs25 extra for the worse pairing.
        2. The accompaniment never out-costs the main: "Masala Curry" Rs75 +
           Rs90 of rumali roti was the plan's worst dinner. Above
           SIDE_COST_RATIO the curry ships unpaired instead.
        Same-restaurant first (Swiggy carts are per-restaurant); if their stock
        is only expensive, another restaurant's affordable bread beats none —
        the old code already crossed restaurants when the restaurant had NONE,
        this just widens that escape hatch to "none they didn't gouge on".
        """
        if not sides:
            return None

        def total(s):
            return s.price * course_rules.accompaniment_qty(s.name)

        limit = main_price * SIDE_COST_RATIO
        # Cheapest TOTAL first; prior-use count only breaks ties between
        # equal-cost breads, so variety never buys a worse pairing.
        same = sorted((s for s in sides if s.restaurant_id == dish.restaurant_id),
                      key=lambda s: (total(s), side_used[s.dish_id]))
        if same and total(same[0]) <= limit:
            return same[0]
        wider = sorted((s for s in sides if s.restaurant_id != dish.restaurant_id),
                       key=lambda s: (total(s), side_used[s.dish_id]))
        if wider and total(wider[0]) <= limit:
            return wider[0]
        return None

    def _pick_second_side(dish, main_price, first_side, first_total):
        """Pick a second accompaniment of the OPPOSITE course (bread vs staple).

        Only used when appetite wants an extra component (heavy). The combined
        cost of both sides must still respect SIDE_COST_RATIO — if the second
        bread would push the meal past that ceiling it is skipped entirely.
        """
        if not sides or not first_side:
            return None
        limit = main_price * SIDE_COST_RATIO
        remaining = limit - first_total
        if remaining <= 0:
            return None
        try:
            first_course = first_side.course
        except AttributeError:
            first_course = course_rules.course_of(first_side.name)
        wanted = course_rules.STAPLE if first_course == course_rules.BREAD else course_rules.BREAD

        def total(s):
            return s.price * course_rules.accompaniment_qty(s.name)

        # Candidates must be the wanted course and fit the remaining budget
        same_candidates = sorted(
            (s for s in sides
             if s.course == wanted
             and s.dish_id != first_side.dish_id
             and total(s) <= remaining
             and s.restaurant_id == dish.restaurant_id),
            key=lambda s: (total(s), side_used[s.dish_id]))
        if same_candidates:
            return same_candidates[0]
        wider = sorted(
            (s for s in sides
             if s.course == wanted
             and s.dish_id != first_side.dish_id
             and total(s) <= remaining
             and s.restaurant_id != dish.restaurant_id),
            key=lambda s: (total(s), side_used[s.dish_id]))
        if wider:
            return wider[0]
        # Fallback: any fitting candidate regardless of restaurant dichotomy
        any_fit = sorted(
            (s for s in sides
             if s.course == wanted
             and s.dish_id != first_side.dish_id
             and total(s) <= remaining),
            key=lambda s: (total(s), side_used[s.dish_id]))
        if any_fit:
            return any_fit[0]
        return None

    def meal_cost(dish, meal, mult=None):
        """Full cost of planning `dish` at `meal`, accompaniment included.

        Every budget decision goes through this, so a curry is always costed as
        the real meal (curry + 2 roti), never as the bare gravy. `mult=None`
        sizes the portion from the user's appetite profile; an explicit
        multiplier (e.g. 1.0 = REGULAR portion) lets the budget fallbacks relax
        the appetite premium instead of blowing past the budget.

        Appetite drives COMPONENT COUNT, not dish choice:
        - light      -> curry served alone, no sides
        - moderate   -> curry + 1 side (current behaviour)
        - heavy      -> curry + 2 sides (bread + staple) if within SIDE_COST_RATIO
        Complete dishes (thali/combo/biryani etc, course==COMPLETE) never get
        sides regardless of appetite — they are already a meal.
        """
        if mult is None:
            mult = slot_multiplier(profile, meal)
        _, price = _adj_price(dish, mult)
        # Thali/combo/complete meals never get sides — they are already whole.
        if dish.course == course_rules.COMPLETE:
            return round(price, 2), None, 0.0, None, 0.0
        # Appetite decides whether curries get paired at all
        pair_curry, extra = component_plan(profile, meal)
        if not pair_curry:
            return round(price, 2), None, 0.0, None, 0.0
        side_total = 0.0
        side = None
        side2 = None
        side2_total = 0.0
        # needs_accompaniment() re-checks the NAME, not just the stored course,
        # so a low-confidence guess never gets bread attached to it. Pairing the
        # wrong thing (roti with momos) is much worse than not pairing.
        # Also guard that complete dishes never pair (already returned above).
        if (dish.course in course_rules.NEEDS_ACCOMPANIMENT
                and course_rules.needs_accompaniment(dish.name)
                and dish.course != course_rules.COMPLETE):
            side = pick_side(dish, price)
            if side:
                qty = course_rules.accompaniment_qty(side.name)
                side_total = round(side.price * qty, 2)
                if extra:
                    side2 = _pick_second_side(dish, price, side, side_total)
                    if side2:
                        qty2 = course_rules.accompaniment_qty(side2.name)
                        side2_total = round(side2.price * qty2, 2)
                        if side_total + side2_total > price * SIDE_COST_RATIO:
                            side2 = None
                            side2_total = 0.0
        return round(price + side_total + side2_total, 2), side, side_total, side2, side2_total

    def place(day, meal, dish, mult=None):
        if mult is None:
            mult = slot_multiplier(profile, meal)
        variant, price = _adj_price(dish, mult)
        # Cost the meal at the SAME multiplier that sizes the main — passing
        # None here re-derived the appetite premium and could disagree with
        # `price` when a fallback explicitly downsized the portion.
        _, side, side_total, side2, side2_total = meal_cost(dish, meal, mult)

        slot = PlannedSlot(day, meal, dish.dish_id, dish.name,
                           dish.restaurant_id, price, dish.price, dish.rating,
                           variant, mult,
                           restaurant_name=dish.restaurant_name,
                           image_url=dish.image_url,
                           course=dish.course, dish_kind=dish.dish_kind)
        if side:
            slot.side_dish_id = side.dish_id
            slot.side_dish_name = side.name
            slot.side_qty = course_rules.accompaniment_qty(side.name)
            slot.side_price = side_total
            slot.side_restaurant_name = side.restaurant_name
            slot.side_image_url = side.image_url
            side_used[side.dish_id] += 1
        if side2:
            slot.side2_dish_id = side2.dish_id
            slot.side2_dish_name = side2.name
            slot.side2_qty = course_rules.accompaniment_qty(side2.name)
            slot.side2_price = side2_total
            slot.side2_restaurant_name = side2.restaurant_name
            slot.side2_image_url = side2.image_url
            side_used[side2.dish_id] += 1
        slots.append(slot)

        used_count[dish.dish_id] += 1
        last_used[dish.dish_id] = day
        day_dishes[day].add(dish.dish_id)
        week_dish[(week_of(day), dish.dish_id)] += 1
        for t in dish.tags:
            tag_got[t.lower()] += 1
        return slot.total_price

    # order of slots to fill (chronological), restricted to the requested meals
    grid = [(day, m) for day in range(1, days + 1) for m in meals]
    total = 0.0
    filled = set()  # (day, meal)

    # ---- whole-month repeat ceiling -----------------------------------------
    # max_repeat_per_week resets every week, so a favourite could legally
    # appear ~8x/month — and did (Veg Dum Biryani Bowl x9). Cap each dish at
    # its fair share of the month plus one, measured against the FULL slot
    # pool. The old math keyed the cap to the AFFORDABLE slice (dishes under
    # ~1.3x the per-slot fair share): under a heavy appetite that slice came
    # out EMPTY, the guarded division exploded the cap to days+1, and nothing
    # ever bound — one dish was served 9-14 times. With the portion/rating
    # relaxation in pass 2's fallback every pooled dish is genuinely reachable,
    # so capping against the whole pool both binds correctly and stays safe.
    #
    # WIDENED POOLS COUNT THEIR REAL DEMAND. Thin lunch/dinner pools are merged
    # above (MIN_POOL_SIZE), so len(by_slot[m])) looks like 10 while the shared
    # pool must actually fill SIXTY slots — capping each dish at ceil(30/10)+1=4
    # promised 40 fills for 60 slots, the under-cap preference ran dry mid-
    # month, and the relaxation branch hammered one standout 9 times. Meals
    # drawing on the SAME pool therefore multiply the demand side.
    pool_groups = {}                # frozenset(dish_ids) -> meals sharing it
    for m in meals:
        key = frozenset(d.dish_id for d in by_slot[m])
        pool_groups.setdefault(key, []).append(m)
    for members, sharing in pool_groups.items():
        cap = max(3, ceil(days * len(sharing) / max(1, len(members))) + 1)
        for did in members:
            caps[did] = max(caps.get(did, 0), cap)
    # Constraint-pass candidates outside any slot pool get the loose ceiling,
    # so an explicit user request ("10 paneer meals") is never blocked by it.
    _default_cap = max(3, ceil(days / 5) + 1)
    for d in mains:
        caps.setdefault(d.dish_id, _default_cap)

    # Cheapest possible meal per slot type — the floor used for budget pacing.
    cheapest = {m: min((meal_cost(d, m)[0] for d in by_slot[m]), default=0.0)
                for m in meals}

    # Cost LADDERS: the honest version of that floor. "Every future slot can
    # sit at the single cheapest dish" is fiction once monthly caps exist — a
    # Rs64 Chena Toast may headline only 3 dinners, so dinners 4..30 must climb
    # the price ladder no matter how disciplined the planner is. Each ladder is
    # the dish costs of one slot type, every cost repeated at most its monthly
    # cap times, sorted, with running totals; entry N-1 is a TRUE lower bound
    # on what N slots of that type can cost. Reserving this instead of the raw
    # minimum is what stops pass 1 from spending a small catalog's whole surplus
    # in week one and starving the rest of the month.
    cost_ladder = {}
    for m in meals:
        entries = []
        for d in by_slot[m]:
            c = meal_cost(d, m)[0]
            entries.extend([c] * max(1, caps.get(d.dish_id, 1)))
        entries.sort()
        cost_ladder[m] = list(accumulate(entries))

    # Rating-relaxed reserves for the budget ladder: when nothing at or above
    # MIN_RATING fits what's left of the budget, these sub-floor dishes are a
    # cheaper way to keep a slot filled than blowing past the budget. Money is
    # the hard constraint; rating bends first, appetite portions bend next.
    emergency_pool = {}
    for m in meals:
        base_ids = {d.dish_id for d in by_slot[m]}
        emergency_pool[m] = [
            d for d in pool
            if d.meal_type == m and d.dish_id not in base_ids
            and d.dish_kind == course_rules.KIND_MEAL
            and d.course not in course_rules.NEVER_STANDALONE
            and (d.course != course_rules.COMPLETE
                 or course_rules.standalone_meal(d.name, d.price))]

    def reserve_others(idx):
        """Minimum rupees needed to fill every UNFILLED slot except `idx`.

        Pass 2 used to spend greedily until the budget ran dry, then force-fill
        the remaining slots at any price — which is how a plan blew past budget
        while early days ate ₹651 and late days ₹150. Reserving this floor
        before each pick keeps spending paced across the whole month.

        Two honesty fixes over the versions that came before:
        - It covers every UNFILLED slot in the grid, not just the ones after
          the current position: pass 1 spreads its forced picks across the
          month, leaving unfilled slots on BOTH sides, and pass 1 itself must
          pace too.
        - It reads the CAP-AWARE cost ladder (see cost_ladder above), not the
          raw per-slot minimum. Reserving "29 more dinners at Rs64" when the
          Rs64 dish may legally headline only 3 of them let early slots spend
          money the back of the month never had.
        """
        counts = defaultdict(int)
        for j, (dd, mm) in enumerate(grid):
            if j != idx and (dd, mm) not in filled:
                counts[mm] += 1
        # Blend the cap-aware ladder TOTAL with the naive minimum TOTAL: pure
        # ladders starved mid-month variety (every slot fell through to cheap
        # fills), while reserving only n*cheapest invited the early-month
        # splurge. Both sides are whole-meal-slot totals — averaging a
        # cumulative ladder entry and then multiplying by n again (the old
        # arithmetic) overstated the reserve ~n/2-fold, drove `room` negative
        # from day two, and pushed every fill down the cheapest-first escape
        # hatch, synchronising identical day menus across the month.
        reserved = 0.0
        for mm, n in counts.items():
            ladder = cost_ladder[mm]
            ladder_total = ladder[min(n, len(ladder)) - 1] if n else 0.0
            reserved += (ladder_total + cheapest[mm] * n) / 2
        return round(reserved, 2)

    # Completed-day menu signatures: sorted (meal_type, dish_id) pairs. Caps and
    # recency rotate individual dishes, yet their daily COMBINATION can still
    # loop — track finished menus so selection can prefer alternatives before a
    # third copy locks in.
    sig_counts = defaultdict(int)

    def note_completion(day):
        """Record today's menu signature once all its meal slots are filled."""
        if variety_guards and all((day, m) in filled for m in meals):
            sig = tuple(sorted((s.meal_type, s.dish_id)
                               for s in slots if s.day == day))
            sig_counts[sig] += 1

    def would_complete(day, meal):
        """True when filling (day, meal) completes that day's menu."""
        return all(m == meal or (day, m) in filled for m in meals)

    def prior_copies(day, meal, dish_id):
        """How many past days match the menu this pick would complete.

        Nonzero only when the pick fills the day's LAST open slot; partial days
        have no signature yet, so mid-day picks are never penalised.
        """
        if not would_complete(day, meal):
            return 0
        hyp = tuple(sorted([(s.meal_type, s.dish_id)
                            for s in slots if s.day == day]
                           + [(meal, dish_id)]))
        return sig_counts[hyp]

    # Variant-aware identity: "Rajma Chawal" and "Rajma Chawal [Mini]" carry
    # different dish_ids but are the same food to the person eating them, so
    # consecutive-day rules must compare FAMILIES (name minus bracketed size /
    # portion tags), not raw ids.
    fam = {d.dish_id: d.name.split("[")[0].strip().lower() for d in pool}

    # ---- PASS 1: satisfy min-count constraints first ----
    # The forced picks keep three disciplines the live plan had none of:
    #   SPREAD — "10 paneer meals" went to the first grid positions and made
    #     Day 1 == Day 2 exactly (three paneer meals a day, back to back).
    #     Target positions are now spaced evenly across the month.
    #   ROTATE — candidates are preferred by recency exactly like pass 2's
    #     scoring; Rs881 Lababdar twice in a row is rotation failure even when
    #     each pick was individually "affordable".
    #   PACING — every placement keeps total + reserve_others(idx) <= budget.
    #     The old fallback placed the cheapest match at ANY price once nothing
    #     fit, committing the whole month before pass 2 ever ran. When even a
    #     REGULAR portion cannot fit what's left, the slot is left for pass 2
    #     and the shortfall is reported honestly instead.
    for c in constraints:
        if not c.dish_tag:
            continue  # pairing constraints (desserts/drinks) are PASS 4's job
        tag = c.dish_tag.lower()
        need = c.min_count - tag_got[tag]
        cands_c = sorted(
            (d for d in mains if _matches(d, tag)),
            key=lambda d: (-d.rating, d.price),
        )
        if need <= 0 or not cands_c:
            continue

        elig = [i for i, (day, meal) in enumerate(grid)
                if (day, meal) not in filled
                and any(x.meal_type == meal for x in cands_c)]
        if not elig:
            continue

        # Evenly spaced target positions across the eligible grid; walk outward
        # from each target when it collides with a slot already chosen.
        k = len(elig)
        step = k / min(need, k)
        preferred, taken = [], set()
        for j in range(min(need, k)):
            t = int(round(j * step))
            for off in range(k):
                for p in (t + off, t - off):
                    if 0 <= p < k and p not in taken:
                        taken.add(p)
                        preferred.append(elig[p])
                        break
                else:
                    continue
                break
        order = preferred + [i for i in elig if i not in taken]

        for idx in order:
            if tag_got[tag] >= c.min_count:
                break
            day, meal = grid[idx]

            def staleness(x, day=day):
                lu = last_used.get(x.dish_id)
                return (RECENT_WINDOW if lu is None
                        else min(RECENT_WINDOW, day - lu))

            slot_cands = [x for x in cands_c
                          if x.meal_type == meal and can_place(day, x)]
            ranked = [x for x in slot_cands if staleness(x) >= 2] or slot_cands
            if not ranked:
                continue
            room = round(budget - total - reserve_others(idx), 2)
            # Among the fresh candidates prefer the CHEAPEST fit (rating only
            # breaks ties): picking best-rated-first here is how "10 paneer
            # meals" committed the priciest paneer dishes up front and ate the
            # whole month's surplus before pass 2 ever ran. Staleness still
            # dominates, so rotation is never sacrificed for price.
            fits = [x for x in ranked if meal_cost(x, meal)[0] <= room]
            if fits:
                dish = min(fits, key=lambda x: (-staleness(x), x.price,
                                                -x.rating))
                total += place(day, meal, dish)
                filled.add((day, meal))
                note_completion(day)
                continue
            # Nothing fits at this appetite's portions — drop to a REGULAR
            # size before giving up on the constraint for this slot.
            reg_fits = [x for x in ranked if meal_cost(x, meal, 1.0)[0] <= room]
            if reg_fits:
                dish = min(reg_fits,
                           key=lambda x: (-staleness(x),
                                          meal_cost(x, meal, 1.0)[0],
                                          -x.rating))
                total += place(day, meal, dish, mult=1.0)
                filled.add((day, meal))
                note_completion(day)
            # else: leave the slot to pass 2. An unmet constraint with an
            # honest message beats a plan that silently overshot the budget.

    # ---- PASS 2: greedy fill remaining slots by score, paced against budget ----
    for idx, (day, meal) in enumerate(grid):
        if (day, meal) in filled:
            continue
        cands = [d for d in by_slot[meal] if can_place(day, d)]
        if not cands:
            # Relax variety rather than leave the slot empty — but rotate by
            # least-used-first so a small catalog doesn't hammer the same
            # top-rated dish every single time the cap is hit. Dishes still
            # UNDER their monthly ceiling are preferred here too: with the
            # stricter whole-pool caps this branch fires far more often, and
            # blindly ignoring the caps re-opened the "same dish nine times"
            # door through the back of the house.
            pool_m = by_slot[meal]
            under_cap = [d for d in pool_m
                         if caps.get(d.dish_id) is None
                         or used_count[d.dish_id] < caps[d.dish_id]]
            cands = sorted(under_cap or pool_m,
                           key=lambda d: used_count[d.dish_id])
        # Consecutive-day variety: prefer dishes NOT served yesterday. This is a
        # soft constraint — the live catalog near a user can be small (a handful
        # of dishes per meal), so a hard ban could leave a slot unfillable. Relax
        # to the full candidate list only when nothing fresh fits. day_dishes is
        # filled chronologically, so day-1 is already complete by the time we
        # plan day; day_dishes[0] is an empty set, so day 1 is unconstrained.
        fresh = [d for d in cands if d.dish_id not in day_dishes[day - 1]]
        if fresh:
            cands = fresh
        # Consecutive-day CAP, not just preference: the fresh filter above
        # works per-slot, but a tight pace can still clone yesterday one meal
        # at a time (breakfast falls back, then lunch falls back -> two shared
        # mains plus their usual side). Once today ALREADY shares a dish with
        # yesterday, hard-ban the rest of yesterday's menu whenever any other
        # candidate exists — one shared item is a coincidence, three is a
        # reheated day.
        yest = day_dishes.get(day - 1) or set()
        if variety_guards and yest and len(day_dishes[day] & yest) >= 1:
            yest_fams = {fam[i] for i in yest}
            tight = [d for d in cands if fam[d.dish_id] not in yest_fams]
            if tight:
                cands = tight
        cands = sorted(
            cands,
            key=lambda d: -_score(d, wanted_tags, week_dish[(week_of(day), d.dish_id)],
                                  med, used_count[d.dish_id],
                                  (day - last_used[d.dish_id]) if d.dish_id in last_used else None),
        )
        # Whole-day variety: when THIS pick would complete today's menu, push
        # options whose full menu has already happened MAX_IDENTICAL_DAY_MENUS
        # times behind fresher ones. Stable sort keeps score order otherwise,
        # and the affordability checks below are untouched — worst case (every
        # option is a repeat) falls through exactly as before.
        if variety_guards and would_complete(day, meal):
            cands = sorted(
                cands,
                key=lambda d: prior_copies(day, meal, d.dish_id)
                >= MAX_IDENTICAL_DAY_MENUS)
        # Spend only what still leaves enough to fill every other unfilled slot,
        # and take only a FAIR SHARE of the surplus above that floor rather than
        # the whole of it. Reserving just the floor still let early slots swallow
        # the entire surplus on premium dishes, leaving later days scraping the
        # bottom (the Rs 651 vs Rs 150 day-to-day swing). Spreading the surplus
        # evenly over the remaining slots is what actually evens the plan out.
        room = round(budget - total - reserve_others(idx), 2)
        surplus = room - cheapest[meal]
        remaining_slots = max(1, len(grid) - idx)
        affordable = round(cheapest[meal] + max(0.0, surplus) / remaining_slots, 2)
        placed = False
        for dish in cands:
            cost, _, _, _, _ = meal_cost(dish, meal)
            if cost <= affordable:
                total += place(day, meal, dish)
                filled.add((day, meal))
                note_completion(day)
                placed = True
                break
        if not placed:
            # Graceful degradation, money first. Nothing scored fit the pace:
            # try a smaller REGULAR portion of a well-scored dish before
            # touching the rating-relaxed reserve — cost-ranking the whole pool
            # (the old escape hatch) is how tight budgets homogenized menus
            # onto the same few cheapest dishes and dragged sub-3.0 fillers in.
            for dish in cands:
                if meal_cost(dish, meal, 1.0)[0] <= room:
                    total += place(day, meal, dish, mult=1.0)
                    filled.add((day, meal))
                    note_completion(day)
                    placed = True
                    break
        if not placed:
            # Last resort: the rating-relaxed emergency reserve, preferring
            # options that respect the monthly cap and were not served
            # yesterday. Only when even the cheapest possible fill cannot fit
            # what remains does the plan go over budget — and then the final
            # message says so honestly. The old fallback just took "the
            # cheapest option" at full appetite price with no room check at
            # all, which is where a +35% month came from.
            yest = day_dishes.get(day - 1, set())
            opts = [d for d in cands if d.rating >= MIN_RATING]
            if not opts:
                opts = list(cands)
            have = {x.dish_id for x in opts}
            # Sub-floor dishes are a LAST resort even here: rated options that
            # fit any portion always beat a cheap 2.5-star filler.
            if not any(x.rating >= MIN_RATING for x in opts):
                opts += [x for x in emergency_pool[meal]
                         if x.dish_id not in have]
            else:
                rated_em = [x for x in emergency_pool[meal]
                            if x.dish_id not in have
                            and x.rating >= MIN_RATING]
                opts += rated_em

            def rank(x):
                cost = min(meal_cost(x, meal)[0], meal_cost(x, meal, 1.0)[0])
                cap_hit = (caps.get(x.dish_id) is not None
                           and used_count[x.dish_id] >= caps[x.dish_id])
                # Freshest and least-used FIRST, cost last: a starved month
                # used to converge on one cheapest triple and serve the
                # identical menu four times over.
                lu = last_used.get(x.dish_id)
                stale = (RECENT_WINDOW if lu is None
                         else min(RECENT_WINDOW, day - lu))
                return (0 if cost <= room else 1,
                        1 if cap_hit else 0,
                        1 if prior_copies(day, meal, x.dish_id)
                        >= MAX_IDENTICAL_DAY_MENUS else 0,
                        -stale,
                        used_count[x.dish_id],
                        cost)

            opts.sort(key=rank)
            # Monthly caps outrank even a perfect room fit here: an at-cap
            # dish may only be taken when EVERY option for this slot is at
            # its ceiling, else small pools drift +2 past the fair share.
            uncapped = [x for x in opts if caps.get(x.dish_id) is None
                        or used_count[x.dish_id] < caps[x.dish_id]]
            pool_for_pick = uncapped or opts
            safe = [x for x in pool_for_pick
                    if x.dish_id not in day_dishes[day]
                    and week_dish[(week_of(day), x.dish_id)] < max_repeat_per_week]
            if variety_guards and safe:
                yf = {fam[x] for x in yest}
                nf = [x for x in safe if fam[x.dish_id] not in yf]
                if nf:
                    safe = nf
            dish = (safe or pool_for_pick)[0]
            cost_full = meal_cost(dish, meal)[0]
            cost_reg = meal_cost(dish, meal, 1.0)[0]
            if cost_full <= room or cost_full <= cost_reg:
                total += place(day, meal, dish)
            else:
                total += place(day, meal, dish, mult=1.0)
            filled.add((day, meal))
            note_completion(day)

    # ---- PASS 3: repair sweep -------------------------------------------------
    # The ladders pace spending, but they are a lower bound: recency and weekly
    # limits can still force a pricier pick late in the month. When the plan
    # lands over budget anyway, repair it instead of shipping the overrun —
    # downgrade premium portions to REGULAR first (no variety impact), then
    # swap expensive mains for cheaper ones. A slot holding up a min-count
    # constraint is only touched by a replacement that carries the same tag,
    # or when the count has spare room. Money is the hard constraint; rating
    # and portion size bend before it does.
    if total > budget:
        # Repair mutates slots directly, so rebuild the menu-signature counts
        # from the CURRENT plan — the repair sweep must obey the same whole-day
        # variety ceiling pass 2 does, or it quietly rebuilds duplicate menus
        # while hunting for savings.
        if variety_guards:
            sig_counts.clear()
            per_day = defaultdict(list)
            for s in slots:
                per_day[s.day].append((s.meal_type, s.dish_id))
            for d, items in per_day.items():
                if len(items) == len(meals):
                    sig_counts[tuple(sorted(items))] += 1
        dish_by_id = {d.dish_id: d for d in pool}

        def _unplace(slot):
            nonlocal total
            total -= slot.total_price
            # Retire the day's signature first: removing this slot may leave
            # the day incomplete, and a stale count would mislead the swap
            # guard below.
            day_slots = [x for x in slots if x.day == slot.day]
            if len(day_slots) == len(meals):
                sig_counts[tuple(sorted((x.meal_type, x.dish_id)
                                        for x in day_slots))] -= 1
            slots.remove(slot)
            filled.discard((slot.day, slot.meal_type))
            used_count[slot.dish_id] -= 1
            day_dishes[slot.day].discard(slot.dish_id)
            week_dish[(week_of(slot.day), slot.dish_id)] -= 1
            for t in dish_by_id[slot.dish_id].tags:
                tag_got[t.lower()] -= 1
            if slot.side_dish_id:
                side_used[slot.side_dish_id] -= 1
            if slot.side2_dish_id:
                side_used[slot.side2_dish_id] -= 1

        def _can_free(dish):
            # Freeing this slot must not drop any satisfied constraint below
            # its minimum (a same-tag replacement is checked separately).
            # Pairing constraints (empty dish_tag) aren't tag-counted — "" would
            # match every dish and freeze the whole budget-repair pass.
            return all(not c.dish_tag
                       or not _matches(dish, c.dish_tag)
                       or tag_got[c.dish_tag.lower()] > c.min_count
                       for c in constraints)

        for _sweep in range(2):
            if total <= budget:
                break
            # 1) portion downgrades, priciest slots first
            for slot in sorted(slots, key=lambda s: -s.total_price):
                if total <= budget:
                    break
                if slot.portion_mult > 1.0:
                    reg_variant, reg_price = _adj_price(
                        dish_by_id[slot.dish_id], 1.0)
                    saved = round(slot.price - reg_price, 2)
                    if saved > 0:
                        slot.variant = reg_variant
                        slot.price = reg_price
                        slot.portion_mult = 1.0
                        total = round(total - saved, 2)
            # 2) main-dish swaps, priciest slots first; among candidates take
            # the most expensive one that still saves money, so quality gives
            # up only what the budget actually needs.
            for slot in sorted(slots, key=lambda s: -s.total_price):
                if total <= budget:
                    break
                cur = dish_by_id[slot.dish_id]
                if not _can_free(cur):
                    continue
                _unplace(slot)
                yest_set = day_dishes.get(slot.day - 1) or set()
                yest_fams = {fam[i] for i in yest_set}
                best = None
                best_key = None
                for cand in by_slot.get(slot.meal_type, []):
                    if cand.dish_id == cur.dish_id:
                        continue
                    if not can_place(slot.day, cand):
                        continue
                    cost = meal_cost(cand, slot.meal_type, 1.0)[0]
                    if cost >= slot.total_price:
                        continue
                    # honour every tag this slot was carrying (pairing
                    # constraints have no tag to carry — skip them)
                    if not all(not c.dish_tag
                               or _matches(cand, c.dish_tag)
                               or not _matches(cur, c.dish_tag)
                               or tag_got[c.dish_tag.lower()] >= c.min_count
                               for c in constraints):
                        continue
                    # Rotate while repairing: the freshest, least-used cheaper
                    # dish wins, price only breaks ties. Picking the priciest
                    # saving option (the previous rule) pulled every repaired
                    # day onto the same standout trio.
                    lu = last_used.get(cand.dish_id)
                    stale = (RECENT_WINDOW if lu is None
                             else min(RECENT_WINDOW, slot.day - lu))
                    key = (
                        # Whole-day variety outranks even freshness here:
                        # repairs that complete a third copy of an existing
                        # menu are how a saved month still looked cloned.
                        # Max-selection key, so the guard flags are 0 = banned
                        # tier, 1 = free tier: a repeat candidate only wins
                        # when no fresher saver exists.
                        0 if prior_copies(slot.day, slot.meal_type,
                                          cand.dish_id)
                        >= MAX_IDENTICAL_DAY_MENUS else 1,
                        # Same discipline against ADJACENT days: a repair that
                        # drops yesterday's curry back into today re-heats two
                        # days at once, side pairing included. Compared by
                        # FAMILY, not raw id — "Sambar Rice" and its [Mini]
                        # variant are the same food to the person eating them.
                        0 if (variety_guards
                              and fam[cand.dish_id] in yest_fams) else 1,
                        stale, -used_count[cand.dish_id], cost)
                    if best_key is None or key > best_key:
                        best, best_key = cand, key
                if best is not None:
                    total = round(total + place(slot.day, slot.meal_type,
                                                best, mult=1.0), 2)
                else:
                    # nothing cheaper fits — restore the original pick exactly
                    total = round(total + place(slot.day, slot.meal_type,
                                                cur, mult=slot.portion_mult), 2)
                note_completion(slot.day)

    total = round(total, 2)
    cstatus = {c.dish_tag: {"got": tag_got[c.dish_tag.lower()], "needed": c.min_count}
               for c in constraints if c.dish_tag}  # Only regular tag constraints
    unmet = [c for c in constraints
             if c.dish_tag and tag_got[c.dish_tag.lower()] < c.min_count]
    over = total > budget

    feasible = (not over) and (not unmet)
    msg = _feasibility_message(over, unmet, total, budget, cstatus)

    # PASS 4: Add pairings (desserts/drinks) for slots with pairing constraints.
    # extra_pairing_dishes (Instamart groceries) are merged into the pairing
    # pool ONLY — they never join `pool`, so they can't leak into the main
    # placement, bread rotation, or budget-repair passes.
    pairing_constraints = [c for c in constraints if c.dish_kind and c.slot_type]
    if pairing_constraints:
        total = _add_pairings(slots, pairing_constraints, pool, budget, total,
                              profile, extra_pairing_dishes,
                              taste_profile=taste_profile)
        total = round(total, 2)
        # Recalculate feasibility after pairings
        over = total > budget
        feasible = (not over) and (not unmet)
        if over:
            msg = (f"Plan with pairings needs Rs {round(total-budget,2)} more "
                   f"(Rs {total} vs Rs {budget}). Options: raise budget or skip pairings.")
        else:
            msg = (f"Plan fits with pairings. Spent ~Rs {total} of Rs {budget}. "
                   f"Rs {round(budget-total,2)} rolls over.")

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
