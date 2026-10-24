"""SpacetimeDBStore: contract tests shared with InMemoryStore, plus write-through behaviour.

No network: an httpx.MockTransport plays the SpacetimeDB HTTP API.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import httpx
import pytest

from bellhop.adapters.memory_store import InMemoryStore
from bellhop.adapters.spacetimedb_store import SpacetimeDBStore
from bellhop.container import Settings, build_container
from bellhop.domain import (
    Alert,
    Call,
    CallStatus,
    Nurse,
    Resident,
    Robot,
    RobotStatus,
    Urgency,
    Visit,
)

URL = "http://stdb.test:3000"
DB = "bellhop"
TOKEN = "tok-secret"
TABLE_REDUCERS = {
    "call": "save_call",
    "resident": "save_resident",
    "nurse": "save_nurse",
    "robot": "save_robot",
    "alert": "save_alert",
    "visit": "save_visit",
}


class FakeServer:
    """Records requests; optionally stores reducer args so SQL can read them back."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.fail = False
        self.tables: dict[str, dict[str, list]] = {}

    def calls(self) -> list[tuple[str, list]]:
        return [
            (r.url.path.rsplit("/", 1)[-1], json.loads(r.content))
            for r in self.requests
            if "/call/" in r.url.path
        ]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            raise httpx.ConnectError("down", request=request)
        path = request.url.path
        if "/call/" in path:
            self._apply(path.rsplit("/", 1)[-1], json.loads(request.content))
            return httpx.Response(200)
        if path.endswith("/sql"):
            table = request.content.decode().rsplit(" ", 1)[-1].strip().rstrip(";")
            return httpx.Response(200, json=[self._select(table)])
        return httpx.Response(404)

    def _apply(self, reducer: str, args: list) -> None:
        from bellhop.adapters import spacetimedb_store as mod

        if reducer == "append_turn":
            call_id, seq, *rest = args
            self.tables.setdefault("call_turn", {})[f"{call_id}:{seq}"] = [
                f"{call_id}:{seq}",
                call_id,
                seq,
                *rest,
            ]
            return
        table = next(t for t, r in TABLE_REDUCERS.items() if r == reducer)
        assert len(args) == len(mod.COLUMNS[table]), (reducer, args)
        self.tables.setdefault(table, {})[args[0]] = args

    def _select(self, table: str) -> dict:
        from bellhop.adapters import spacetimedb_store as mod

        cols = mod.COLUMNS[table] if table != "call_turn" else mod.TURN_COLUMNS
        return {
            "schema": {
                "elements": [{"name": {"some": c}, "algebraic_type": {"String": []}} for c in cols]
            },
            "rows": list(self.tables.get(table, {}).values()),
        }


def _make(server: FakeServer, **kw) -> SpacetimeDBStore:
    client = httpx.Client(transport=httpx.MockTransport(server))
    return SpacetimeDBStore(URL, DB, TOKEN, client=client, **kw)


@pytest.fixture
def server() -> FakeServer:
    return FakeServer()


@pytest.fixture(params=["memory", "spacetimedb"])
def store(request, server):
    if request.param == "memory":
        return InMemoryStore()
    return _make(server)


def _call(clock, id="c1", room="12") -> Call:
    return Call(id=id, room=room, created_at=clock.now())


# ---- contract: same behaviour as test_memory_store.py -------------------------------


def test_save_is_upsert_and_get_returns_saved_call(store, clock):
    call = _call(clock)
    store.calls.save(call)
    call.room = "13"
    store.calls.save(call)
    assert store.calls.get("c1").room == "13"
    assert len(store.calls.list_all()) == 1


def test_get_unknown_returns_none(store):
    assert store.calls.get("nope") is None


def test_get_returns_copy_so_mutation_needs_save(store, clock):
    store.calls.save(_call(clock))
    store.calls.get("c1").room = "99"
    assert store.calls.get("c1").room == "12"


def test_saving_stores_a_snapshot(store, clock):
    call = _call(clock)
    store.calls.save(call)
    call.room = "99"
    assert store.calls.get("c1").room == "12"


def test_list_open_excludes_resolved_and_closed(store, clock):
    for id, status in [
        ("a", CallStatus.RINGING),
        ("b", CallStatus.RESOLVED),
        ("c", CallStatus.CLOSED),
        ("d", CallStatus.ESCALATED),
    ]:
        call = _call(clock, id)
        call.status = status
        store.calls.save(call)
    assert sorted(c.id for c in store.calls.list_open()) == ["a", "d"]


