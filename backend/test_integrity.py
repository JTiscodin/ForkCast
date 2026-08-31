"""RED reproduction tests for the integrity bug batch #2 (test_integrity).

Bugs already covered green in test_bugfixes.py are deliberately NOT repeated
here:
    double-yes-debit          -> test_double_yes_debits_once
    no-after-yes-refund       -> test_no_after_yes_does_not_refund_live_order
    approve-infeasible        -> test_over_budget_plan_not_approvable
    reschedule-out-of-range   -> test_reschedule_rejects_out_of_range_day

This file covers the REST of the audit list. Each test asserts the CORRECT
behavior, so while the bug is live it FAILS (red); after the fix it passes.

Run:  python test_integrity.py
"""
from db import get_conn, SCHEMA
from wallet_service import WalletService
from plan_service import PlanService
from order_executor import OrderExecutor


def fresh():
    """In-memory DB + PlanService wired to a MOCK executor (no real orders)."""
    conn = get_conn(":memory:")
    conn.executescript(SCHEMA)
    conn.commit()
    wallet = WalletService(conn)
    executor = OrderExecutor(mode="mock")
    svc = PlanService(conn, wallet, executor)
    return conn, wallet, svc


def seed_plan(conn, svc, budget=10000, feasible=1, days=3, meals=("lunch", "dinner")):
    """Create a user + approvable draft plan + one slot per (day, meal)."""
    uid = conn.execute("INSERT INTO users (name) VALUES ('T')").lastrowid
    conn.commit()

    class _Slot:
        def __init__(self, day, meal):
            self.day = day
            self.meal_type = meal
            self.dish_id = f"d{day}{meal}"
            self.dish_name = f"Dish {day} {meal}"
            self.restaurant_id = "r1"
            self.restaurant_name = "R"
            self.image_url = ""
            self.price = 100.0
            self.rating = 4.0
            self.variant = "regular"
            self.course = "complete"
            self.side_dish_id = ""
            self.side_dish_name = ""
            self.side_qty = 0
            self.side_price = 0.0
            self.side_restaurant_name = ""
            self.side_image_url = ""

    class _Result:
        def __init__(self):
            self.budget = budget
            self.total_cost = 100.0 * days * len(meals)
            self.feasible = bool(feasible)
            self.message = "ok"
            self.slots = [_Slot(d, m) for d in range(1, days + 1) for m in meals]

    plan_id = svc.save_plan(uid, "2026-07", _Result())
    return uid, plan_id


# ---- BUG: second approve_plan of the SAME plan must be rejected ----
# Symptom: tapping "Approve" twice on one plan re-ran approval instead of
# erroring, leaving the UI believing a second deposit/activation happened.
def test_second_approve_of_same_plan_rejected():
    conn, wallet, svc = fresh()
    uid, plan_id = seed_plan(conn, svc)
    svc.approve_plan(plan_id)                      # first approval is fine
    bal_before = wallet.get_balance(uid, "2026-07")

    try:
        svc.approve_plan(plan_id)                  # second tap on same plan
        assert False, "second approve_plan(same id) succeeded silently"
    except ValueError:
        pass
    assert wallet.get_balance(uid, "2026-07") == bal_before


class _NoCloseConn:
    """Proxy so an endpoint's `finally: conn.close()` can't kill our shared
    in-memory DB — only execute/commit/close are used by /appetite."""

    def __init__(self, real):
        self._real = real

    def execute(self, *a, **k):
        return self._real.execute(*a, **k)

    def commit(self):
        self._real.commit()

    def close(self):
        pass


