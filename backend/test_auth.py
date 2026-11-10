import pytest
from fastapi.testclient import TestClient

import app as app_mod
import auth


@pytest.fixture
def client():
    return TestClient(app_mod.app)


def test_token_round_trip_and_forgery():
    assert auth.user_from("Bearer " + auth.bearer(7)) == 7
    assert auth.user_from("Bearer 8." + auth.token_for(7)) is None   # old no-expiry format is refused
    assert auth.user_from(None) is None
    assert auth.user_from("Bearer " + auth.bearer(7, now=0)) is None   # issued long ago: expired
    uid, exp, sig = auth.bearer(7).split(".")
    assert auth.user_from(f"Bearer {uid}.{int(exp) + 999}.{sig}") is None   # expiry can't be edited


def test_response_renews_the_token(client):
    u = client.post("/user", json={"name": "R"}).json()
    r = client.get(f"/daily/{u['user_id']}/memory", headers={"Authorization": "Bearer " + u["token"]})
    assert auth.user_from("Bearer " + r.headers["X-Forkcast-Token"]) == u["user_id"]
    client.delete(f"/daily/{u['user_id']}", headers={"Authorization": "Bearer " + u["token"]})


def test_same_swiggy_account_signs_back_in(client, monkeypatch):
    class Swiggy:
        token = "t"

        def call(self, tool, args):
            return {"addresses": [{"id": "999__home"}, {"id": "999__work"}]}
    monkeypatch.setattr(app_mod, "_live", lambda: True)
    monkeypatch.setitem(app_mod.STATE, "client", Swiggy())
    client = TestClient(app_mod.app, client=("127.0.0.1", 5000))   # the person at the server's machine
    a = client.post("/user", json={"name": "S", "address_id": "999__home"}).json()
    b = client.post("/user", json={"name": "S", "address_id": "999__work"}).json()
    assert b["user_id"] == a["user_id"] and b["returning"] is True
    stranger = client.post("/user", json={"name": "X", "address_id": "999__made_up"}).json()
    assert stranger["user_id"] != a["user_id"]            # unproven address never signs in
    remote = TestClient(app_mod.app, client=("203.0.113.9", 5000))
    r = remote.post("/user", json={"name": "S", "address_id": "999__home"}).json()
    assert r["user_id"] != a["user_id"] and r["returning"] is False   # remote callers can't reclaim an account
    client.delete(f"/daily/{r['user_id']}", headers={"Authorization": "Bearer " + r["token"]})
    for u in (a, stranger):
        client.delete(f"/daily/{u['user_id']}", headers={"Authorization": "Bearer " + u["token"]})


def test_user_routes_need_the_owners_token(client):
    uid = client.post("/user", json={"name": "A"}).json()
    other = client.post("/user", json={"name": "B"}).json()
    assert client.get(f"/daily/{uid['user_id']}/memory").status_code == 403            # no token
    h = {"Authorization": "Bearer " + other["token"]}
    assert client.delete(f"/daily/{uid['user_id']}", headers=h).status_code == 403    # wrong user
    assert client.post("/chat", json={"user_id": uid["user_id"], "message": "hi"}, headers=h).status_code == 403
    # body sent without a JSON content-type is still checked
    raw = client.post("/chat", content=f'{{"user_id": {uid["user_id"]}, "message": "hi"}}', headers=h)
    assert raw.status_code == 403
    mine = {"Authorization": "Bearer " + uid["token"]}
    assert client.delete(f"/daily/{uid['user_id']}", headers=mine).status_code == 200
    client.delete(f"/daily/{other['user_id']}", headers=h)


def test_deleted_account_token_stops_working(client):
    u = client.post("/user", json={"name": "D"}).json()
    h = {"Authorization": "Bearer " + u["token"]}
    assert client.delete(f"/daily/{u['user_id']}", headers=h).status_code == 200
    assert client.get(f"/daily/{u['user_id']}/memory", headers=h).status_code == 403


def test_public_routes_stay_open(client):
    assert client.get("/mode").status_code == 200