def test_resident_by_room(store):
    store.residents.save(Resident(id="r1", name="Ada", room="12"))
    assert store.residents.by_room("12").id == "r1"
    assert store.residents.by_room("13") is None
    assert store.residents.get("r1").name == "Ada"


def test_list_on_shift_nurses_only(store):
    store.nurses.save(Nurse(id="n1", name="A"))
    store.nurses.save(Nurse(id="n2", name="B", on_shift=False))
    assert [n.id for n in store.nurses.list_on_shift()] == ["n1"]


def test_robot_save_get_list(store):
    store.robots.save(Robot(id="b1"))
    assert store.robots.get("b1").battery == 1.0
    assert [r.id for r in store.robots.list_all()] == ["b1"]


def test_visit_for_call_and_list(store):
    store.visits.save(Visit(id="v1", call_id="c1", resident_id=None, robot_id=None))
    assert store.visits.for_call("c1").id == "v1"
    assert store.visits.for_call("zzz") is None
    assert len(store.visits.list_all()) == 1


def test_alerts_for_call(store, clock):
    for id, call_id in [("a1", "c1"), ("a2", "c1"), ("a3", "c2")]:
        store.alerts.save(
            Alert(
                id=id,
                call_id=call_id,
                nurse_id=None,
                level=Urgency.EMERGENCY,
                message="m",
                created_at=clock.now(),
            )
        )
    assert [a.id for a in store.alerts.for_call("c1")] == ["a1", "a2"]
    assert store.alerts.get("a3").call_id == "c2"


# ---- write-through request shape ----------------------------------------------------


def test_reads_never_touch_the_network(server, clock):
    store = _make(server)
    store.calls.save(_call(clock))
    server.requests.clear()
    store.calls.get("c1")
    store.calls.list_all()
    store.calls.list_open()
    assert server.requests == []


def test_save_robot_posts_positional_args_to_reducer_route(server):
    store = _make(server)
    store.robots.save(Robot(id="b1", status=RobotStatus.BUSY, battery=0.5, room="12"))
    (req,) = server.requests
    assert req.method == "POST"
    assert str(req.url) == f"{URL}/v1/database/{DB}/call/save_robot"
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(req.content) == ["b1", "busy", 0.5, "12"]


def test_robot_without_room_sends_empty_string(server):
    _make(server).robots.save(Robot(id="b1"))
    assert server.calls() == [("save_robot", ["b1", "idle", 1.0, ""])]


def test_no_token_means_no_authorization_header(server):
    store = SpacetimeDBStore(
        URL, DB, None, client=httpx.Client(transport=httpx.MockTransport(server))
    )
    store.robots.save(Robot(id="b1"))
    assert "authorization" not in server.requests[0].headers


def test_every_request_has_a_hard_two_second_timeout(server):
    _make(server).robots.save(Robot(id="b1"))
    timeout = server.requests[0].extensions["timeout"]
    assert set(timeout.values()) == {2.0}


def test_save_call_flattens_sentinels_and_sets(server, clock):
    store = _make(server)
    call = _call(clock)
    call.urgency = Urgency.NURSE_SOON
    call.assigned_to = ["b1", "n2"]
    call.nurse_tasks = {"n2", "n1"}
    store.calls.save(call)
    ((reducer, args),) = server.calls()
    assert reducer == "save_call"
    assert args == [
        "c1",
        "12",
        "",
        3,
        "",
        "ringing",
        "",
        "b1,n2",
        "",
        "n1,n2",
        call.created_at.isoformat(),
        "",
        "",
        "",
        0,  # resolved_by_robot: not decided yet
    ]


def test_save_call_sends_only_new_turns(server, clock):
    store = _make(server)
    call = _call(clock)
    call.add_turn("resident", "help", clock.now())
    store.calls.save(call)
    call.add_turn("robot", "coming", clock.now())
    store.calls.save(call)
    turns = [a for r, a in server.calls() if r == "append_turn"]
    assert [(a[0], a[1], a[2], a[3]) for a in turns] == [
        ("c1", 0, "resident", "help"),
        ("c1", 1, "robot", "coming"),
    ]


