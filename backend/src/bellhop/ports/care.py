"""Ports for care data. Separate from `ports/__init__.py` to keep the core contract small."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from bellhop.domain.care import (
    CareEntry,
    EntryKind,
    FamilyMessage,
    Flag,
    MedicalRecord,
    NoteCategory,
    Preferences,
    RefinedNote,
)


class CareRepository(Protocol):
    def add(self, entry: CareEntry) -> None: ...
    def entries(
        self,
        resident_id: str,
        kind: EntryKind | None = None,
        since: datetime | None = None,
    ) -> list[CareEntry]:
        """Oldest first."""
        ...


class FlagRepository(Protocol):
    def save(self, flag: Flag) -> None: ...
    def get(self, flag_id: str) -> Flag | None: ...
    def list(self, resident_id: str | None = None, open_only: bool = True) -> list[Flag]: ...


class PreferencesRepository(Protocol):
    def get(self, resident_id: str) -> Preferences:
        """Defaults when nothing is stored."""
        ...

    def save(self, prefs: Preferences) -> None: ...


class FamilyMessageRepository(Protocol):
    def add(self, message: FamilyMessage) -> None: ...
    def list(self, resident_id: str) -> list[FamilyMessage]:
        """Oldest first."""
        ...


class MedicalRepository(Protocol):
    def get(self, resident_id: str) -> MedicalRecord:
        """An empty record when nothing is stored."""
        ...

    def save(self, record: MedicalRecord) -> None: ...


class NoteRefiner(Protocol):
    """Tidies a note staff wrote in their own words. Raises ValueError for an empty note."""

    def refine(self, category: NoteCategory, text: str) -> RefinedNote: ...
