"""Staff send a chosen robot to a room: POST /robots/{id}/dispatch."""

import pytest
from fastapi.testclient import TestClient

from bellhop.api.app import create_app
from bellhop.container import Settings, build_container


@pytest.fixture
def container():
    return build_container(Settings(seed_demo=True, guard_timeouts=False))


@pytest.fixture
def client(container) -> TestClient:
    return TestClient(create_app(container))


def report(client, robot_id, status="idle", battery=0.9, room="lobby"):
    r = client.put(f"/robots/{robot_id}", json={"status": status, "battery": battery, "room": room})
    assert r.status_code == 200


def dispatch(client, robot_id="robot_1", room="12"):
    return client.post(f"/robots/{robot_id}/dispatch", json={"room": room})


def test_the_chosen_robot_goes_even_when_another_is_closer(client, container):
    report(client, "robot_2", room="12")  # already standing in the room
    r = dispatch(client, "robot_1", "12")
    assert r.status_code == 201
    call = r.json()
    assert (call["robot_id"], call["room"], call["status"]) == ("robot_1", "12", "robot_en_route")
    assert ("go_to", "robot_1", "12") in container.gateway.commands
    assert all(c[1] != "robot_2" for c in container.gateway.commands if c[0] == "go_to")


def test_the_robot_is_busy_afterwards_and_cannot_be_sent_twice(client):
    assert dispatch(client, "robot_1", "12").status_code == 201
    assert {r["id"]: r["status"] for r in client.get("/robots").json()}["robot_1"] == "busy"
    again = dispatch(client, "robot_1", "14")
    assert again.status_code == 409
    assert "busy" in again.json()["detail"]


def test_the_call_belongs_to_the_resident_of_the_room(client):
    assert dispatch(client, "robot_1", "14").json()["resident_id"] == "res_arthur"


def test_a_place_with_no_resident_works(client):
    call = dispatch(client, "robot_1", "lobby").json()
    assert (call["resident_id"], call["robot_id"]) == (None, "robot_1")


def test_unknown_robot_is_404(client):
    assert dispatch(client, "robot_99").status_code == 404


@pytest.mark.parametrize("status", ["charging", "fault", "busy"])
def test_a_robot_that_is_not_idle_is_409(client, status):
    report(client, "robot_1", status=status)
    r = dispatch(client)
    assert r.status_code == 409 and status in r.json()["detail"]


def test_a_robot_low_on_charge_is_409(client):
    report(client, "robot_1", battery=0.19)
    r = dispatch(client)
    assert r.status_code == 409 and "charge" in r.json()["detail"]


def test_exactly_the_minimum_charge_can_go(client):
    report(client, "robot_1", battery=0.2)
    assert dispatch(client).status_code == 201


def test_a_room_with_an_open_call_is_409(client):
    report(client, "robot_2")
    assert client.post("/calls", json={"room": "12"}).status_code == 201
    r = dispatch(client, "robot_2", "12")
    assert r.status_code == 409 and "open call" in r.json()["detail"]


def test_bad_bodies_are_422(client):
    assert client.post("/robots/robot_1/dispatch", json={"room": ""}).status_code == 422
    assert client.post("/robots/robot_1/dispatch", json={}).status_code == 422
    assert (
        client.post("/robots/robot_1/dispatch", json={"room": "12", "extra": 1}).status_code == 422
    )


def test_dispatching_is_announced_on_the_event_stream_like_any_bell(client, container):
    seen = []
    from bellhop.domain.events import CallAssigned, CallRaised

    container.bus.subscribe(CallRaised, seen.append)
    container.bus.subscribe(CallAssigned, seen.append)
    dispatch(client)
    assert {type(e).__name__ for e in seen} == {"CallRaised", "CallAssigned"}
    assert {e.robot_id for e in seen} == {"robot_1"}


def test_a_robot_that_cannot_be_commanded_is_reported_not_silently_replaced():
    c = build_container(
        Settings(seed_demo=True, guard_timeouts=False, robot_url="http://127.0.0.1:9")
    )
    client = TestClient(create_app(c))
    r = dispatch(client)
    assert r.status_code == 409 and "could not be reached" in r.json()["detail"]
    [call] = c.store.calls.list_all()  # the call exists and a nurse owns it
    assert call.robot_id is None and call.nurse_tasks
