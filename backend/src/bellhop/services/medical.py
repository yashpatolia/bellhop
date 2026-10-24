"""Medical history entered by staff. Facts about habits live in memory, not here."""

from __future__ import annotations

import re

from bellhop.domain.care import Condition, MedicalRecord, NoteCategory, RefinedNote
from bellhop.ports import Clock
from bellhop.ports.care import MedicalRepository

_EMPTY = re.compile(r"^none (?:known|recorded)$", re.IGNORECASE)


def _same(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


class MedicalService:
    def __init__(self, repo: MedicalRepository, clock: Clock) -> None:
        self._repo = repo
        self._clock = clock

    def get(self, resident_id: str) -> MedicalRecord:
        return self._repo.get(resident_id)

    def replace(self, record: MedicalRecord) -> MedicalRecord:
        self._repo.save(record)
        return record

    def add_entry(
        self, resident_id: str, note: RefinedNote, reviewer: str = "Staff"
    ) -> MedicalRecord:
        """Add one reviewed note. Duplicates are ignored; mobility and diet are replaced."""
        if note.category.is_fact:
            raise ValueError(f"{note.category.value} is a memory fact, not medical history")
        record = self._repo.get(resident_id)
        text = note.text.strip()
        match note.category:
            case NoteCategory.CONDITION:
                record.conditions.append(Condition(name=text, since=note.since or "recently"))
            case NoteCategory.ALLERGY:
                kept = [a for a in record.allergies if not _EMPTY.match(a.strip())]
                record.allergies = kept if any(_same(a, text) for a in kept) else [*kept, text]
            case NoteCategory.MEDICINE:
                if not any(_same(m, text) for m in record.medicines):
                    record.medicines.append(text)
            case NoteCategory.MOBILITY:
                record.mobility = text
            case NoteCategory.DIET:
                record.diet = text
        record.last_review = self._clock.now()
        record.reviewed_by = reviewer
        self._repo.save(record)
        return record
