"""Swap Engine (Docs section 8 'other' branch).

Given a slot the user rejected, return alternatives in the same meal type within
a ± price band, preserving the user's portion multiplier (Docs section 4 note:
swap must respect appetite, not just price).

Quality parity with the optimizer: /alternatives used to offer the very dishes
the planner is forbidden to plan — sub-3.0 fillers, bare rotis, ₹19 salans — so
the user's escape hatch could lead somewhere worse than the original pick. The
same gates as optimizer's mains filter (MIN_RATING, NEVER_STANDALONE, the
price-aware standalone check for COMPLETE dishes) now run here, and dishes the
rest of the plan already leans on are demoted, so a swap rotates variety into
neighbours instead of re-concentrating it on the next-best regular.

apply_swap() owns the persistence half: it validates the client's chosen dish
against the catalog before trusting any of its fields, refuses bare
breads/staples/sides posted as a whole meal, re-pairs a swapped-in curry with
an affordable accompaniment (mirroring optimizer.pick_side rather than wiping
the old pairing), and recomputes the plan's total_cost/feasible so the approve
guard stops running on stale money numbers.
"""
from collections import defaultdict

from catalog import variant_price
import course as course_rules
from course import KIND_MEAL
from optimizer import MIN_RATING, SIDE_COST_RATIO

# Demotion per prior appearance elsewhere in the plan, expressed as extra
# distance from the target price. Half a rupee per use: a dish served ten
# times loses to a comparable neighbour four rupees farther out, while a
# single prior use barely registers.
REPETITION_PENALTY = 0.5

# Slack for float-comparing a client-posted swap against the catalog.
_PRICE_TOL = 0.05
_RATING_TOL = 0.05


def alternatives(slot, catalog, profile_mult=1.0, band=100, veg_only=False,
                 limit=5, used_counts=None):
    """slot: dict with meal_type, dish_id, price. Returns ranked alt dishes.

    used_counts: optional {dish_id-or-name: n} counting how often each dish
    already appears in the plan. Every prior use adds REPETITION_PENALTY to a
    candidate's effective distance from the target price, so hammered dishes
    sink behind equally-close neighbours.
    """
    meal_type = slot["meal_type"]
    target = slot["price"]
    cur_id = slot["dish_id"]
    used = used_counts or {}

    def times_used(d):
        # Callers may key by dish_id, name, or record both per slot (app.py
        # does); max() counts each plan occurrence once however it was built.
        return max(used.get(d.dish_id, 0), used.get(d.name, 0))

    def course_of_dish(d):
        return getattr(d, "course", "") or course_rules.COMPLETE

    cands = []
    for d in catalog:
        if d.meal_type != meal_type or d.dish_id == cur_id:
            continue
        if veg_only and not d.veg:
            continue
        # --- quality gates: exactly the optimizer's mains filter ---
        # KIND gate first so sweets/snacks never reach price band.
        if getattr(d, "dish_kind", "meal") != KIND_MEAL:
            continue
        if d.rating < MIN_RATING:
            continue
        c = course_of_dish(d)
        if c in course_rules.NEVER_STANDALONE:
            continue
        if c == course_rules.COMPLETE and not course_rules.standalone_meal(d.name, d.price):
            continue
        variant, price = variant_price(d, profile_mult)
        if abs(price - target) <= band:
            cands.append({
                "dish_id": d.dish_id,
                "name": d.name,
                "restaurant_id": d.restaurant_id,
                "restaurant_name": d.restaurant_name,
                "image_url": getattr(d, "image_url", ""),
                "price": price,
                "variant": variant,
                "rating": d.rating,
                "veg": d.veg,
                # rank metric kept internal; stripped before returning
                "_eff_dist": abs(price - target) + REPETITION_PENALTY * times_used(d),
            })
    # rank: closest to target price after the repetition penalty; higher
    # rating breaks ties between equally-distant candidates.
    cands.sort(key=lambda c: (c["_eff_dist"], -c["rating"]))
    return [{k: v for k, v in c.items() if k != "_eff_dist"}
            for c in cands[:limit]]


# ---------- swap persistence --------------------------------------------------

class SwapError(ValueError):
    """Client-fixable rejection; the /swap endpoint maps it to HTTP 400."""


def _close(a, b, tol):
    try:
        return abs(float(a) - float(b)) <= tol + 1e-9
    except (TypeError, ValueError):
        return False


def match_catalog_dish(body, catalog, profile_mult=1.0):
    """Locate the posted dish in the catalog and verify its fields agree.

    SwapIn used to be trusted blindly: whatever name/price a client posted was
    written straight into the slot. Now the dish_id must exist in the catalog
    AND the echoed name/price/rating must match it — price compared after the
    same portion adjustment /alternatives displayed, ratings with a small
    float slack. Anything else is "Unknown dish": there is no honest way to
    order a dish the catalog doesn't sell at that price.
    """
    did = str(body.get("dish_id", ""))
    sent_name = str(body.get("name") or "").strip().casefold()
    for d in catalog:
        if str(d.dish_id) != did:
            continue
        _, adj_price = variant_price(d, profile_mult)
        if (sent_name == str(d.name or "").strip().casefold()
                and _close(body.get("price"), adj_price, _PRICE_TOL)
                and _close(body.get("rating", d.rating), d.rating, _RATING_TOL)):
            return d
        raise SwapError("Unknown dish")
    raise SwapError("Unknown dish")


