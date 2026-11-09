"""Why a budget doesn't fit, and what would actually make it fit.

The optimizer already reports a shortfall ("needs Rs 8159 more"), but the advice
attached to it was generic - "raise budget, reduce constraint count, or drop to
a smaller portion size" - with no numbers behind it. A user reading that has no
way to know whether Rs 12,000 would work, or whether dropping dinner is enough.

This module answers that concretely: it re-runs the deterministic optimizer over
the realistic combinations of the three levers a user actually controls, and
reports which ones land inside the budget and what each would cost.

Cheap to do, because the optimizer is fast and deterministic - probing a dozen
scenarios is a dozen sorts, not a dozen LLM calls.

Levers, in the order users find them acceptable:
  1. budget      raise it to the real floor
  2. meals       skip a meal slot (usually dinner)
  3. appetite    smaller portions
"""
from optimizer import optimize, Constraint, MEAL_TYPES

APPETITE_ORDER = ("light", "moderate", "heavy", "very_heavy")

# Meal-set combinations worth suggesting, most complete first. Dropping
# breakfast is unusual, so lunch+dinner is offered before lunch-only.
MEAL_COMBOS = (
    ("breakfast", "lunch", "dinner"),
    ("breakfast", "lunch"),
    ("lunch", "dinner"),
    ("lunch",),
)

_MEAL_LABEL = {
    ("breakfast", "lunch", "dinner"): "all three meals",
    ("breakfast", "lunch"): "breakfast + lunch",
    ("lunch", "dinner"): "lunch + dinner",
    ("lunch",): "lunch only",
}


def _floor_cost(catalog, profile, days, meals, constraints, veg_only=False,
                taste_profile=None):
    """Cheapest achievable total for this configuration, constraints honoured.

    Two requirements shape this probe, both learned from live failures:

    1. The planner probed must behave EXACTLY like /plan. Running it at
       budget=1 makes every pacing decision fall through to "take the cheapest
       thing", which diverged from real behavior and quoted "minimum Rs 10,501"
       for a request whose real plan cost Rs 13,560. So the budget escalates
       until the optimizer's own output fits inside it AND meets every
       min-count constraint.
    2. A stall (neither the constraint count nor the cost moving between
       escalations) only means "impossible" when the plan ALREADY FITS its
       budget. Below the true floor the opposite happens: the pacing reserves
       freeze the total near the cheap minimum while the constraint stays
       starved, and reading that as a stall quoted Rs 7,600 for plans that
       genuinely need Rs 8,400 -- a floor no real run could honour.

    The first succeeding budget is found by geometric escalation, so it can
    overshoot; a short binary refinement walks it back down. What is returned
    is the smallest VERIFIED-SUFFICIENT budget: calling /plan with exactly this
    number fits inside it and meets every min-count constraint.
    """
    def attempt(b):
        r = optimize(catalog, profile, b, days=days,
                     constraints=constraints, meals=list(meals),
                     veg_only=veg_only, taste_profile=taste_profile)
        # Guards stay ON deliberately: the quoted floor must be one a REAL
        # plan (variety disciplines included) can honour, or /plan at exactly
        # this budget would still come back over.
        ok = (r.total_cost <= b + 0.01
              and all(s["got"] >= s["needed"]
                      for s in r.constraint_status.values()))
        return r, ok

    budget = 1.0
    result, ok = attempt(budget)
    low = 0.0                     # highest budget known to FAIL
    sufficient = None             # lowest budget known to WORK
    prev_got = prev_total = None
    stall_rounds = 0
    for _ in range(12):
        if ok:
            sufficient = budget
            break
        low = max(low, budget)
        got = sum(s["got"] for s in result.constraint_status.values())
        if (prev_got is not None and got == prev_got
                and abs(result.total_cost - prev_total) < 0.01):
            stall_rounds += 1
        else:
            stall_rounds = 0
        prev_got, prev_total = got, result.total_cost
        # A single frozen round below the floor is NORMAL: the pacing reserves
        # hold the total at the cheap minimum while the constraint waits for
        # real money. Only a stall that SURVIVES another full escalation --
        # budget grown well past the plan, constraint still unmoved -- means
        # more money cannot help (e.g. nothing matches the tag).
        if stall_rounds >= 2 and result.total_cost <= budget + 0.01:
            break
        budget = max(result.total_cost, budget * 1.35) + 1.0
        result, ok = attempt(budget)

    if result is None:
        return 0.0
    if sufficient is not None:
        # Binary refinement: the escalation overshot, so pull the budget back
        # toward the highest known-failing point while it keeps working.
        # What we quote is this smallest VERIFIED-SUFFICIENT budget — not the
        # cheaper total the planner happened to spend once — because quoting
        # the total invited "run /plan at exactly this number" and a tighter
        # budget re-starves the constraint (got dropped from 10 to 1).
        high = sufficient
        for _ in range(6):
            mid = round((low + high) / 2, 2)
            if mid <= low or mid >= high:
                break
            r_mid, ok_mid = attempt(mid)
            if ok_mid:
                high, sufficient, result = mid, mid, r_mid
            else:
                low = mid
        return round(sufficient, 2)
    return round(result.total_cost, 2)


