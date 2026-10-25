import json
import math

import httpx
from rover.backend import Backend


def make_backend(handler, api_key: str = "secret"):
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return Backend(
        "http://backend.test", api_key, transport=httpx.MockTransport(record)
    ), seen


def ok(body=None):
    return lambda request: httpx.Response(
        200, json={"id": "c1"} if body is None else body
    )


def test_score_clamps_every_field_and_sends_key():
    backend, seen = make_backend(ok())
    call = backend.score("c1", 7, "x" * 100, "s" * 900, 1.5)
    assert call == {"id": "c1"}
    request = seen[0]
    assert request.method == "POST" and request.url.path == "/calls/c1/score"
    assert request.headers["X-API-Key"] == "secret"
    body = json.loads(request.content)
    assert body["urgency"] == 4
    assert len(body["category"]) == 64
    assert len(body["summary"]) == 300
    assert body["confidence"] == 1.0


def test_score_low_values_and_nan_lean_toward_escalation():
    backend, seen = make_backend(ok())
    backend.score("c1", 0, "pain", "hurts", -0.5)
    backend.score("c1", math.nan, "pain", "hurts", math.nan)
    low, broken = (json.loads(r.content) for r in seen)
    assert (low["urgency"], low["confidence"]) == (1, 0.0)
    assert (broken["urgency"], broken["confidence"]) == (4, 0.0)


def test_no_key_means_no_header():
    backend, seen = make_backend(ok(), api_key="")
    backend.get_call("c1")
    assert "X-API-Key" not in seen[0].headers


def test_in_visit_success():
    backend, seen = make_backend(ok())
    assert backend.in_visit("c1") is True
    assert seen[0].url.path == "/calls/c1/in-visit"


def conflict_then_status(status: str):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(409, json={"detail": "in_visit -> in_visit"})
        return httpx.Response(200, json={"id": "c1", "status": status})

    return handler


def test_in_visit_409_when_already_in_visit_counts_as_success():
    backend, _ = make_backend(conflict_then_status("in_visit"))
    assert backend.in_visit("c1") is True


def test_in_visit_409_for_any_other_state_fails():
    backend, _ = make_backend(conflict_then_status("escalated"))
    assert backend.in_visit("c1") is False


def test_failures_return_empty_values():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    backend, _ = make_backend(refuse)
    assert backend.get_call("c1") is None
    assert backend.calls() == []
    assert backend.in_visit("c1") is False
    assert backend.memory("r1") == []
    assert backend.score("c1", 3, "pain", "hurts", 0.9) is None

    server_error, _ = make_backend(lambda request: httpx.Response(500, text="boom"))
    assert server_error.resolve("c1", by_robot=True) is None
    assert server_error.calls() == []


def test_safe_get_retries_once_after_a_transient_network_failure():
    attempts = 0

    def flaky(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("brief stall", request=request)
        return httpx.Response(200, json=[])

    backend, _ = make_backend(flaky)
    assert backend.calls() == []
    assert attempts == 2


def test_find_assigned_call_picks_newest_active_call_for_this_robot():
    def call(call_id, robot_id, status, hour):
        return {
            "id": call_id,
            "robot_id": robot_id,
            "status": status,
            "created_at": f"2026-10-24T0{hour}:00:00Z",
        }

    calls = [
        call("old", "robot_1", "assigned", 1),
        call("new", "robot_1", "robot_en_route", 2),
        call("done", "robot_1", "resolved", 3),
        call("other", "robot_2", "assigned", 4),
    ]
    backend, _ = make_backend(ok(calls))
    assert backend.find_assigned_call("robot_1")["id"] == "new"
    assert backend.find_assigned_call("robot_3") is None


def test_report_robot_puts_status_target_and_clamps_battery():
    backend, seen = make_backend(ok({"id": "robot_1", "status": "idle"}))
    assert backend.report_robot("robot_1", "busy", 1.3, "lobby", "210") is not None
    backend.report_robot("robot_1", "idle", None, None, None)
    full, unknown = seen
    assert full.method == "PUT" and full.url.path == "/robots/robot_1"
    assert json.loads(full.content) == {
        "status": "busy",
        "battery": 1.0,
        "room": "lobby",
        "target": "210",
    }
    assert json.loads(unknown.content) == {
        "status": "idle",
        "battery": 1.0,
        "room": None,
        "target": None,
    }


def test_turns_resolve_and_triage_failed_requests():
    backend, seen = make_backend(ok())
    backend.add_turn("c1", "resident", "a" * 2500)
    backend.resolve("c1", by_robot=False)
    backend.triage_failed("c1")
    backend.memory("r1", q="tea", k=2)
    turn, resolve, failed, memory = seen
    assert json.loads(turn.content) == {"speaker": "resident", "text": "a" * 2000}
    assert resolve.url.path == "/calls/c1/resolve"
    assert json.loads(resolve.content) == {"by_robot": False}
    assert failed.url.path == "/calls/c1/triage-failed" and failed.content == b""
    assert memory.url.path == "/residents/r1/memory"
    assert dict(memory.url.params) == {"q": "tea", "k": "2"}