# ---- BUG: /appetite with an unknown appetite_level must map to 400 ----
# Symptom: a typo'd/garbled level from the chat layer ("hevy!!") crashed the
# endpoint with a 500 ValueError instead of a clean 400 telling the user which
# levels exist.
def test_appetite_invalid_level_maps_to_400():
    from fastapi import HTTPException
    import app as appmod

    mem = get_conn(":memory:")
    mem.executescript(SCHEMA)
    mem.commit()
    uid = WalletService(mem).create_user("T")
    orig_svc = appmod.svc
    appmod.svc = lambda: (_NoCloseConn(mem), WalletService(mem), PlanService(mem))
    try:
        try:
            appmod.set_appetite(
                appmod.AppetiteIn(user_id=uid, appetite_level="bad appetite_level"))
            assert False, "/appetite accepted an invalid appetite_level"
        except HTTPException as e:
            assert e.status_code == 400, \
                f"invalid appetite_level surfaced as {e.status_code}, expected 400"
    finally:
        appmod.svc = orig_svc


# ---- BUG: meals=[] must be rejected, not planned as all three meals ----
# Symptom: a blueprint whose meals list came back empty still produced (and
# budgeted for) breakfast+lunch+dinner — asking for nothing got everything.
def test_meals_empty_rejected_not_planned_as_all_three():
    from catalog import mock_catalog
    from appetite import build_profile
    from optimizer import optimize

    prof = build_profile(1, "moderate")
    try:
        res = optimize(mock_catalog(), prof, 10000, days=2, meals=[])
        planned = sorted({s.meal_type for s in res.slots})
        assert False, (
            f"meals=[] was accepted and planned {planned} "
            f"({len(res.slots)} slots) instead of raising")
    except ValueError as e:
        assert "meal" in str(e).lower(), f"unhelpful rejection message: {e}"


# ---- BUG: appetite choice is lost on restart ----
# Symptom: user picks "heavy" portions, the backend restarts (or another worker
# serves the next request) and their plan quietly reverts to "moderate"
# portions — /appetite only filled the in-process cache.
def test_appetite_survives_restart():
    import app as appmod

    mem = get_conn(":memory:")
    mem.executescript(SCHEMA)
    mem.commit()
    uid = WalletService(mem).create_user("T")
    orig_svc = appmod.svc
    appmod.svc = lambda: (_NoCloseConn(mem), WalletService(mem), PlanService(mem))
    try:
        appmod.set_appetite(appmod.AppetiteIn(user_id=uid, appetite_level="heavy"))

        # 1. persisted: the profile row must be in appetite_profiles...
        row = mem.execute(
            "SELECT * FROM appetite_profiles WHERE user_id=?", (uid,)).fetchone()
        assert row is not None, "/appetite never wrote the appetite_profiles table"
        assert row["appetite_level"] == "heavy"

        # 2. reloaded: simulate a restart (fresh process = empty cache). Whatever
        #    the planner resolves for this user must come back as "heavy", not the
        #    silent "moderate" default. The reload itself reads through svc(), so
        #    svc stays patched until after this probe — restoring it earlier made
        #    the probe hit the real DB file, where this user does not exist.
        appmod._APPETITE_CACHE.pop(uid, None)
        prof = appmod._APPETITE_CACHE.get(uid)
        level = prof.appetite_level if prof else "moderate"
        assert level == "heavy", (
            f"after a restart the planner resolves appetite={level!r} — the saved "
            f"'heavy' profile was persisted but never reloaded")
    finally:
        appmod.svc = orig_svc


# ---- BUG: days=0 (or negative) must be rejected, not yield an empty plan ----
# Symptom: a zero/negative day count slipped through and produced a bogus empty
# "plan" that looked approved-ready instead of telling the user to pick >= 1 day.
def test_days_zero_rejected():
    from catalog import mock_catalog
    from appetite import build_profile
    from optimizer import optimize

    prof = build_profile(1, "moderate")
    try:
        res = optimize(mock_catalog(), prof, 10000, days=0, meals=["lunch"])
        assert False, (
            f"days=0 accepted -> {len(res.slots)} slots, "
            f"feasible={res.feasible}, message={res.message!r}")
    except ValueError:
        pass


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns)-failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
