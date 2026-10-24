"""Write-through persistence for memory facts, the review queue, care data and medical history.

These live next to the core store (`spacetimedb_store.py`) and share its connection and write
queue. Reads come from memory; every change is also sent to a reducer, and `hydrate` loads the
tables back when the backend starts. Column order is the reducer argument order and the table's
declaration order in spacetimedb/src/index.ts: keep the two in sync.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from bellhop.adapters.care_store import InMemoryCareStore
from bellhop.adapters.deletable_memory import DeletableLocalMemoryIndex
from bellhop.adapters.local_memory import LocalMemoryIndex
from bellhop.adapters.spacetimedb_store import Link
from bellhop.domain import MemoryFact
from bellhop.domain.care import (
    CareEntry,
    Condition,
    EntryKind,
    FamilyMessage,
    Flag,
    FlagType,
    MedicalRecord,
    MessageDirection,
    Preferences,
)
from bellhop.services.memory_guard import InMemoryPending, PendingFact

log = logging.getLogger(__name__)

DATA_COLUMNS: dict[str, tuple[str, ...]] = {
    "memory_fact": (
        "id",
        "resident_id",
        "text",
        "tags",
        "created_at",
        "source",
        "confidence",
        "quote",
        "call_id",
        "last_confirmed",
        "times_seen",
    ),
    "pending_fact": (
        "id",
        "resident_id",
        "text",
        "tags",
        "source",
        "confidence",
        "quote",
        "call_id",
    ),
    "care_entry": ("id", "resident_id", "call_id", "kind", "value", "note", "at"),
    "flag": ("id", "resident_id", "call_id", "type", "reason", "created_at", "resolved_at"),
    "preferences": (
        "resident_id",
        "hard_of_hearing",
        "quiet_mode",
        "night_mode",
        "favourite_drink",
    ),
    "family_message": ("id", "resident_id", "direction", "text", "created_at"),
    "family_delivery": ("resident_id", "at"),
    "medical_record": (
        "resident_id",
        "conditions",
        "allergies",
        "medicines",
        "mobility",
        "diet",
        "last_review",
        "reviewed_by",
    ),
}


def _s(value: str | None) -> str:
    return value or ""


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _dt(value: str) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _tags(value: str) -> list[str]:
    return [t for t in value.split(",") if t]


# -- memory facts ------------------------------------------------------------------------------
def _fact_args(f: MemoryFact) -> list[Any]:
    return [
        f.id,
        f.resident_id,
        f.text,
        ",".join(f.tags),
        _iso(f.created_at),
        f.source,
        f.confidence,
        _s(f.quote),
        _s(f.call_id),
        _iso(f.last_confirmed),
        f.times_seen,
    ]


def _fact_from(r: dict[str, Any]) -> MemoryFact:
    return MemoryFact(
        id=r["id"],
        resident_id=r["resident_id"],
        text=r["text"],
        tags=_tags(r["tags"]),
        created_at=_dt(r["created_at"]),
        source=r["source"],
        confidence=r["confidence"],
        quote=r["quote"] or None,
        call_id=r["call_id"] or None,
        last_confirmed=_dt(r["last_confirmed"]),
        times_seen=r["times_seen"] or 1,
    )


class PersistentMemoryIndex(DeletableLocalMemoryIndex):
    """The local fact index, saving every add, change and delete to SpacetimeDB."""

    def __init__(self, link: Link) -> None:
        super().__init__()
        self._link = link

    def add(self, fact: MemoryFact) -> None:
        super().add(fact)
        self._link.write("save_memory_fact", _fact_args(fact))

    def update(self, fact: MemoryFact) -> None:
        self._link.write("save_memory_fact", _fact_args(fact))

    def remove(self, fact_id: str) -> bool:
        removed = super().remove(fact_id)
        if removed:
            self._link.write("delete_memory_fact", [fact_id])
        return removed

    def remove_all(self, resident_id: str) -> int:
        count = super().remove_all(resident_id)
        if count:
            self._link.write("delete_resident_memory", [resident_id])
        return count

    def load(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            LocalMemoryIndex.add(self, _fact_from(row))  # into memory only: no write back
        return len(rows)


# -- the nurse review queue --------------------------------------------------------------------
def _pending_args(p: PendingFact) -> list[Any]:
    return [
        p.id,
        p.resident_id,
        p.text,
        ",".join(p.tags),
        p.source,
        p.confidence,
        _s(p.quote),
        _s(p.call_id),
    ]


def _pending_from(r: dict[str, Any]) -> PendingFact:
    return PendingFact(
        id=r["id"],
        resident_id=r["resident_id"],
        text=r["text"],
        tags=tuple(_tags(r["tags"])),
        source=r["source"],
        confidence=r["confidence"],
        quote=r["quote"] or None,
        call_id=r["call_id"] or None,
    )


class PersistentPending(InMemoryPending):
    def __init__(self, link: Link) -> None:
        super().__init__()
        self._link = link

    def add(self, item: PendingFact) -> None:
        super().add(item)
        self._link.write("save_pending_fact", _pending_args(item))

    def remove(self, pending_id: str) -> None:
        super().remove(pending_id)
        self._link.write("delete_pending_fact", [pending_id])

    def load(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            InMemoryPending.add(self, _pending_from(row))
        return len(rows)


# -- care data and medical history -------------------------------------------------------------
def _entry_args(e: CareEntry) -> list[Any]:
    return [e.id, e.resident_id, _s(e.call_id), e.kind.value, e.value or 0.0, e.note, _iso(e.at)]


def _entry_from(r: dict[str, Any]) -> CareEntry:
    return CareEntry(
        id=r["id"],
        resident_id=r["resident_id"],
        call_id=r["call_id"] or None,
        kind=EntryKind(r["kind"]),
        value=r["value"] or None,
        note=r["note"],
        at=_dt(r["at"]),
    )


def _flag_args(f: Flag) -> list[Any]:
    return [
        f.id,
        f.resident_id,
        _s(f.call_id),
        f.type.value,
        f.reason,
        _iso(f.created_at),
        _iso(f.resolved_at),
    ]


def _flag_from(r: dict[str, Any]) -> Flag:
    return Flag(
        id=r["id"],
        resident_id=r["resident_id"],
        call_id=r["call_id"] or None,
        type=FlagType(r["type"]),
        reason=r["reason"],
        created_at=_dt(r["created_at"]),
        resolved_at=_dt(r["resolved_at"]),
    )


def _prefs_args(p: Preferences) -> list[Any]:
    return [p.resident_id, p.hard_of_hearing, p.quiet_mode, p.night_mode, _s(p.favourite_drink)]


def _prefs_from(r: dict[str, Any]) -> Preferences:
    return Preferences(
        resident_id=r["resident_id"],
        hard_of_hearing=r["hard_of_hearing"],
        quiet_mode=r["quiet_mode"],
        night_mode=r["night_mode"],
        favourite_drink=r["favourite_drink"] or None,
    )


def _message_args(m: FamilyMessage) -> list[Any]:
    return [m.id, m.resident_id, m.direction.value, m.text, _iso(m.created_at)]


def _message_from(r: dict[str, Any]) -> FamilyMessage:
    return FamilyMessage(
        id=r["id"],
        resident_id=r["resident_id"],
        direction=MessageDirection(r["direction"]),
        text=r["text"],
        created_at=_dt(r["created_at"]),
    )


def _medical_args(m: MedicalRecord) -> list[Any]:
    return [
        m.resident_id,
        json.dumps([c.model_dump() for c in m.conditions]),
        json.dumps(m.allergies),
        json.dumps(m.medicines),
        m.mobility,
        m.diet,
        _iso(m.last_review),
        m.reviewed_by,
    ]


def _medical_from(r: dict[str, Any]) -> MedicalRecord:
    return MedicalRecord(
        resident_id=r["resident_id"],
        conditions=[Condition(**c) for c in json.loads(r["conditions"] or "[]")],
        allergies=json.loads(r["allergies"] or "[]"),
        medicines=json.loads(r["medicines"] or "[]"),
        mobility=r["mobility"],
        diet=r["diet"],
        last_review=_dt(r["last_review"]),
        reviewed_by=r["reviewed_by"],
    )


class _Wrapped:
    """Delegates to a repository; `method` also writes through to the server."""

    def __init__(self, inner: Any, method: str, write: Callable[[Any], None]) -> None:
        self._inner = inner
        self._method = method
        self._write = write

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._inner, name)
        if name != self._method:
            return target

        def through(item: Any) -> Any:
            result = target(item)
            self._write(item)
            return result

        return through


class PersistentCareStore(InMemoryCareStore):
    def __init__(self, link: Link) -> None:
        super().__init__()
        self._link = link
        self._raw = {
            "entries": self.entries,
            "flags": self.flags,
            "preferences": self.preferences,
            "messages": self.messages,
            "medical": self.medical,
            "deliveries": self.deliveries,
        }

        def to(reducer: str, args: Callable[[Any], list[Any]]) -> Callable[[Any], None]:
            return lambda item: link.write(reducer, args(item))

        self.entries = _Wrapped(self.entries, "add", to("save_care_entry", _entry_args))
        self.flags = _Wrapped(self.flags, "save", to("save_flag", _flag_args))
        self.preferences = _Wrapped(self.preferences, "save", to("save_preferences", _prefs_args))
        self.messages = _Wrapped(self.messages, "add", to("save_family_message", _message_args))
        self.medical = _Wrapped(self.medical, "save", to("save_medical_record", _medical_args))
        self.deliveries = _DeliveryThrough(self._raw["deliveries"], link)

    def load(self, link: Link) -> int:
        """Fill the in-memory repositories from the server (no write back)."""
        raw = self._raw
        n = 0
        for row in link.select_all("care_entry"):
            raw["entries"].add(_entry_from(row))
            n += 1
        for row in link.select_all("flag"):
            raw["flags"].save(_flag_from(row))
            n += 1
        for row in link.select_all("preferences"):
            raw["preferences"].save(_prefs_from(row))
            n += 1
        for row in link.select_all("family_message"):
            raw["messages"].add(_message_from(row))
            n += 1
        for row in link.select_all("medical_record"):
            raw["medical"].save(_medical_from(row))
            n += 1
        for row in link.select_all("family_delivery"):
            raw["deliveries"].set(row["resident_id"], _dt(row["at"]))
            n += 1
        return n


class _DeliveryThrough:
    def __init__(self, inner: Any, link: Link) -> None:
        self._inner = inner
        self._link = link

    def get(self, resident_id: str) -> datetime | None:
        return self._inner.get(resident_id)

    def set(self, resident_id: str, at: datetime) -> None:
        self._inner.set(resident_id, at)
        self._link.write("save_family_delivery", [resident_id, _iso(at)])


class PersistentData:
    """The memory index, review queue and care store, all writing through one link."""

    def __init__(self, link: Link) -> None:
        self.link = link
        self.index = PersistentMemoryIndex(link)
        self.pending = PersistentPending(link)
        self.care = PersistentCareStore(link)

    def hydrate(self) -> int:
        """Load everything from the server. Raises httpx.HTTPError if a table is unavailable."""
        facts = self.link.select_all("memory_fact")
        pending = self.link.select_all("pending_fact")
        # Read every table before filling anything, so a half-loaded state is never used.
        count = len(facts) + len(pending)
        count += self.care.load(self.link)
        self.index.load(facts)
        self.pending.load(pending)
        return count
