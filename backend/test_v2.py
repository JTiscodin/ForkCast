"""v2 tests: image_url end-to-end, /why (AI + cache), /chat orchestration.

No network: Gemini is exercised via its fallback path (GEMINI_API_KEY unset), and
Swiggy stays in mock mode. In-memory / temp-file SQLite only, no disk pollution.
Avoids printing the rupee sign (Windows cp1252 console can't encode it).
"""
import os
import tempfile

# Force mock Swiggy + no Gemini BEFORE importing app/config so the app never tries
# to build a live MCP client or hit the network. (.env sets SWIGGY_MODE=mcp for real
# runs; tests must stay offline. We do not modify .env.)
os.environ["SWIGGY_MODE"] = "mock"

from db import get_conn, SCHEMA, migrate
from wallet_service import WalletService
from appetite import build_profile
from catalog import mock_catalog
from optimizer import optimize, Constraint, PlannedSlot
from plan_service import PlanService
from order_executor import OrderExecutor


def _mem_conn():
    conn = get_conn(":memory:")
    conn.executescript(SCHEMA)
    conn.commit()
    migrate(conn)   # idempotent; SCHEMA already has cols, proves migration is safe
    return conn


# ---------- TASK 1: image_url / restaurant_name flow ----------
def test_image_url_on_dish_and_planned_slot():
    cat = mock_catalog()
    assert all(hasattr(d, "image_url") for d in cat)
    assert cat[0].image_url  # mocks carry plausible URLs
    prof = build_profile(1, "moderate")
    r = optimize(cat, prof, budget=15000, days=2)
    s = r.slots[0]
    assert isinstance(s, PlannedSlot)
    assert s.image_url and s.restaurant_name


def test_image_url_flows_to_db_slot():
    conn = _mem_conn()
    w = WalletService(conn)
    plan_svc = PlanService(conn, w, OrderExecutor(mode="mock"))
    uid = w.create_user("Ishank")
    r = optimize(mock_catalog(), build_profile(uid, "moderate"), budget=15000, days=2)
    plan_id = plan_svc.save_plan(uid, "2026-07", r)
    _, slots = plan_svc.get_plan(plan_id)
    s0 = slots[0]
    assert s0["image_url"], "image_url must persist to meal_slots"
    assert s0["restaurant_name"], "restaurant_name must persist to meal_slots"
    assert "why_text" in s0  # column exists (may be None)


def test_migration_idempotent_on_legacy_db():
    # simulate an OLD dev DB missing the new columns, then migrate twice.
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = get_conn(path)
        conn.executescript("""
            CREATE TABLE plans (id INTEGER PRIMARY KEY, user_id INTEGER, month TEXT,
                budget REAL, total_cost REAL, feasible INTEGER, status TEXT, message TEXT);
            CREATE TABLE meal_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER, day INTEGER,
                meal_type TEXT, dish_id TEXT, dish_name TEXT, restaurant_id TEXT,
                price REAL, rating REAL, variant TEXT, status TEXT, order_id TEXT);
        """)
        conn.commit()
        migrate(conn)
        migrate(conn)  # second run must not raise
        cols = {r[1] for r in conn.execute("PRAGMA table_info(meal_slots)").fetchall()}
        assert {"restaurant_name", "image_url", "why_text"} <= cols
        conn.close()
    finally:
        os.remove(path)


# ---------- TASK 2: /why endpoint (fallback + cache) ----------
def _seeded_plan(conn):
    w = WalletService(conn)
    plan_svc = PlanService(conn, w, OrderExecutor(mode="mock"))
    uid = w.create_user("Ishank")
    r = optimize(mock_catalog(), build_profile(uid, "heavy"), budget=15000, days=2)
    plan_id = plan_svc.save_plan(uid, "2026-07", r)
    _, slots = plan_svc.get_plan(plan_id)
    return plan_svc, slots


def test_why_returns_text_and_caches(monkeypatch=None):
    # ensure no key -> deterministic fallback path (no network)
    old = os.environ.pop("GEMINI_API_KEY", None)
    try:
        import importlib
        import app as appmod
        # point the app at an in-memory-ish temp DB so svc() works
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from db import init_db
            init_db(path)
            orig_get_conn = appmod.get_conn
            appmod.get_conn = lambda db_path=path: orig_get_conn(path)
            try:
                conn = appmod.get_conn()
                plan_svc, slots = _seeded_plan(conn)
                conn.close()
                sid = slots[0]["id"]

                r1 = appmod.why(sid)
                assert r1["why"] and len(r1["why"]) > 0
                assert r1["cached"] is False

                # cached on second call, identical text, still no crash
                r2 = appmod.why(sid)
                assert r2["cached"] is True
                assert r2["why"] == r1["why"]

                # verify persisted
                conn = appmod.get_conn()
                row = conn.execute("SELECT why_text FROM meal_slots WHERE id=?",
                                   (sid,)).fetchone()
                conn.close()
                assert row["why_text"] == r1["why"]
            finally:
                appmod.get_conn = orig_get_conn
        finally:
            os.remove(path)
    finally:
        if old is not None:
            os.environ["GEMINI_API_KEY"] = old


# ---------- TASK 3: /chat orchestration ----------
def test_chat_ready_to_plan_when_budget_and_appetite():
    old = os.environ.pop("GEMINI_API_KEY", None)  # deterministic reply, no network
    try:
        import app as appmod
        body = appmod.ChatIn(user_id=1,
                             message="10k budget, at least 10 paneer meals, veg only, heavy eater")
        res = appmod.chat(body)
        assert res["action"] == "ready_to_plan"
        assert res["extracted"]["budget"] == 10000
        assert res["extracted"]["appetite_level"] == "heavy"
        assert res["extracted"]["veg_only"] is True
        assert res["missing"] == []
        assert res["reply"]
    finally:
        if old is not None:
            os.environ["GEMINI_API_KEY"] = old


def test_chat_need_more_when_missing():
    old = os.environ.pop("GEMINI_API_KEY", None)
    try:
        import app as appmod
        body = appmod.ChatIn(user_id=1, message="I want a veg plan")
        res = appmod.chat(body)
        assert res["action"] == "need_more"
        assert "budget" in res["missing"]
        assert "appetite_level" in res["missing"]
        assert res["reply"]
    finally:
        if old is not None:
            os.environ["GEMINI_API_KEY"] = old


def test_chat_merges_session_state_across_turns():
    old = os.environ.pop("GEMINI_API_KEY", None)
    try:
        import app as appmod
        # turn 1: only budget
        r1 = appmod.chat(appmod.ChatIn(user_id=1, message="my budget is 12000"))
        assert r1["action"] == "need_more"
        assert r1["extracted"]["budget"] == 12000
        # turn 2: appetite only, echo prior extracted back
        r2 = appmod.chat(appmod.ChatIn(
            user_id=1, message="I'm a heavy eater",
            session_state={"extracted": r1["extracted"]}))
        assert r2["extracted"]["budget"] == 12000  # merged from prior turn
        assert r2["extracted"]["appetite_level"] == "heavy"
        assert r2["action"] == "ready_to_plan"
        assert r2["missing"] == []
    finally:
        if old is not None:
            os.environ["GEMINI_API_KEY"] = old


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns)-failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
