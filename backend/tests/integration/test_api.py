import pytest
from fastapi.testclient import TestClient

from bellhop.api.app import create_app
from bellhop.container import Settings, build_container


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(build_container(Settings(seed_demo=True))))


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_cors_allows_any_origin(client):
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "*"


def _raise(client, room="12"):
    return client.post("/calls", json={"room": room})


def test_create_call_returns_201_and_assigns(client):
    r = _raise(client)
    assert r.status_code == 201
    body = r.json()
    assert body["room"] == "12"
    assert body["status"] == "assigned"
    assert body["resident_id"] == "res_margaret"


def test_create_call_requires_room(client):
    assert client.post("/calls", json={}).status_code == 422


def test_get_call_and_404(client):
    call_id = _raise(client).json()["id"]
    assert client.get(f"/calls/{call_id}").json()["id"] == call_id
    assert client.get("/calls/nope").status_code == 404


def test_list_calls_newest_first(client):
    first = _raise(client, "12").json()["id"]
    second = _raise(client, "14").json()["id"]
    assert [c["id"] for c in client.get("/calls").json()] == [second, first]


def test_add_turn(client):
    call_id = _raise(client).json()["id"]
    r = client.post(f"/calls/{call_id}/turns", json={"speaker": "resident", "text": "hi"})
    assert r.status_code == 200
    assert r.json()["transcript"][0]["text"] == "hi"
    assert client.post("/calls/nope/turns", json={"speaker": "a", "text": "b"}).status_code == 404
    assert client.post(f"/calls/{call_id}/turns", json={"speaker": "a"}).status_code == 422


def test_score_validates_urgency_range(client):
    call_id = _raise(client).json()["id"]
    for bad in (0, 5):
        r = client.post(f"/calls/{call_id}/score", json={"urgency": bad, "category": "x"})
        assert r.status_code == 422
    assert client.post("/calls/nope/score", json={"urgency": 2, "category": "x"}).status_code == 404


def test_score_updates_call(client):
    call_id = _raise(client).json()["id"]
    r = client.post(
        f"/calls/{call_id}/score", json={"urgency": 3, "category": "pain", "summary": "hip"}
    )
    body = r.json()
    assert (body["urgency"], body["category"], body["summary"]) == (3, "pain", "hip")
    assert body["status"] == "escalated"


def test_in_visit_and_resolve(client):
    call_id = _raise(client).json()["id"]
    assert client.post(f"/calls/{call_id}/in-visit").json()["status"] == "in_visit"
    r = client.post(f"/calls/{call_id}/resolve", json={})
    assert r.json()["status"] == "resolved"
    assert client.get("/metrics").json()["resolved_without_nurse"] == 1


def test_resolve_without_body_defaults_by_robot(client):
    call_id = _raise(client).json()["id"]
    assert client.post(f"/calls/{call_id}/resolve").status_code == 200


def test_invalid_transition_is_409(client):
    call_id = _raise(client).json()["id"]
    client.post(f"/calls/{call_id}/resolve")
    assert client.post(f"/calls/{call_id}/in-visit").status_code == 409


def test_memory_roundtrip(client):
    r = client.post(
        "/residents/res_margaret/memory", json={"text": "Loves jazz music", "tags": ["music"]}
    )
    assert r.status_code == 201
    assert r.json()["text"] == "Loves jazz music"
    facts = client.get("/residents/res_margaret/memory", params={"q": "jazz", "k": 1}).json()
    assert len(facts) == 1
    assert facts[0]["text"] == "Loves jazz music"


def test_memory_post_requires_text(client):
    assert client.post("/residents/res_margaret/memory", json={}).status_code == 422


def test_metrics_shape(client):
    _raise(client, "12")
    m = client.get("/metrics").json()
    assert set(m) == {
        "resolved_without_nurse",
        "minutes_saved",
        "share_answered_within_10min",
        "calls_by_hour",
        "calls_by_room",
        "calls_by_category",
    }
    assert m["calls_by_room"] == {"12": 1}


def test_ack_unknown_alert_is_404(client):
    assert client.post("/alerts/nope/ack", json={"nurse_id": "n"}).status_code == 404


def test_end_to_end_nurse_ack(client):
    call_id = _raise(client, "12").json()["id"]
    client.post(f"/calls/{call_id}/score", json={"urgency": 3, "category": "pain"})
    alerts = client.get("/alerts").json()
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["call_id"] == call_id
    r = client.post(f"/alerts/{alert['id']}/ack", json={"nurse_id": "nurse_priya"})
    assert r.status_code == 200
    assert r.json()["acked_at"] is not None
    call = client.get(f"/calls/{call_id}").json()
    assert call["status"] == "nurse_acked"
    assert "nurse_priya" in call["assigned_to"]


def test_fall_scenario_broadcasts_alert(client):
    call_id = _raise(client, "12").json()["id"]
    client.post(f"/calls/{call_id}/turns", json={"speaker": "resident", "text": "I have fallen"})
    client.post(f"/calls/{call_id}/score", json={"urgency": 4, "category": "fall"})
    alerts = client.get("/alerts").json()
    assert len(alerts) == 1
    assert alerts[0]["nurse_id"] is None
    assert alerts[0]["level"] == 4
    assert "fallen" in alerts[0]["message"]
