import time

import httpx
import pytest
from fastapi.testclient import TestClient

from bellhop.adapters.http_robot_gateway import HttpRobotGateway
from bellhop.api.app import create_app
from bellhop.container import Settings, build_container


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(build_container(Settings(seed_demo=True))))


def put(client, robot_id="robot_1", **body):
    body.setdefault("status", "idle")
    body.setdefault("battery", 0.8)
    return client.put(f"/robots/{robot_id}", json=body)


def test_list_robots_shows_seeded_robot(client):
    robots = client.get("/robots").json()
    assert [r["id"] for r in robots] == ["robot_1"]


def test_put_updates_existing_robot(client):
    r = put(client, status="charging", battery=0.5, room="dock")
    assert r.status_code == 200
    assert r.json() == {"id": "robot_1", "status": "charging", "battery": 0.5, "room": "dock"}
    assert client.get("/robots").json()[0]["status"] == "charging"


def test_put_unknown_robot_creates_it(client):
    assert put(client, "robot_9").status_code == 200
    assert {r["id"] for r in client.get("/robots").json()} == {"robot_1", "robot_9"}


@pytest.mark.parametrize("battery", [-0.1, 1.5])
def test_battery_out_of_range_is_422(client, battery):
    assert put(client, battery=battery).status_code == 422


def test_bad_status_is_422(client):
    assert put(client, status="asleep").status_code == 422


@pytest.mark.parametrize("status", ["charging", "fault"])
def test_unavailable_robot_gets_no_new_calls(client, status):
    first = client.post("/calls", json={"room": "14"}).json()
    assert first["robot_id"] == "robot_1"
    put(client, status=status)
    second = client.post("/calls", json={"room": "14"}).json()
    assert second["robot_id"] is None
    assert second["assigned_to"] == ["nurse_priya"] or second["assigned_to"] == ["nurse_sam"]


def test_idle_report_does_not_free_robot_with_open_call(client):
    call = client.post("/calls", json={"room": "14"}).json()
    r = put(client, status="idle", battery=0.7, room="14")
    assert r.status_code == 200
    assert r.json()["status"] == "busy"  # status ignored, other fields still applied
    assert r.json()["battery"] == 0.7
    other = client.post("/calls", json={"room": "14"}).json()
    assert other["robot_id"] is None
    client.post(f"/calls/{call['id']}/resolve", json={})
    assert client.get("/robots").json()[0]["status"] == "idle"


def test_idle_report_frees_robot_once_call_resolved(client):
    call = client.post("/calls", json={"room": "14"}).json()
    client.post(f"/calls/{call['id']}/resolve", json={})
    put(client, status="charging")
    assert put(client, status="idle").json()["status"] == "idle"


def test_container_uses_http_gateway_when_robot_url_set():
    c = build_container(Settings(robot_url="http://pi.local:8080", guard_timeouts=False))
    assert isinstance(c.dispatcher._gateway, HttpRobotGateway)


def test_failing_robot_http_falls_back_to_nurse_and_never_leaks():
    c = build_container(Settings(seed_demo=True, robot_url="http://pi.local:8080"))
    c.guarded_gateway._inner._client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(503))
    )
    call = TestClient(create_app(c)).post("/calls", json={"room": "12"}).json()
    assert call["robot_id"] is None and call["status"] == "assigned"


def test_failing_go_to_pages_a_nurse_and_stops_the_robot_for_a_resident_without_risk_flags():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(503 if request.url.path == "/go_to" else 200)

    c = build_container(Settings(seed_demo=True, robot_url="http://pi.local:8080"))
    c.guarded_gateway._inner._client = httpx.Client(transport=httpx.MockTransport(handler))
    client = TestClient(create_app(c))
    resident = next(r for r in client.get("/residents").json() if r["room"] == "14")
    assert resident["risk_flags"] == []
    call = client.post("/calls", json={"room": "14"}).json()
    assert call["robot_id"] is None and len(call["assigned_to"]) == 1
    assert call["urgency"] is None
    [alert] = client.get("/alerts").json()
    assert alert["call_id"] == call["id"] and alert["nurse_id"] == call["assigned_to"][0]
    assert alert["level"] == 3 and "robot" in alert["message"].lower()
    deadline = time.monotonic() + 2.0
    while "/stop" not in seen and time.monotonic() < deadline:
        time.sleep(0.01)
    assert seen[0] == "/go_to" and "/stop" in seen
    assert client.get("/robots").json()[0]["status"] == "idle"


def test_settings_from_env_reads_robot_url(monkeypatch):
    monkeypatch.setenv("BELLHOP_ROBOT_URL", "http://pi.local:8080")
    assert Settings.from_env().robot_url == "http://pi.local:8080"
