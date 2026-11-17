import sqlite3
import hf_backup


def test_noop_without_env(monkeypatch):
    monkeypatch.delenv("HF_BACKUP_REPO", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert hf_backup.restore() is False
    assert hf_backup.upload() is False
    assert hf_backup.start() is False


def test_snapshot_copies_live_db(tmp_path):
    src = tmp_path / "live.db"
    conn = sqlite3.connect(src)
    conn.execute("create table t(x)")
    conn.execute("insert into t values (42)")
    conn.commit()   # connection left open, like the running app
    out = hf_backup.snapshot(src, str(tmp_path / "snap.db"))
    with sqlite3.connect(out) as c:
        assert c.execute("select x from t").fetchall() == [(42,)]
    conn.close()


def test_ping_is_public():
    from fastapi.testclient import TestClient
    import app as app_mod
    r = TestClient(app_mod.app, client=("203.0.113.9", 5000)).get("/ping")
    assert r.status_code == 200 and r.json() == {"ok": True}
