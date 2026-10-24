import pytest
from fastapi.testclient import TestClient

from bellhop.api.app import create_app
from bellhop.container import Settings, build_container


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(build_container(Settings(seed_demo=True))))


def test_create_resident_returns_201_and_is_listed_and_readable(client):
    r = client.post(
        "/residents",
        json={"id": "res_ines", "name": "Ines", "room": "301", "risk_flags": ["falls"]},
    )
    assert r.status_code == 201
    assert r.json() == {
        "id": "res_ines",
        "name": "Ines",
        "room": "301",
        "risk_flags": ["falls"],
        "birth_year": None,
    }
    assert client.get("/residents/res_ines").json() == r.json()
    assert "res_ines" in {x["id"] for x in client.get("/residents").json()}


def test_create_resident_without_id_generates_one(client):
    r = client.post("/residents", json={"name": "Ines", "room": "301"})
    assert r.status_code == 201
    assert r.json()["id"]


def test_new_resident_is_attached_to_calls_from_their_room(client):
    client.post("/residents", json={"id": "res_x", "name": "Xan", "room": "301"})
    assert client.post("/calls", json={"room": "301"}).json()["resident_id"] == "res_x"


def test_duplicate_resident_id_and_room_clash_are_409(client):
    assert (
        client.post(
            "/residents", json={"id": "res_margaret", "name": "M", "room": "99"}
        ).status_code
        == 409
    )
    assert (
        client.post("/residents", json={"id": "res_z", "name": "Z", "room": "12"}).status_code
        == 409
    )


@pytest.mark.parametrize(
    "body",
    [
        {"room": "1"},
        {"name": "A"},
        {"name": "", "room": "1"},
        {"name": "A", "room": "1", "extra": 1},
        {"name": "A" * 81, "room": "1"},
        {"name": "A", "room": "1", "risk_flags": ["x"] * 11},
        {"name": "A", "room": "1", "birth_year": "old"},
    ],
)
def test_create_resident_validation_is_422(client, body):
    assert client.post("/residents", json=body).status_code == 422


def test_unknown_resident_is_404(client):
    assert client.get("/residents/nope").status_code == 404
    assert client.patch("/residents/nope", json={"name": "A"}).status_code == 404


def test_patch_resident_changes_only_given_fields(client):
    r = client.patch("/residents/res_margaret", json={"name": "Maggie", "birth_year": 1940})
    assert r.status_code == 200
    body = r.json()
    assert (body["name"], body["room"], body["birth_year"]) == ("Maggie", "12", 1940)
    assert body["risk_flags"] == ["falls"]
    cleared = client.patch("/residents/res_margaret", json={"risk_flags": []}).json()
    assert cleared["risk_flags"] == []


def test_patch_resident_room_clash_is_409_and_move_is_allowed(client):
    assert client.patch("/residents/res_margaret", json={"room": "14"}).status_code == 409
    assert client.patch("/residents/res_margaret", json={"room": "20"}).json()["room"] == "20"


@pytest.mark.parametrize("body", [{"name": None}, {"room": ""}, {"bogus": 1}, {"risk_flags": "x"}])
def test_patch_resident_validation_is_422(client, body):
    assert client.patch("/residents/res_margaret", json=body).status_code == 422


def test_put_birth_year_still_works(client):
    r = client.put("/residents/res_margaret", json={"birth_year": 1938})
    assert r.status_code == 200 and r.json()["birth_year"] == 1938
    assert client.put("/residents/nope", json={"birth_year": 1938}).status_code == 404


def test_nurse_lifecycle(client):
    r = client.post("/nurses", json={"id": "nurse_lena", "name": "Lena"})
    assert r.status_code == 201
    assert r.json() == {"id": "nurse_lena", "name": "Lena", "on_shift": True, "open_tasks": 0}
    assert "nurse_lena" in {n["id"] for n in client.get("/nurses").json()}
    p = client.patch("/nurses/nurse_lena", json={"on_shift": False, "name": "Lena K"})
    assert p.status_code == 200
    assert (p.json()["on_shift"], p.json()["name"]) == (False, "Lena K")


def test_nurse_errors(client):
    assert client.post("/nurses", json={"id": "nurse_priya", "name": "P"}).status_code == 409
    assert client.post("/nurses", json={"name": ""}).status_code == 422
    assert client.post("/nurses", json={"name": "A", "on_shift": "maybe"}).status_code == 422
    assert client.patch("/nurses/nope", json={"name": "A"}).status_code == 404
    assert client.patch("/nurses/nurse_priya", json={"bogus": 1}).status_code == 422
    assert client.patch("/nurses/nurse_priya", json={"name": None}).status_code == 422


def test_admin_routes_need_api_key_when_configured():
    c = TestClient(create_app(build_container(Settings(seed_demo=True, api_key="k"))))
    assert c.get("/residents").status_code == 401
    assert c.get("/nurses", headers={"X-API-Key": "k"}).status_code == 200
    assert c.post("/nurses", json={"name": "A"}).status_code == 401


def test_admin_body_over_limit_is_413(client):
    assert client.post("/residents", content=b"x" * (1024 * 1024 + 1)).status_code == 413
