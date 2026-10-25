"""SpacetimeDB-backed store: write-through to the server, reads from an in-memory mirror.

Reads never touch the network. Every `save` updates the mirror, then POSTs the matching
reducer (`/v1/database/{db}/call/{reducer}`, JSON array of positional args) with a hard 2 s
timeout. A failed write is logged and queued (bounded); the queue is retried, oldest first,
at the start of the next save. Nothing here raises into services after construction.
`hydrate()` loads rows over the SQL route into the mirror and raises if the server is down.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import Any, Generic, TypeVar

import httpx
from pydantic import BaseModel

from bellhop.adapters.memory_store import InMemoryStore
from bellhop.domain import (
    Alert,
    Call,
    Nurse,
    Resident,
    Robot,
    RobotStatus,
    Turn,
    Urgency,
    Visit,
)

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 2.0

# Column order is the reducer argument order and the table's declaration order in
# spacetimedb/src/index.ts. Keep the two in sync.
COLUMNS: dict[str, tuple[str, ...]] = {
    "call": (
        "id",
        "room",
        "resident_id",
        "urgency",
        "category",
        "status",
        "summary",
        "assigned_to",
        "robot_id",
        "nurse_tasks",
        "created_at",
        "assigned_at",
        "first_response_at",
        "resolved_at",
        "resolved_by_robot",
    ),
    "resident": ("id", "name", "room", "risk_flags", "birth_year"),
    "nurse": ("id", "name", "on_shift", "open_tasks"),
    "robot": ("id", "status", "battery", "room", "target"),
    "alert": ("id", "call_id", "nurse_id", "level", "message", "created_at", "acked_at"),
    "visit": (
        "id",
        "call_id",
        "resident_id",
        "robot_id",
        "resolved_by_robot",
        "rating",
        "mood",
        "nurse_urgency_override",
    ),
}
# `append_turn(call_id, seq, speaker, text, at)`; the module derives id "{call_id}:{seq}".
TURN_COLUMNS = ("id", "call_id", "seq", "speaker", "text", "at")


def _s(value: str | None) -> str:
    return value or ""


def _n(value: int | None) -> int:
    return int(value) if value else 0


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _csv(values: Any) -> str:
    return ",".join(sorted(values))


def _unsv(value: str) -> list[str]:
    return [v for v in value.split(",") if v]


def _dt(value: str) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _tri(value: bool | None) -> int:
    """None -> 0, False -> 1, True -> 2 (the module has no optional column on this path)."""
    return 0 if value is None else 2 if value else 1


def _untri(value: int) -> bool | None:
    return None if not value else value == 2


def _call_args(c: Call) -> list[Any]:
    return [
        c.id,
        c.room,
        _s(c.resident_id),
        _n(c.urgency),
        _s(c.category),
        c.status.value,
        _s(c.summary),
        ",".join(c.assigned_to),
        _s(c.robot_id),
        _csv(c.nurse_tasks),
        _iso(c.created_at),
        _iso(c.assigned_at),
        _iso(c.first_response_at),
        _iso(c.resolved_at),
        _tri(c.resolved_by_robot),
    ]


def _call_from(r: dict[str, Any], turns: list[Turn]) -> Call:
    return Call(
        id=r["id"],
        room=r["room"],
        resident_id=r["resident_id"] or None,
        urgency=Urgency(r["urgency"]) if r["urgency"] else None,
        category=r["category"] or None,
        status=r["status"],
        transcript=turns,
        summary=r["summary"] or None,
        assigned_to=_unsv(r["assigned_to"]),
        robot_id=r["robot_id"] or None,
        nurse_tasks=set(_unsv(r["nurse_tasks"])),
        created_at=_dt(r["created_at"]),
        assigned_at=_dt(r["assigned_at"]),
        first_response_at=_dt(r["first_response_at"]),
        resolved_at=_dt(r["resolved_at"]),
        resolved_by_robot=_untri(r.get("resolved_by_robot", 0)),
    )


def _resident_args(r: Resident) -> list[Any]:
    return [r.id, r.name, r.room, _csv(r.risk_flags), _n(r.birth_year)]


def _resident_from(r: dict[str, Any]) -> Resident:
    return Resident(
        id=r["id"],
        name=r["name"],
        room=r["room"],
        risk_flags=set(_unsv(r["risk_flags"])),
        birth_year=r["birth_year"] or None,
    )


def _nurse_args(n: Nurse) -> list[Any]:
    return [n.id, n.name, n.on_shift, n.open_tasks]


def _nurse_from(r: dict[str, Any]) -> Nurse:
    return Nurse(id=r["id"], name=r["name"], on_shift=r["on_shift"], open_tasks=r["open_tasks"])


def _robot_args(r: Robot) -> list[Any]:
    return [r.id, r.status.value, r.battery, _s(r.room), _s(r.target)]


def _robot_from(r: dict[str, Any]) -> Robot:
    return Robot(
        id=r["id"],
        status=RobotStatus(r["status"]),
        battery=r["battery"],
        room=r["room"] or None,
        target=r.get("target", "") or None,
    )


def _alert_args(a: Alert) -> list[Any]:
    return [
        a.id,
        a.call_id,
        _s(a.nurse_id),
        int(a.level),
        a.message,
        _iso(a.created_at),
        _iso(a.acked_at),
    ]


def _alert_from(r: dict[str, Any]) -> Alert:
    return Alert(
        id=r["id"],
        call_id=r["call_id"],
        nurse_id=r["nurse_id"] or None,
        level=Urgency(r["level"]),
        message=r["message"],
        created_at=_dt(r["created_at"]),
        acked_at=_dt(r["acked_at"]),
    )


def _visit_args(v: Visit) -> list[Any]:
    return [
        v.id,
        v.call_id,
        _s(v.resident_id),
        _s(v.robot_id),
        v.resolved_by_robot,
        _n(v.rating),
        _s(v.mood),
        _n(v.nurse_urgency_override),
    ]


def _visit_from(r: dict[str, Any]) -> Visit:
    return Visit(
        id=r["id"],
        call_id=r["call_id"],
        resident_id=r["resident_id"] or None,
        robot_id=r["robot_id"] or None,
        resolved_by_robot=r["resolved_by_robot"],
        rating=r["rating"] or None,
        mood=r["mood"] or None,
        nurse_urgency_override=(
            Urgency(r["nurse_urgency_override"]) if r["nurse_urgency_override"] else None
        ),
    )


class _Client:
    """Minimal SpacetimeDB HTTP client. Raises httpx.HTTPError on any failure."""

    def __init__(self, url: str, db: str, token: str | None, http: httpx.Client) -> None:
        self._base = f"{url.rstrip('/')}/v1/database/{db}"
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = http

    def call(self, reducer: str, args: list[Any]) -> None:
        resp = self._http.post(
            f"{self._base}/call/{reducer}",
            json=args,
            headers=self._headers,
            timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()

    def select_all(self, table: str) -> list[dict[str, Any]]:
        resp = self._http.post(
            f"{self._base}/sql",
            content=f"SELECT * FROM {table}",
            headers=self._headers,
            timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        (result,) = resp.json()
        names = [
            e["name"]["some"] if isinstance(e["name"], dict) else e["name"]
            for e in result["schema"]["elements"]
        ]
        return [dict(zip(names, row, strict=True)) for row in result["rows"]]


class _Writer:
    """Bounded retry queue in front of `_Client.call`. Never raises."""

    def __init__(self, client: _Client, max_queue: int) -> None:
        self._client = client
        self._queue: deque[tuple[str, list[Any]]] = deque()
        self._max = max_queue

    @property
    def pending(self) -> int:
        return len(self._queue)

    def flush(self) -> None:
        while self._queue:
            reducer, args = self._queue[0]
            if not self._try(reducer, args):
                return
            self._queue.popleft()

    def send(self, reducer: str, args: list[Any]) -> None:
        if self._queue:  # keep order: retry the backlog first, queue behind it on failure
            self.flush()
        if self._queue or not self._try(reducer, args):
            self._enqueue(reducer, args)

    def _try(self, reducer: str, args: list[Any]) -> bool:
        try:
            self._client.call(reducer, args)
        except httpx.HTTPError as exc:
            log.warning("spacetimedb %s failed (%s); queued for retry", reducer, type(exc).__name__)
            return False
        return True

    def _enqueue(self, reducer: str, args: list[Any]) -> None:
        if len(self._queue) >= self._max:
            dropped, _ = self._queue.popleft()
            log.warning("spacetimedb retry queue full; dropped oldest write (%s)", dropped)
        self._queue.append((reducer, args))


M = TypeVar("M", bound=BaseModel)


class _Through(Generic[M]):  # noqa: UP046
    """Wraps a mirror table: reads delegate, `save` also writes through."""

    def __init__(self, mirror: Any, write: Callable[[M], None]) -> None:
        self._mirror = mirror
        self._write = write

    def save(self, item: M) -> None:
        self._mirror.save(item)
        self._write(item)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._mirror, name)


class Link:
    """What the other persistent stores need from the server: queued writes and full-table reads."""

    def __init__(self, client: _Client, writer: _Writer) -> None:
        self._client = client
        self._writer = writer

    def write(self, reducer: str, args: list[Any]) -> None:
        self._writer.send(reducer, args)

    def select_all(self, table: str) -> list[dict[str, Any]]:
        return self._client.select_all(table)


class SpacetimeDBStore:
    def __init__(
        self,
        url: str,
        db: str,
        token: str | None = None,
        *,
        client: httpx.Client | None = None,
        max_queue: int = 500,
    ) -> None:
        self._client = _Client(url, db, token, client or httpx.Client())
        self._writer = _Writer(self._client, max_queue)
        self._sent_turns: dict[str, int] = {}
        mirror = self._mirror = InMemoryStore()
        w = self._writer

        def simple(reducer: str, args: Callable[[Any], list[Any]]) -> Callable[[Any], None]:
            return lambda item: w.send(reducer, args(item))

        self.calls = _Through[Call](mirror.calls, self._write_call)
        self.residents = _Through[Resident](
            mirror.residents, simple("save_resident", _resident_args)
        )
        self.nurses = _Through[Nurse](mirror.nurses, simple("save_nurse", _nurse_args))
        self.robots = _Through[Robot](mirror.robots, simple("save_robot", _robot_args))
        self.visits = _Through[Visit](mirror.visits, simple("save_visit", _visit_args))
        self.alerts = _Through[Alert](mirror.alerts, simple("save_alert", _alert_args))

    @property
    def link(self) -> Link:
        """Shares this store's connection and write queue with the memory and care stores."""
        return Link(self._client, self._writer)

    @property
    def pending(self) -> int:
        return self._writer.pending

    def flush(self) -> None:
        self._writer.flush()

    def _write_call(self, call: Call) -> None:
        self._writer.send("save_call", _call_args(call))
        sent = self._sent_turns.get(call.id, 0)
        for seq in range(sent, len(call.transcript)):
            t = call.transcript[seq]
            self._writer.send("append_turn", [call.id, seq, t.speaker, t.text, _iso(t.at)])
        self._sent_turns[call.id] = len(call.transcript)

    def hydrate(self) -> int:
        """Load all rows into the mirror (no write-back). Raises httpx.HTTPError if down."""
        c = self._client
        turns: dict[str, list[tuple[int, Turn]]] = {}
        for r in c.select_all("call_turn"):
            turn = Turn(speaker=r["speaker"], text=r["text"], at=_dt(r["at"]))
            turns.setdefault(r["call_id"], []).append((r["seq"], turn))
        count = 0
        loaders: list[tuple[str, Callable[[dict[str, Any]], BaseModel], Any]] = [
            ("resident", _resident_from, self._mirror.residents),
            ("nurse", _nurse_from, self._mirror.nurses),
            ("robot", _robot_from, self._mirror.robots),
            ("alert", _alert_from, self._mirror.alerts),
            ("visit", _visit_from, self._mirror.visits),
        ]
        for row in c.select_all("call"):
            ordered = [t for _, t in sorted(turns.get(row["id"], []), key=lambda p: p[0])]
            self._mirror.calls.save(_call_from(row, ordered))
            self._sent_turns[row["id"]] = len(ordered)
            count += 1
        for table, build, mirror_table in loaders:
            for row in c.select_all(table):
                mirror_table.save(build(row))
                count += 1
        return count