def test_resident_nurse_alert_visit_shapes(server, clock):
    store = _make(server)
    store.residents.save(Resident(id="r1", name="Ada", room="12", risk_flags={"falls", "ad"}))
    store.nurses.save(Nurse(id="n1", name="Bo", on_shift=False, open_tasks=2))
    store.alerts.save(
        Alert(
            id="a1",
            call_id="c1",
            nurse_id=None,
            level=Urgency.EMERGENCY,
            message="m",
            created_at=clock.now(),
        )
    )
    store.visits.save(Visit(id="v1", call_id="c1", resident_id="r1", robot_id="b1", rating=4))
    got = dict(server.calls())
    assert got["save_resident"] == ["r1", "Ada", "12", "ad,falls", 0]
    assert got["save_nurse"] == ["n1", "Bo", False, 2]
    assert got["save_alert"] == ["a1", "c1", "", 4, "m", clock.now().isoformat(), ""]
    assert got["save_visit"] == ["v1", "c1", "r1", "b1", False, 4, "", 0]


# ---- failure handling: log, queue, retry --------------------------------------------


def test_failed_write_is_logged_not_raised_and_mirror_still_updated(server, caplog):
    store = _make(server)
    server.fail = True
    with caplog.at_level(logging.WARNING):
        store.robots.save(Robot(id="b1"))
    assert store.robots.get("b1") is not None
    assert "save_robot" in caplog.text
    assert TOKEN not in caplog.text


