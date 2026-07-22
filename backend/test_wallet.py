"""Unit tests for WalletService. In-memory SQLite, no disk touch."""
from db import get_conn, SCHEMA
from wallet_service import WalletService, next_month


def fresh_service():
    conn = get_conn(":memory:")
    conn.executescript(SCHEMA)
    conn.commit()
    return WalletService(conn)


def test_next_month():
    assert next_month("2026-07") == "2026-08"
    assert next_month("2026-12") == "2027-01"


def test_deposit_and_balance():
    w = fresh_service()
    uid = w.create_user("Ishank")
    w.deposit(uid, "2026-07", 10000)
    assert w.get_balance(uid, "2026-07") == 10000


def test_debit_reduces_balance():
    w = fresh_service()
    uid = w.create_user("Ishank")
    w.deposit(uid, "2026-07", 10000)
    w.debit(uid, "2026-07", 180, note="Paneer Tikka Bowl")
    assert w.get_balance(uid, "2026-07") == 9820


def test_credit_returns_money():
    w = fresh_service()
    uid = w.create_user("Ishank")
    w.deposit(uid, "2026-07", 10000)
    w.debit(uid, "2026-07", 180)
    w.credit(uid, "2026-07", 180, note="meal skipped")
    assert w.get_balance(uid, "2026-07") == 10000


def test_total_spent_cache():
    w = fresh_service()
    uid = w.create_user("Ishank")
    w.deposit(uid, "2026-07", 10000)
    w.debit(uid, "2026-07", 200)
    w.debit(uid, "2026-07", 150)
    w.credit(uid, "2026-07", 50)  # partial refund
    s = w.get_summary(uid, "2026-07")
    assert s["total_spent"] == 300  # 200+150-50
    assert s["balance"] == 9700


def test_rollover_carries_leftover():
    w = fresh_service()
    uid = w.create_user("Ishank")
    w.deposit(uid, "2026-07", 10000)
    w.debit(uid, "2026-07", 7000)
    rolled = w.close_cycle(uid, "2026-07")
    assert rolled == 3000
    # next month starts with rollover as balance
    assert w.get_balance(uid, "2026-08") == 3000
    s = w.get_summary(uid, "2026-08")
    assert s["rolled_in"] == 3000


def test_rollover_never_negative():
    w = fresh_service()
    uid = w.create_user("Ishank")
    w.deposit(uid, "2026-07", 1000)
    w.debit(uid, "2026-07", 1000)
    rolled = w.close_cycle(uid, "2026-07")
    assert rolled == 0
    assert w.get_balance(uid, "2026-08") == 0


def test_double_close_raises():
    w = fresh_service()
    uid = w.create_user("Ishank")
    w.deposit(uid, "2026-07", 1000)
    w.close_cycle(uid, "2026-07")
    try:
        w.close_cycle(uid, "2026-07")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_bad_amount_rejected():
    w = fresh_service()
    uid = w.create_user("Ishank")
    try:
        w.deposit(uid, "2026-07", -5)
        assert False, "expected ValueError"
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
        except Exception as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns)-failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