def analyse(catalog, profile_builder, user_id, appetite_level, budget, days,
            constraints=None, meals=None, veg_only=False, taste_profile=None):
    """Probe the levers and return concrete, numbered options.

    profile_builder: appetite.build_profile - injected so this module stays
    free of the appetite cache and is trivially testable.

    Returns a dict shaped for direct rendering:
      {
        "feasible": bool,
        "budget": float,
        "floor": float,              # cheapest possible for what was ASKED for
        "shortfall": float,          # 0 when feasible
        "current": {...},            # the requested configuration
        "options": [ {...}, ... ],   # ways to make it fit, best first
        "headline": str,             # one plain-language sentence
      }
    """
    constraints = constraints or []
    meals = tuple(m for m in MEAL_TYPES if m in (meals or MEAL_TYPES)) or MEAL_TYPES
    # Same normalization as /plan — a bare string from an LLM blueprint would
    # otherwise be handed to the optimizer as a Constraint and blow up on
    # `.dish_tag`.
    cons = []
    for c in constraints:
        if isinstance(c, Constraint):
            cons.append(c)
        elif isinstance(c, dict):
            # Pairing constraints (dish_kind/slot_type, empty tag) carry the
            # pairing fields; must-have dishes carry only tag + count.
            kind = str(c.get("dish_kind") or "").strip()
            slot = str(c.get("slot_type") or "").strip()
            tag = str(c.get("dish_tag") or "").strip().lower()
            if not tag and not (kind and slot):
                continue
            try:
                count = max(1, int(c.get("min_count") or 1))
            except (TypeError, ValueError):
                count = 1
            cons.append(Constraint(
                tag, 0 if (kind and slot) else count,
                dish_kind=kind, slot_type=slot,
                frequency=str(c.get("frequency") or "").strip()))
        elif isinstance(c, str) and c.strip():
            cons.append(Constraint(c.strip().lower(), 1))

    prof = profile_builder(user_id, appetite_level)
    floor = _floor_cost(catalog, prof, days, meals, cons, veg_only=veg_only,
                        taste_profile=taste_profile)
    slot_count = days * len(meals)
    shortfall = round(max(0.0, floor - budget), 2)
    feasible = floor <= budget

    current = {
        "appetite": appetite_level,
        "meals": list(meals),
        "meals_label": _MEAL_LABEL.get(tuple(meals), " + ".join(meals)),
        "slots": slot_count,
        "floor": floor,
        "per_meal": round(floor / slot_count, 2) if slot_count else 0.0,
    }

    options = []

    # --- Lever 1: the budget that would actually work, as asked -----------
    if not feasible:
        options.append({
            "kind": "budget",
            "label": f"Raise budget to Rs {int(round(floor))}",
            "detail": (f"Keeps {current['meals_label']} at {appetite_level} "
                       f"appetite - {slot_count} meals."),
            "total": floor,
            "fits": True,
            "changes": {"budget": int(round(floor))},
        })

    # --- Levers 2 + 3: fewer meals and/or smaller portions ----------------
    # Only suggest changes that are a genuine reduction from what was asked.
    ai = APPETITE_ORDER.index(appetite_level) if appetite_level in APPETITE_ORDER else 2
    seen = set()
    for combo in MEAL_COMBOS:
        if len(combo) > len(meals):
            continue  # never suggest ADDING a meal to fix an overrun
        for lvl in APPETITE_ORDER[:ai + 1]:
            if combo == tuple(meals) and lvl == appetite_level:
                continue  # that's the current config, not an option
            key = (combo, lvl)
            if key in seen:
                continue
            seen.add(key)

            cost = _floor_cost(catalog, profile_builder(user_id, lvl), days,
                               combo, cons, veg_only=veg_only,
                               taste_profile=taste_profile)
            if cost > budget:
                continue  # doesn't actually solve anything

            changed = []
            if combo != tuple(meals):
                changed.append(_MEAL_LABEL.get(combo, " + ".join(combo)))
            if lvl != appetite_level:
                changed.append(f"{lvl} portions")
            options.append({
                "kind": "config",
                "label": " + ".join(changed).capitalize(),
                "detail": (f"{days * len(combo)} meals at {lvl} appetite "
                           f"- about Rs {int(round(cost / (days * len(combo))))} "
                           f"per meal."),
                "total": cost,
                "fits": True,
                "changes": {"meals": list(combo), "appetite_level": lvl},
            })

    # Least-disruptive first. The budget option leads when present (it changes
    # nothing about the food), then options that keep the most meals, then the
    # ones closest to the appetite originally asked for. Cost breaks ties -
    # it is deliberately the LAST key, because the cheapest option is usually
    # the most drastic one (lunch only), and leading with that reads as though
    # the planner is trying to talk the user out of eating.
    def rank(o):
        ch = o.get("changes", {})
        kept = len(ch.get("meals", meals))
        lvl = ch.get("appetite_level", appetite_level)
        drop = ai - (APPETITE_ORDER.index(lvl) if lvl in APPETITE_ORDER else ai)
        return (o["kind"] != "budget", -kept, drop, o["total"])

    options.sort(key=rank)

    return {
        "feasible": feasible,
        "budget": budget,
        "floor": floor,
        "shortfall": shortfall,
        "current": current,
        "options": options[:4],
        "headline": _headline(feasible, budget, floor, shortfall, current),
    }


def _headline(feasible, budget, floor, shortfall, current):
    """One plain sentence explaining the situation in the user's own terms."""
    if feasible:
        return (f"Rs {int(budget)} covers {current['slots']} meals "
                f"({current['meals_label']}, {current['appetite']} appetite).")
    return (
        f"Rs {int(budget)} won't cover {current['slots']} meals here. "
        f"The cheapest options near you work out to about "
        f"Rs {int(current['per_meal'])} a meal, so {current['meals_label']} at "
        f"{current['appetite']} appetite needs at least Rs {int(round(floor))} "
        f"a month - Rs {int(round(shortfall))} more than you set."
    )