def test_http_error_status_is_treated_as_failure(clock):
    def handler(request):
        return httpx.Response(500)

    store = SpacetimeDBStore(
        URL, DB, None, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    store.robots.save(Robot(id="b1"))
    assert store.pending == 1


def test_timeout_is_queued_not_raised():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    store = SpacetimeDBStore(
        URL, DB, None, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    store.robots.save(Robot(id="b1"))
    assert store.pending == 1


def test_queued_writes_retry_in_order_before_the_next_save(server):
    store = _make(server)
    server.fail = True
    store.robots.save(Robot(id="b1"))
    store.robots.save(Robot(id="b2"))
    assert store.pending == 2
    server.fail = False
    server.requests.clear()
    store.robots.save(Robot(id="b3"))
    assert [a[0] for _, a in server.calls()] == ["b1", "b2", "b3"]
    assert store.pending == 0


def test_dead_server_costs_one_attempt_per_save(server):
    store = _make(server)
    server.fail = True
    store.robots.save(Robot(id="b1"))
    server.requests.clear()
    store.robots.save(Robot(id="b2"))
    assert len(server.requests) == 1  # retry head of queue; new write is queued untried
    assert store.pending == 2


def test_retry_stops_at_first_failure_and_keeps_the_rest(server):
    store = _make(server)
    server.fail = True
    for i in range(3):
        store.robots.save(Robot(id=f"b{i}"))
    store.robots.save(Robot(id="b9"))
    assert store.pending == 4


def test_queue_is_bounded_and_drops_oldest(server, caplog):
    store = _make(server, max_queue=2)
    server.fail = True
    with caplog.at_level(logging.WARNING):
        for i in range(4):
            store.robots.save(Robot(id=f"b{i}"))
    assert store.pending == 2
    server.fail = False
    server.requests.clear()
    store.flush()
    assert [a[0] for _, a in server.calls()] == ["b2", "b3"]
    assert "dropped" in caplog.text


# ---- hydrate ------------------------------------------------------------------------


def test_hydrate_round_trips_every_aggregate(server, clock):
    writer = _make(server)
    call = _call(clock)
    call.urgency = Urgency.EMERGENCY
    call.category = "fall"
    call.summary = "s"
    call.assigned_to = ["b1"]
    call.robot_id = "b1"
    call.nurse_tasks = {"n1"}
    call.resident_id = "r1"
    call.assigned_at = datetime(2026, 10, 24, 9, 1, tzinfo=UTC)
    call.add_turn("resident", "help me", clock.now())
    call.add_turn("robot", "coming, with a comma", clock.now())
    writer.calls.save(call)
    writer.residents.save(
        Resident(id="r1", name="Ada", room="12", risk_flags={"falls"}, birth_year=1940)
    )
    writer.nurses.save(Nurse(id="n1", name="Bo", on_shift=False, open_tasks=1))
    writer.robots.save(Robot(id="b1", status=RobotStatus.CHARGING, battery=0.25, room="12"))
    alert = Alert(
        id="a1",
        call_id="c1",
        nurse_id="n1",
        level=Urgency.NURSE_SOON,
        message="m",
        created_at=clock.now(),
        acked_at=clock.now(),
    )
    writer.alerts.save(alert)
    visit = Visit(
        id="v1",
        call_id="c1",
        resident_id="r1",
        robot_id="b1",
        resolved_by_robot=True,
        rating=5,
        mood="happy",
        nurse_urgency_override=Urgency.ROUTINE,
    )
    writer.visits.save(visit)

    reader = _make(server)
    reader.hydrate()

    assert reader.calls.get("c1") == call
    assert reader.residents.get("r1") == writer.residents.get("r1")
    assert reader.nurses.get("n1") == writer.nurses.get("n1")
    assert reader.robots.get("b1") == writer.robots.get("b1")
    assert reader.alerts.get("a1") == alert
    assert reader.visits.for_call("c1") == visit


def test_hydrate_maps_sentinels_back_to_none(server, clock):
    writer = _make(server)
    writer.calls.save(_call(clock))
    writer.robots.save(Robot(id="b1"))
    writer.alerts.save(
        Alert(
            id="a1",
            call_id="c1",
            nurse_id=None,
            level=Urgency.EMERGENCY,
            message="m",
            created_at=clock.now(),
        )
    )
    reader = _make(server)
    reader.hydrate()
    got = reader.calls.get("c1")
    assert (got.urgency, got.resident_id, got.assigned_at, got.assigned_to) == (
        None,
        None,
        None,
        [],
    )
    assert reader.robots.get("b1").room is None
    assert reader.alerts.get("a1").nurse_id is None


def test_hydrate_does_not_write_back_and_does_not_resend_turns(server, clock):
    writer = _make(server)
    call = _call(clock)
    call.add_turn("resident", "hi", clock.now())
    writer.calls.save(call)
    reader = _make(server)
    reader.hydrate()
    server.requests.clear()
    got = reader.calls.get("c1")
    got.add_turn("robot", "hello", clock.now())
    reader.calls.save(got)
    turns = [a for r, a in server.calls() if r == "append_turn"]
    assert [(a[1], a[3]) for a in turns] == [(1, "hello")]
    assert [r for r, _ in server.calls()].count("save_call") == 1


def test_hydrate_queries_sql_route_with_auth(server):
    store = _make(server)
    store.hydrate()
    sql = [r for r in server.requests if r.url.path.endswith("/sql")]
    assert {r.content.decode() for r in sql} >= {"SELECT * FROM call", "SELECT * FROM robot"}
    assert all(str(r.url).startswith(f"{URL}/v1/database/{DB}/sql") for r in sql)
    assert all(r.headers["authorization"] == f"Bearer {TOKEN}" for r in sql)


def test_hydrate_raises_when_server_unreachable(server):
    store = _make(server)
    server.fail = True
    with pytest.raises(httpx.HTTPError):
        store.hydrate()


# ---- container ----------------------------------------------------------------------


def test_settings_from_env_reads_spacetimedb_vars(monkeypatch):
    monkeypatch.setenv("BELLHOP_STORE", "spacetimedb")
    monkeypatch.setenv("BELLHOP_STDB_URL", "http://h:1")
    monkeypatch.setenv("BELLHOP_STDB_DB", "mydb")
    monkeypatch.setenv("BELLHOP_STDB_TOKEN", "t")
    s = Settings.from_env()
    assert (s.store, s.spacetimedb_url, s.spacetimedb_db, s.spacetimedb_token) == (
        "spacetimedb",
        "http://h:1",
        "mydb",
        "t",
    )


def test_settings_default_store_is_memory_with_local_stdb_defaults(monkeypatch):
    for k in ("BELLHOP_STORE", "BELLHOP_STDB_URL", "BELLHOP_STDB_DB", "BELLHOP_STDB_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert s.store == "memory"
    assert (s.spacetimedb_url, s.spacetimedb_db, s.spacetimedb_token) == (
        "http://127.0.0.1:3000",
        "bellhop",
        None,
    )


def test_container_falls_back_to_memory_when_server_unreachable(caplog):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(refuse))
    with caplog.at_level(logging.WARNING):
        c = build_container(
            Settings(store="spacetimedb", spacetimedb_token="s3"), stdb_client=client
        )
    assert isinstance(c.store, InMemoryStore)
    assert "falling back" in caplog.text
    assert "s3" not in caplog.text


def test_container_uses_spacetimedb_store_and_hydrates(server, clock):
    _make(server).robots.save(Robot(id="b1"))
    client = httpx.Client(transport=httpx.MockTransport(server))
    c = build_container(
        Settings(store="spacetimedb", spacetimedb_url=URL, spacetimedb_db=DB), stdb_client=client
    )
    assert isinstance(c.store, SpacetimeDBStore)
    assert c.store.robots.get("b1") is not None


def test_unknown_store_still_rejected():
    with pytest.raises(ValueError):
        build_container(Settings(store="nope"))
