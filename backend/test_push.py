from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import app as app_mod
import daily
import db
import push

SUB = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "pk", "auth": "ak"}}


def test_due_slots_pure():
    w = {"breakfast": ["07:00", "10:00"], "lunch": ["12:00", "15:00"]}
    assert push.due_slots(["breakfast", "lunch"], w, "12:00", set()) == ["lunch"]
    assert push.due_slots(["breakfast", "lunch"], w, "12:00", {"lunch"}) == []
    assert push.due_slots(["breakfast"], w, "12:00", set()) == []   # lunch not planned
    assert push.due_slots(["lunch"], w, "12:01", set()) == []


def test_subscribe_is_owner_only():
    c = TestClient(app_mod.app)
    a = c.post("/user", json={"name": "A"}).json()
    b = c.post("/user", json={"name": "B"}).json()
    ha, hb = ({"Authorization": "Bearer " + u["token"]} for u in (a, b))
    try:
        assert c.get("/push/vapid-public-key").json()["key"]
        assert c.post(f"/daily/{a['user_id']}/push", json=SUB, headers=hb).status_code == 403
        assert c.post(f"/daily/{a['user_id']}/push", json=SUB).status_code == 403
        assert c.post(f"/daily/{a['user_id']}/push", json={**SUB, "endpoint": "http://x"}, headers=ha).status_code == 400
        assert c.post(f"/daily/{a['user_id']}/push", json={**SUB, "endpoint": "https://169.254.169.254/latest"}, headers=ha).status_code == 400
        assert c.post(f"/daily/{a['user_id']}/push", json=SUB, headers=ha).status_code == 200
        assert c.delete(f"/daily/{a['user_id']}/push", headers=hb).status_code == 403
        assert c.delete(f"/daily/{a['user_id']}/push", headers=ha).status_code == 200
    finally:
        for u, h in ((a, ha), (b, hb)):
            c.delete(f"/daily/{u['user_id']}", headers=h)


def test_tick_sends_once_and_drops_gone_subscriptions(monkeypatch):
    conn = db.get_conn(":memory:")
    conn.executescript(db.SCHEMA)
    conn.execute("INSERT INTO users (id, name) VALUES (1, 'T')")
    daily.save_profile(conn, 1, {"diet_type": "veg", "slots": ["lunch"], "monthly_budget": 9000})
    push.subscribe(conn, 1, SUB)
    push.subscribe(conn, 1, {**SUB, "endpoint": "https://fcm.googleapis.com/fcm/send/gone"})
    monkeypatch.setattr(push, "vapid", lambda: {"private": "x", "subject": "mailto:a@b"})
    monkeypatch.setattr(push, "_SENT", set())
    got = []

    class Gone(Exception):
        response = type("R", (), {"status_code": 410})()

    def send(sub, data, keys):
        if sub["endpoint"].endswith("gone"):
            raise Gone()
        got.append(data)

    now = datetime(2026, 11, 4, 12, 0)
    assert push.tick(conn, now, send) == 1
    assert got[0]["title"] == "Lunch time" and got[0]["url"] == "/#slot-lunch"
    assert conn.execute("SELECT COUNT(*) FROM push_subscription").fetchone()[0] == 1
    assert push.tick(conn, now, send) == 0   # deduped
    assert push.tick(conn, datetime(2026, 11, 4, 12, 1), send) == 0