def require_standalone(dish):
    """Refuse bare bread/staple/side (and below-meal-price guesses) as a MAIN.

    Same gate the optimizer applies before a dish may occupy a slot; without
    it a client could post "Tawa Roti" as an entire dinner.
    """
    if getattr(dish, "dish_kind", "meal") != KIND_MEAL:
        raise SwapError(f"{dish.name} can't be a meal on its own")
    c = getattr(dish, "course", "") or course_rules.course_of(dish.name)
    if (c in course_rules.NEVER_STANDALONE
            or (c == course_rules.COMPLETE
                and not course_rules.standalone_meal(dish.name, dish.price))):
        raise SwapError(f"{dish.name} can't be a meal on its own")


def pick_side(dish, main_price, catalog, side_used=None):
    """Cheapest-TOTAL bread/rice for a swapped-in curry — mirrors
    optimizer.pick_side: ranked by price x accompaniment qty, never costing
    more than SIDE_COST_RATIO x the main, same restaurant first with the
    wider catalog as escape hatch, ties broken toward less-used pairings.

    NOTE: optimizer supports a heavy-appetite second accompaniment (side2) via
    appetite component_plan, but swaps currently re-pair only a SINGLE side.
    The extra side is not added here; future work can extend this to pick a
    second side when needed. For now every swap clears side2_* columns."""
    sides = [d for d in catalog
             if (getattr(d, "course", "") or course_rules.course_of(d.name))
             in course_rules.ACCOMPANIMENT]
    if not sides:
        return None
    used = side_used or {}

    def total(s):
        return s.price * course_rules.accompaniment_qty(s.name)

    limit = main_price * SIDE_COST_RATIO
    same = sorted((s for s in sides if s.restaurant_id == dish.restaurant_id),
                  key=lambda s: (total(s), used.get(s.dish_id, 0)))
    if same and total(same[0]) <= limit:
        return same[0]
    wider = sorted((s for s in sides if s.restaurant_id != dish.restaurant_id),
                   key=lambda s: (total(s), used.get(s.dish_id, 0)))
    if wider and total(wider[0]) <= limit:
        return wider[0]
    return None


def _side_usage(conn, plan_id, exclude_slot_id=None):
    """How many of the plan's other slots already pair each side (rotation)."""
    used = defaultdict(int)
    q = ("SELECT side_dish_id FROM meal_slots "
         "WHERE plan_id=? AND side_dish_id IS NOT NULL AND side_dish_id<>''")
    args = [plan_id]
    if exclude_slot_id is not None:
        q += " AND id<>?"
        args.append(exclude_slot_id)
    for r in conn.execute(q, args):
        used[r["side_dish_id"]] += 1
    return used


def _has_side2(conn):
    """True if meal_slots has side2 columns (newer DBs). Guards old DBs."""
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(meal_slots)").fetchall()]
        return "side2_price" in cols
    except Exception:
        return False


def recompute_plan_totals(conn, plan_id):
    """Refresh plans.total_cost / feasible from the slot rows (bug H3).

    A swap changes what its meal costs, but the plans row kept the original
    total, so /approve kept gating on a number nothing ever updated. Sum main
    + side (+ side2 when present) over every slot and re-derive feasibility
    against the budget. Returns the new total as float and updates
    plans.feasible correctly.
    """
    # side2-aware sum with guard for old DBs that lack the column
    try:
        if _has_side2(conn):
            row = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(price,0)+COALESCE(side_price,0)"
                "+COALESCE(side2_price,0)),0) AS tc "
                "FROM meal_slots WHERE plan_id=?", (plan_id,)).fetchone()
        else:
            row = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(price,0)+COALESCE(side_price,0)),0) AS tc "
                "FROM meal_slots WHERE plan_id=?", (plan_id,)).fetchone()
    except Exception:
        # pragma race or missing column — fallback to price+side_price
        row = conn.execute(
            "SELECT COALESCE(SUM(COALESCE(price,0)+COALESCE(side_price,0)),0) AS tc "
            "FROM meal_slots WHERE plan_id=?", (plan_id,)).fetchone()
    total = round(float(row["tc"] or 0.0), 2)
    plan = conn.execute("SELECT budget FROM plans WHERE id=?",
                        (plan_id,)).fetchone()
    if plan:
        conn.execute("UPDATE plans SET total_cost=?, feasible=? WHERE id=?",
                     (total, 1 if total <= plan["budget"] else 0, plan_id))
    return total


