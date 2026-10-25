import json

import httpx
import pytest
from fastapi.testclient import TestClient

from bellhop.adapters.http_robot_gateway import HttpRobotGateway
from bellhop.adapters.robot_gateway import RecordingRobotGateway
from bellhop.api.app import create_app
from bellhop.container import Settings, build_container


@pytest.fixture
def container():
    return build_container(Settings(seed_demo=True, guard_timeouts=False))


@pytest.fixture
def client(container) -> TestClient:
    return TestClient(create_app(container))


def test_navigate_sends_opaque_target_marks_robot_busy_and_emits_update(client, container):
    stream_client = container.events.connect()

    response = client.post("/robots/robot_1/navigate", json={"target": "  210  "})

    assert response.status_code == 200
    assert response.json()["id"] == "robot_1"
    assert response.json()["status"] == "busy"
    assert response.json()["room"] == "lobby"  # target is not claimed as a physical location
    assert response.json()["target"] == "210"
    assert isinstance(container.gateway, RecordingRobotGateway)
    assert container.gateway.commands[-1] == ("go_to", "robot_1", "210")
    message = stream_client.pop()
    assert message is not None and message.name == "robot.updated"
    assert json.loads(container.events.frame(message).split("data: ", 1)[1]) == {
        "robot_id": "robot_1",
        "robot": response.json(),
    }


def test_follow_marker_keeps_a_moving_marker_separate_from_room_arrival(client, container):
    response = client.post("/robots/robot_1/follow-marker", json={"target": "208"})

    assert response.status_code == 200
    assert response.json()["status"] == "busy"
    assert response.json()["room"] == "lobby"
    assert response.json()["target"] == "208"
    assert isinstance(container.gateway, RecordingRobotGateway)
    assert container.gateway.commands[-1] == ("follow_marker", "robot_1", "208")


def test_stop_stops_robot_marks_it_idle_and_emits_update(client, container):
    client.post("/robots/robot_1/navigate", json={"target": "210"})
    stream_client = container.events.connect()

    response = client.post("/robots/robot_1/stop")

    assert response.status_code == 200
    assert response.json()["status"] == "idle"
    assert response.json()["target"] is None
    assert container.gateway.commands[-1] == ("stop", "robot_1", "")
    message = stream_client.pop()
    assert message is not None and message.name == "robot.updated"


@pytest.mark.parametrize("target", ["", "   ", "x" * 33])
def test_navigate_validates_a_nonempty_bounded_target(client, target):
    response = client.post("/robots/robot_1/navigate", json={"target": target})

    assert response.status_code == 422


def test_navigate_rejects_unknown_or_unavailable_robot(client):
    assert client.post("/robots/not_here/navigate", json={"target": "210"}).status_code == 404
    report = client.put("/robots/robot_1", json={"status": "charging", "battery": 1})
    assert report.status_code == 200

    response = client.post("/robots/robot_1/navigate", json={"target": "210"})

    assert response.status_code == 409
    assert "not idle" in response.json()["detail"]


def test_navigation_obeys_existing_api_key_authentication():
    secured = TestClient(create_app(build_container(Settings(seed_demo=True, api_key="demo-key"))))

    assert secured.post("/robots/robot_1/navigate", json={"target": "210"}).status_code == 401
    assert (
        secured.post(
            "/robots/robot_1/navigate",
            json={"target": "210"},
            headers={"X-API-Key": "demo-key"},
        ).status_code
        == 200
    )


def test_navigation_gateway_failure_returns_503_without_claiming_movement():
    container = build_container(
        Settings(seed_demo=True, robot_url="http://pi.test:8080", guard_timeouts=False)
    )
    assert isinstance(container.gateway, HttpRobotGateway)
    transport = httpx.MockTransport(lambda _: httpx.Response(503))
    container.gateway._client = httpx.Client(transport=transport)
    client = TestClient(create_app(container))

    response = client.post("/robots/robot_1/navigate", json={"target": "210"})

    assert response.status_code == 503
    robot = client.get("/robots").json()[0]
    assert robot["status"] == "idle"
    assert robot["target"] is None


def test_pi_target_report_preserves_an_omitted_dashboard_target_and_clears_on_arrival(client):
    """Only the Pi reports target state, so a dashboard-style report cannot erase it by omission."""
    client.post("/robots/robot_1/navigate", json={"target": "210"})

    omitted = client.put(
        "/robots/robot_1", json={"status": "busy", "battery": 0.9, "room": "lobby"}
    )
    assert omitted.status_code == 200
    assert omitted.json()["target"] == "210"

    arrived = client.put(
        "/robots/robot_1",
        json={"status": "idle", "battery": 0.9, "room": "12", "target": None},
    )
    assert arrived.status_code == 200
    assert arrived.json()["room"] == "12"
    assert arrived.json()["target"] is None
