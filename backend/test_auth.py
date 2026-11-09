import pytest
from fastapi.testclient import TestClient

import app as app_mod
import auth


@pytest.fixture
def client():
    return TestClient(app_mod.app)


def test_token_round_trip_and_forgery():
    assert auth.user_from("Bearer " + auth.bearer(7)) == 7
    assert auth.user_from("Bearer 8." + auth.token_for(7)) is None   # someone else's signature
    assert auth.user_from(None) is None


def test_user_routes_need_the_owners_token(client):
    uid = client.post("/user", json={"name": "A"}).json()
    other = client.post("/user", json={"name": "B"}).json()
    assert client.get(f"/daily/{uid['user_id']}/memory").status_code == 403            # no token
    h = {"Authorization": "Bearer " + other["token"]}
    assert client.delete(f"/daily/{uid['user_id']}", headers=h).status_code == 403    # wrong user
    assert client.post("/chat", json={"user_id": uid["user_id"], "message": "hi"}, headers=h).status_code == 403
    mine = {"Authorization": "Bearer " + uid["token"]}
    assert client.delete(f"/daily/{uid['user_id']}", headers=mine).status_code == 200
    client.delete(f"/daily/{other['user_id']}", headers=h)


def test_public_routes_stay_open(client):
    assert client.get("/mode").status_code == 200
