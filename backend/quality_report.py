"""Quality metrics report for a meal plan.

Usage:
    python quality_report.py [plan_id]

Defaults to the latest plan id when no argument is given. Prints a
human-readable quality report (repetition, duplicate day menus, consecutive
day overlap, side-dish economics, rating quality, cost distribution) and a
final one-line SCORECARD suitable for diffing before/after fixes.

Stdlib only.
"""

import sqlite3
import sys
from collections import Counter, defaultdict

DB_PATH = "mealplanner.db"

MEAL_ORDER = {"breakfast": 0, "lunch": 1, "dinner": 2, "snacks": 3}


def warn(msg):
    print(f"[warn] {msg} -- skipping metric")


def has_columns(cur, table, cols):
    cur.execute(f"PRAGMA table_info({table})")
    present = {row[1] for row in cur.fetchall()}
    return all(c in present for c in cols)


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def median(xs):
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ---- resolve plan id -------------------------------------------------
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        if arg is not None:
            plan_id = int(arg)
        else:
            row = cur.execute("select max(id) from plans").fetchone()
            if row is None or row[0] is None:
                print("No plans found in database.")
                return
            plan_id = int(row[0])
    except ValueError:
        print(f"Invalid plan id: {arg!r}")
        return

    slots = []
    try:
        slots = cur.execute(
            "select * from meal_slots where plan_id = ? order by day, meal_type",
            (plan_id,),
        ).fetchall()
    except sqlite3.Error as e:
        warn(f"cannot read meal_slots ({e})")
    if not slots and arg is None:
        print("Latest plan has no slots; nothing to report.")
        return

    # ---- 1. header -------------------------------------------------------
    print("=" * 70)
    print(f"QUALITY REPORT -- plan {plan_id}")
    print("=" * 70)
    if has_columns(cur, "plans", ["month"]):
        cols = ["month", "budget", "total_cost", "feasible", "created_at"]
        have = [c for c in cols if c in {r[1] for r in cur.execute("PRAGMA table_info(plans)")}]
        prow = cur.execute(
            f"select {', '.join(have)} from plans where id = ?", (plan_id,)
        ).fetchone()
        if prow is None:
            print(f"Plan row not found in plans table.")
            return
        keys = prow.keys()
        month = prow["month"] if "month" in keys else "?"
        budget = prow["budget"] if "budget" in keys else None
        total = prow["total_cost"] if "total_cost" in keys else None
        feasible = prow["feasible"] if "feasible" in keys else None
        created = prow["created_at"] if "created_at" in keys else "?"
        print(f"month      : {month}")
        print(f"budget     : {budget if budget is not None else '?'}")
        print(f"total_cost : {total if total is not None else '?'}")
        print(f"feasible   : {bool(feasible)}" if feasible is not None else "feasible   : ?")
        print(f"created_at : {created}")
    else:
        warn("plans table missing expected columns")

    if not slots:
        warn("no meal_slots rows for this plan")
        return

    def g(slot, name, default=None):
        v = slot[name] if name in slot.keys() else default
        return default if v is None and default is not None else v

    days = defaultdict(list)          # day -> slots
    per_meal = defaultdict(list)      # meal_type -> slots
    for s in slots:
        days[s["day"]].append(s)
        per_meal[s["meal_type"]].append(s)

    # ---- 2. repetition ---------------------------------------------------
    print()
    print("-" * 70)
    print("REPETITION -- top dishes across the plan")
    print("-" * 70)
    dish_counts = Counter()
    dish_meal = defaultdict(Counter)   # (dish, restaurant) -> meal_type -> count
    for s in slots:
        name = s["dish_name"] or s["dish_id"]
        rest = s["restaurant_name"] or "?"
        key = (name, rest)
        dish_counts[key] += 1
        dish_meal[key][s["meal_type"]] += 1

    top15 = dish_counts.most_common(15)
    for (name, rest), cnt in top15:
        mt = max(dish_meal[(name, rest)].items(), key=lambda kv: kv[1])[0]
        denom = len(per_meal.get(mt, [])) or 1
        pct = 100.0 * cnt / denom
        print(f"  {name} ({rest}) x{cnt} ({pct:.0f}% of {mt})")

    parts = ", ".join(
        f"{mt}: {len({(s['dish_name'] or s['dish_id']) for s in ms})}/{len(ms)}"
        for mt, ms in sorted(per_meal.items(), key=lambda kv: MEAL_ORDER.get(kv[0], 9))
    )
    distinct_total = len(dish_counts)
    total_slots = len(slots)
    print(f"  distinct dishes by meal_type -> {parts}")
    print(f"  overall distinct: {distinct_total}/{total_slots}")

    repeats_max = top15[0][1] if top15 else 0

    # ---- 3. duplicate day signatures -------------------------------------
    print()
    print("-" * 70)
    print("DUPLICATE DAY MENUS (same sorted menu appearing on >=2 days)")
    print("-" * 70)
    sig_days = defaultdict(list)
    for day in sorted(days):
        menu_items = sorted(
            (s["dish_name"] or s["dish_id"]) for s in days[day]
        )
        sig_days[tuple(menu_items)].append(day)
    dup_sigs = {sig: ds for sig, ds in sig_days.items() if len(ds) >= 2}
    if dup_sigs:
        for sig, ds in sorted(dup_sigs.items(), key=lambda kv: kv[1][0]):
            menu = " | ".join(sig)
            print(f"  menu [{menu}] on days {', '.join(map(str, ds))}")
    else:
        print("  none")
    dup_days = sum(len(ds) - 1 for ds in dup_sigs.values())  # extra duplicated days

    # ---- 4. consecutive-day overlap ---------------------------------------
    print()
    print("-" * 70)
    print("CONSECUTIVE-DAY OVERLAP (>=2 shared dishes with previous day)")
    print("-" * 70)
    consec = []
    sorted_days = sorted(days)
    for prev_day, this_day in zip(sorted_days, sorted_days[1:]):
        prev_set = {(s["dish_name"] or s["dish_id"]) for s in days[prev_day]}
        this_set = {(s["dish_name"] or s["dish_id"]) for s in days[this_day]}
        shared = prev_set & this_set
        if len(shared) >= 2:
            consec.append((this_day, prev_day, sorted(shared)))
    if consec:
        for d, p, shared in consec:
            print(f"  day {d} shares {len(shared)} with day {p}: {', '.join(shared)}")
    else:
        print("  none")
    consec_overlap = len(consec)

    # ---- 5. composition economics ----------------------------------------
    print()
    print("-" * 70)
    print("SIDE-DISH ECONOMICS (side_price > 0 and side_price > price * 0.8)")
    print("-" * 70)
    bad_sides = 0
    for s in slots:
        price = s["price"] or 0.0
        side_price = s["side_price"] or 0.0
        if side_price > 0 and side_price > price * 0.8:
            bad_sides += 1
            ratio = side_price / price if price else float("inf")
            print(
                f"  day {s['day']} {s['meal_type']}: main={s['dish_name']} "
                f"(Rs{price:.0f}) + side={s['side_dish_name'] or '?'} "
                f"x{s['side_qty'] or '?'} (Rs{side_price:.0f}) "
                f"-> side is {ratio:.2f}x the main"
            )
    if bad_sides == 0:
        print("  none")

    # ---- 6. rating quality -------------------------------------------------
    print()
    print("-" * 70)
    print("RATING QUALITY")
    print("-" * 70)
    rated = [(s["dish_name"] or s["dish_id"], s["rating"]) for s in slots
             if s["rating"] is not None]
    ratings = [r for _, r in rated]
    low_rated_count = 0
    if rated:
        low = Counter(name for name, r in rated if r < 3.0)
        if low:
            print("  slots with rating < 3.0:")
            for name, cnt in low.most_common():
                rs = [r for nm, r in rated if nm == name]
                print(f"    {name} (rating {min(rs):.1f}) x{cnt}")
        else:
            print("  no slots with rating < 3.0")
        low_rated_count = sum(low.values())
        print(
            f"  overall rating min={min(ratings):.1f} "
            f"max={max(ratings):.1f} mean={mean(ratings):.2f} "
            f"(rated {len(ratings)}/{total_slots})"
        )
    else:
        warn("no rated slots")

    # ---- 7. cost distribution ----------------------------------------------
    print()
    print("-" * 70)
    print("DAILY COST DISTRIBUTION")
    print("-" * 70)
    day_costs = {}
    for day in sorted(days):
        day_costs[day] = sum(
            (s["price"] or 0.0) + (s["side_price"] or 0.0) + (s["side2_price"] or 0.0) if "side2_price" in s.keys() else (s["price"] or 0.0) + (s["side_price"] or 0.0)
            for s in days[day]
        )
    costs = list(day_costs.values())
    if costs:
        print(
            f"  mean=Rs{mean(costs):.1f} median=Rs{median(costs):.1f} "
            f"min=Rs{min(costs):.1f} max=Rs{max(costs):.1f}"
        )
        priciest = sorted(day_costs.items(), key=lambda kv: -kv[1])[:3]
        cheapest = sorted(day_costs.items(), key=lambda kv: kv[1])[:3]
        print("  priciest : " + ", ".join(
            f"day {d}=Rs{c:.0f}" for d, c in priciest))
        print("  cheapest : " + ", ".join(
            f"day {d}=Rs{c:.0f}" for d, c in cheapest))
    else:
        warn("no daily costs computed")

    # ---- 8. composition purity ----------------------------------------------
    print()
    print("-" * 70)
    print("COMPOSITION PURITY (meal slots only: breakfast|lunch|dinner)")
    print("-" * 70)
    purity = None
    sweets_in_meals = snacks_in_meals = beverages_in_meals = 0
    if has_columns(cur, "meal_slots", ["dish_kind"]):
        meal_slots = [s for s in slots if s["meal_type"] in ("breakfast", "lunch", "dinner")]
        if meal_slots:
            kind_counts = Counter((s["dish_kind"] or "meal") for s in meal_slots)
            meal_kind = kind_counts.get("meal", 0)
            purity = 100.0 * meal_kind / len(meal_slots) if meal_slots else 100.0
            sweets_in_meals = kind_counts.get("sweet", 0)
            snacks_in_meals = kind_counts.get("snack", 0)
            beverages_in_meals = kind_counts.get("beverage", 0)
            print(
                f"COMPOSITION PURITY (meal slots only: breakfast|lunch|dinner): "
                f"{meal_kind}/{len(meal_slots)} meal kind ({purity:.0f}% purity) — "
                f"sweets_in_meals={sweets_in_meals} snacks_in_meals={snacks_in_meals} "
                f"beverages_in_meals={beverages_in_meals}"
            )
            if sweets_in_meals or snacks_in_meals or beverages_in_meals:
                offender_counter = Counter(
                    ((s["dish_name"] or s["dish_id"], s["dish_kind"] or "meal")
                     for s in meal_slots if (s["dish_kind"] or "meal") != "meal")
                )
                by_kind = defaultdict(list)
                for (nm, kd), cnt in offender_counter.items():
                    by_kind[kd].append(((nm, kd), cnt))
                for kd in sorted(by_kind):
                    top3 = sorted(by_kind[kd], key=lambda x: -x[1])[:3]
                    formatted = ", ".join(f"{nm} [{kd}] x{cnt}" for (nm, _kd), cnt in top3)
                    print(f"  {kd} offenders: {formatted}")
            else:
                print("  all meal slots are kind=meal")
        else:
            purity = 100.0
            print("  no meal slots to check")
            print(
                "COMPOSITION PURITY (meal slots only: breakfast|lunch|dinner): "
                "0/0 meal kind (100% purity) — sweets_in_meals=0 snacks_in_meals=0 beverages_in_meals=0"
            )
    else:
        warn("meal_slots missing dish_kind -- skipping composition purity")

    # ---- 9. scorecard ------------------------------------------------------
    print()
    print("=" * 70)
    purity_str = f"{purity:.0f}%" if purity is not None else "N/A"
    print(
        f"SCORECARD repeats_max={repeats_max} dup_days={dup_days} "
        f"consec_overlap={consec_overlap} bad_sides={bad_sides} "
        f"low_rated={low_rated_count} "
        f"distinct={distinct_total}/{total_slots} "
        f"purity={purity_str} sweets_in_meals={sweets_in_meals} "
        f"snacks_in_meals={snacks_in_meals} beverages_in_meals={beverages_in_meals}"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
