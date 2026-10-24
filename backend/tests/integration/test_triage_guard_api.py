import pytest
from fastapi.testclient import TestClient

from bellhop.api.app import create_app
from bellhop.container import Settings, build_container


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(build_container(Settings(seed_demo=True))))


def _call_with(client, text):
    call_id = client.post("/calls", json={"room": "12"}).json()["id"]
    client.post(f"/calls/{call_id}/turns", json={"speaker": "resident", "text": text})
    return call_id


def test_fall_utterance_with_low_model_score_becomes_emergency_with_broadcast(client):
    call_id = _call_with(client, "I've fallen and I can't get up")
    r = client.post(f"/calls/{call_id}/score", json={"urgency": 1, "category": "social"})
    body = r.json()
    assert body["urgency"] == 4
    assert body["summary"].startswith("keyword:")
    alerts = client.get("/alerts").json()
    assert len(alerts) == 1
    assert alerts[0]["level"] == 4 and alerts[0]["nurse_id"] is None


def test_benign_utterance_keeps_model_score_and_summary(client):
    call_id = _call_with(client, "could I have some tea please")
    body = client.post(
        f"/calls/{call_id}/score", json={"urgency": 1, "category": "social", "summary": "tea"}
    ).json()
    assert (body["urgency"], body["summary"]) == (1, "tea")


def test_low_confidence_bumps_urgency_and_explains(client):
    call_id = _call_with(client, "my arm feels a bit odd")
    body = client.post(
        f"/calls/{call_id}/score",
        json={"urgency": 2, "category": "comfort", "confidence": 0.3, "summary": "arm"},
    ).json()
    assert body["urgency"] == 3
    assert body["summary"].startswith("arm")
    assert "confidence" in body["summary"]
    assert len(client.get("/alerts").json()) == 1


def test_confidence_out_of_range_is_422(client):
    call_id = _call_with(client, "hello")
    r = client.post(
        f"/calls/{call_id}/score", json={"urgency": 1, "category": "x", "confidence": 2}
    )
    assert r.status_code == 422


def test_triage_failed_defaults_to_nurse_soon_and_alerts(client):
    call_id = _call_with(client, "could I have some tea please")
    body = client.post(f"/calls/{call_id}/triage-failed").json()
    assert body["urgency"] == 3
    assert "model unavailable" in body["summary"]
    assert len(client.get("/alerts").json()) == 1


def test_triage_failed_with_fall_words_is_emergency(client):
    call_id = _call_with(client, "I fell and can't get up")
    assert client.post(f"/calls/{call_id}/triage-failed").json()["urgency"] == 4


def test_triage_failed_unknown_call_404(client):
    assert client.post("/calls/nope/triage-failed").status_code == 404
