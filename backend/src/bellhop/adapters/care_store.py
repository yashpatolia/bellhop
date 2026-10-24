"""In-memory care repositories (copy-safe), exposed through one facade like `InMemoryStore`."""

from __future__ import annotations

from datetime import datetime

from bellhop.domain.care import (
    CareEntry,
    EntryKind,
    FamilyMessage,
    Flag,
    MedicalRecord,
    Preferences,
)


class _Entries:
    def __init__(self) -> None:
        self._items: list[CareEntry] = []

    def add(self, entry: CareEntry) -> None:
        self._items.append(entry.model_copy(deep=True))

    def entries(
        self,
        resident_id: str,
        kind: EntryKind | None = None,
        since: datetime | None = None,
    ) -> list[CareEntry]:
        hits = [
            e
            for e in self._items
            if e.resident_id == resident_id
            and (kind is None or e.kind == kind)
            and (since is None or e.at >= since)
        ]
        return [e.model_copy(deep=True) for e in sorted(hits, key=lambda e: e.at)]


class _Flags:
    def __init__(self) -> None:
        self._items: dict[str, Flag] = {}

    def save(self, flag: Flag) -> None:
        self._items[flag.id] = flag.model_copy(deep=True)

    def get(self, flag_id: str) -> Flag | None:
        f = self._items.get(flag_id)
        return f.model_copy(deep=True) if f else None

    def list(self, resident_id: str | None = None, open_only: bool = True) -> list[Flag]:
        return [
            f.model_copy(deep=True)
            for f in list(self._items.values())
            if (resident_id is None or f.resident_id == resident_id)
            and (not open_only or f.resolved_at is None)
        ]


class _Preferences:
    def __init__(self) -> None:
        self._items: dict[str, Preferences] = {}

    def get(self, resident_id: str) -> Preferences:
        p = self._items.get(resident_id)
        return p.model_copy(deep=True) if p else Preferences(resident_id=resident_id)

    def save(self, prefs: Preferences) -> None:
        self._items[prefs.resident_id] = prefs.model_copy(deep=True)


class _Messages:
    def __init__(self) -> None:
        self._items: list[FamilyMessage] = []

    def add(self, message: FamilyMessage) -> None:
        self._items.append(message.model_copy(deep=True))

    def list(self, resident_id: str) -> list[FamilyMessage]:
        hits = [m for m in self._items if m.resident_id == resident_id]
        return [m.model_copy(deep=True) for m in sorted(hits, key=lambda m: m.created_at)]


class _Medical:
    def __init__(self) -> None:
        self._items: dict[str, MedicalRecord] = {}

    def get(self, resident_id: str) -> MedicalRecord:
        m = self._items.get(resident_id)
        return m.model_copy(deep=True) if m else MedicalRecord(resident_id=resident_id)

    def save(self, record: MedicalRecord) -> None:
        self._items[record.resident_id] = record.model_copy(deep=True)


class _Deliveries:
    """When each resident last had their family voice notes read out."""

    def __init__(self) -> None:
        self._items: dict[str, datetime] = {}

    def get(self, resident_id: str) -> datetime | None:
        return self._items.get(resident_id)

    def set(self, resident_id: str, at: datetime) -> None:
        self._items[resident_id] = at


class InMemoryCareStore:
    def __init__(self) -> None:
        self.entries = _Entries()
        self.flags = _Flags()
        self.preferences = _Preferences()
        self.messages = _Messages()
        self.medical = _Medical()
        self.deliveries = _Deliveries()
