"""End-to-end demo flow test. Exercises the whole pipeline in-memory:
intake -> appetite -> optimize -> save plan -> approve (deposit) ->
notify slot -> yes(order+debit) / no(credit) -> month close (rollover).
"""
from db import get_conn, SCHEMA
from wallet_service import WalletService
from appetite import build_profile
from catalog import mock_catalog
from optimizer import optimize, Constraint
from plan_service import PlanService
from order_executor import OrderExecutor
from intake import fallback_parse


def setup():
    conn = get_conn(":memory:")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def test_full_demo_flow():
    conn = setup()
    w = WalletService(conn)
    plan_svc = PlanService(conn, w, OrderExecutor(mode="mock"))

    # 1. user + intake
    uid = w.create_user("Ishank", "Bandra")
    parsed = fallback_parse("10k budget, at least 10 paneer meals, veg only, heavy eater")
    assert parsed.budget == 10000
    assert parsed.veg_only
    assert parsed.appetite_level == "heavy"

    # 2. appetite
    prof = build_profile(uid, parsed.appetite_level)

    # 3. optimize
    cons = [Constraint(c["dish_tag"], c["min_count"]) for c in parsed.constraints]
    result = optimize(mock_catalog(), prof, parsed.budget, days=30,
                      constraints=cons, veg_only=parsed.veg_only)
    assert len(result.slots) == 90

    # 4. save + approve. An over-budget plan must be REJECTED at approval
    #    (wallet-integrity guard); re-plan with a budget that fits, then approve.
    plan_id = plan_svc.save_plan(uid, "2026-07", result)
    plan, slots = plan_svc.get_plan(plan_id)
    assert len(slots) == 90
    if not result.feasible:
        try:
            plan_svc.approve_plan(plan_id)
            assert False, "over-budget plan was approved"
        except ValueError:
            pass
        result = optimize(mock_catalog(), prof, int(result.total_cost) + 1000,
                          days=30, constraints=cons, veg_only=parsed.veg_only)
        assert result.feasible
        plan_id = plan_svc.save_plan(uid, "2026-07", result)
        plan, slots = plan_svc.get_plan(plan_id)
    plan_svc.approve_plan(plan_id)
    assert w.get_summary(uid, "2026-07")["budget_allocated"] == result.budget

    # 5. notify + YES on first slot -> order + debit
    first = slots[0]
    notif = plan_svc.notify(first["id"])
    assert "options" in notif
    bal_before = w.get_balance(uid, "2026-07")
    res = plan_svc.respond(first["id"], "yes")
    assert res["result"] == "ordered"
    assert res["order"]["order_id"].startswith("MOCK-")
    assert w.get_balance(uid, "2026-07") == round(bal_before - first["price"], 2)

    # 6. NO on second slot -> money simply not spent, balance unchanged
    #    (full budget deposited at approval; skipping a planned slot = keep the cash)
    second = slots[1]
    bal_before2 = w.get_balance(uid, "2026-07")
    res2 = plan_svc.respond(second["id"], "no")
    assert res2["result"] == "skipped"
    assert w.get_balance(uid, "2026-07") == bal_before2  # unspent, no phantom credit

    # 7. later on third slot -> reschedule
    third = slots[2]
    res3 = plan_svc.respond(third["id"], "later", new_day=15)
    assert res3["result"] == "rescheduled"
    moved = conn.execute("SELECT day, status FROM meal_slots WHERE id=?",
                         (third["id"],)).fetchone()
    assert moved["day"] == 15 and moved["status"] == "rescheduled"

    # 8. month close -> rollover leftover into next month.
    #    Only 1 slot actually ordered (the YES), so total_spent == that 1 debit.
    #    Rollover = budget - actual spend, capped at budget.
    summary = w.get_summary(uid, "2026-07")
    assert summary["total_spent"] == first["price"]  # only the confirmed order spent
    rolled = w.close_cycle(uid, "2026-07")
    assert 0 <= rolled <= result.budget
    assert w.get_summary(uid, "2026-08")["rolled_in"] == rolled

    print(f"  demo: budget {result.budget}, planned {result.total_cost}, "
          f"paneer {result.constraint_status.get('paneer')}, rolled {rolled}")


if __name__ == "__main__":
    import sys
    try:
        test_full_demo_flow()
        print("PASS test_full_demo_flow")
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"FAIL: {e}")
        sys.exit(1)
