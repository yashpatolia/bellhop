"""GET /alerts must reflect the store, including acknowledgements."""

import pytest
from fastapi.testclient import TestClient

from bellhop.api.app import create_app
from bellhop.container import Settings, build_container


@pytest.fixture
def client():
    return TestClient(create_app(build_container(Settings(seed_demo=True, guard_timeouts=False))))


def _raise_nurse_alert(client):
    call = client.post("/calls", json={"room": "12"}).json()
    client.post(f"/calls/{call['id']}/score", json={"urgency": 3, "category": "pain"})
    (alert,) = client.get("/alerts").json()
    return alert


def test_acknowledged_alert_shows_acked_at_in_listing(client):
    alert = _raise_nurse_alert(client)
    assert alert["acked_at"] is None

    client.post(f"/alerts/{alert['id']}/ack", json={"nurse_id": alert["nurse_id"]})

    (listed,) = client.get("/alerts").json()
    assert listed["acked_at"] is not None


def test_alerts_listed_newest_first(client):
    first = client.post("/calls", json={"room": "12"}).json()
    client.post(f"/calls/{first['id']}/score", json={"urgency": 3, "category": "pain"})
    second = client.post("/calls", json={"room": "14"}).json()
    client.post(f"/calls/{second['id']}/score", json={"urgency": 4, "category": "fall"})

    listed = client.get("/alerts").json()
    assert [a["call_id"] for a in listed] == [second["id"], first["id"]]