def apply_swap(conn, slot, body, catalog, profile_mult=1.0):
    """Validate + persist a swap, re-pair the side, refresh plan totals.

    slot: the current meal_slots row. body: dict with the SwapIn fields.
    Returns the updated slot as a dict. Raises SwapError on unknown dishes
    and bare breads (client-fixable, mapped to 400 upstream).
    """
    slot_id = slot["id"]
    dish = match_catalog_dish(body, catalog, profile_mult)
    require_standalone(dish)

    course = getattr(dish, "course", "") or course_rules.course_of(dish.name)
    dish_kind = getattr(dish, "dish_kind", "meal")
    # Bug H2: a swapped-in curry used to lose its bread forever because the
    # old pairing was simply wiped. Pair it the way the optimizer would;
    # dishes that travel without a side (and curries with no affordable one —
    # mirroring the optimizer's ship-unpaired rule) still get cleared.
    # Explicit complete-skip mirrors optimizer thali combo fix: a thali/biryani
    # (course==complete) never gets a side even if NEEDS_ACCOMPANIMENT somehow
    # matched, and require_standalone already rejected non-meal kinds.
    side = None
    if (course in course_rules.NEEDS_ACCOMPANIMENT
            and course_rules.needs_accompaniment(dish.name)
            and course != course_rules.COMPLETE):
        side = pick_side(dish, float(body["price"]), catalog,
                         side_used=_side_usage(conn, slot["plan_id"], slot_id))

    has_s2 = _has_side2(conn)
    if side:
        qty = course_rules.accompaniment_qty(side.name)
        side_total = round(side.price * qty, 2)
        if has_s2:
            conn.execute(
                "UPDATE meal_slots SET dish_id=?, dish_name=?, restaurant_id=?, "
                "restaurant_name=?, image_url=?, price=?, rating=?, variant=?, "
                "why_text=NULL, course=?, dish_kind=?, side_dish_id=?, side_dish_name=?, "
                "side_qty=?, side_price=?, side_restaurant_name=?, "
                "side_image_url=?, side2_dish_id='', side2_dish_name='', "
                "side2_qty=0, side2_price=0, side2_restaurant_name='', "
                "side2_image_url='' WHERE id=?",
                (dish.dish_id, dish.name, dish.restaurant_id, dish.restaurant_name,
                 body.get("image_url", ""), body["price"], body["rating"],
                 body.get("variant", "regular"), course, dish_kind,
                 side.dish_id, side.name, qty, side_total,
                 side.restaurant_name, getattr(side, "image_url", ""), slot_id))
        else:
            conn.execute(
                "UPDATE meal_slots SET dish_id=?, dish_name=?, restaurant_id=?, "
                "restaurant_name=?, image_url=?, price=?, rating=?, variant=?, "
                "why_text=NULL, course=?, dish_kind=?, side_dish_id=?, side_dish_name=?, "
                "side_qty=?, side_price=?, side_restaurant_name=?, "
                "side_image_url=? WHERE id=?",
                (dish.dish_id, dish.name, dish.restaurant_id, dish.restaurant_name,
                 body.get("image_url", ""), body["price"], body["rating"],
                 body.get("variant", "regular"), course, dish_kind,
                 side.dish_id, side.name, qty, side_total,
                 side.restaurant_name, getattr(side, "image_url", ""), slot_id))
    else:
        if has_s2:
            conn.execute(
                "UPDATE meal_slots SET dish_id=?, dish_name=?, restaurant_id=?, "
                "restaurant_name=?, image_url=?, price=?, rating=?, variant=?, "
                "why_text=NULL, course=?, dish_kind=?, side_dish_id='', side_dish_name='', "
                "side_qty=0, side_price=0, side_restaurant_name='', "
                "side_image_url='', side2_dish_id='', side2_dish_name='', "
                "side2_qty=0, side2_price=0, side2_restaurant_name='', "
                "side2_image_url='' WHERE id=?",
                (dish.dish_id, dish.name, dish.restaurant_id, dish.restaurant_name,
                 body.get("image_url", ""), body["price"], body["rating"],
                 body.get("variant", "regular"), course, dish_kind, slot_id))
        else:
            conn.execute(
                "UPDATE meal_slots SET dish_id=?, dish_name=?, restaurant_id=?, "
                "restaurant_name=?, image_url=?, price=?, rating=?, variant=?, "
                "why_text=NULL, course=?, dish_kind=?, side_dish_id='', side_dish_name='', "
                "side_qty=0, side_price=0, side_restaurant_name='', "
                "side_image_url='' WHERE id=?",
                (dish.dish_id, dish.name, dish.restaurant_id, dish.restaurant_name,
                 body.get("image_url", ""), body["price"], body["rating"],
                 body.get("variant", "regular"), course, dish_kind, slot_id))

    recompute_plan_totals(conn, slot["plan_id"])
    conn.commit()
    row = conn.execute("SELECT * FROM meal_slots WHERE id=?",
                       (slot_id,)).fetchone()
    return dict(row)
