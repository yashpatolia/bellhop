"""One-line auto visit notes. Observations only: records what was captured, never diagnoses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bellhop.domain import Call
from bellhop.domain.care import CareEntry, EntryKind
from bellhop.ports import CallRepository, Clock
from bellhop.ports.care import CareRepository

_NURSE_ALERT_URGENCY = 3


@dataclass(frozen=True)
class VisitNote:
    text: str
    resident_id: str | None
    room: str
    at: datetime


def mood_word(value: float) -> str:
    if value >= 4:
        return "good"
    if value >= 3:
        return "okay"
    return "low"


class VisitNotes:
    def __init__(self, calls: CallRepository, care: CareRepository, clock: Clock) -> None:
        self._calls = calls
        self._care = care
        self._clock = clock

    def build(self, call_id: str) -> VisitNote:
        call = self._calls.get(call_id)
        if call is None:
            raise LookupError(f"unknown call {call_id}")
        entries = self._entries_for(call)
        parts = self._parts(entries)
        if not parts:
            parts = ["visited, no concerns noted"]
        if call.urgency is not None and int(call.urgency) >= _NURSE_ALERT_URGENCY:
            parts.append(f"nurse alerted (urgency {int(call.urgency)})")
        text = f"Room {call.room}, {call.created_at:%H:%M}: " + ", ".join(parts)
        return VisitNote(
            text=text, resident_id=call.resident_id, room=call.room, at=call.created_at
        )

    def _entries_for(self, call: Call) -> list[CareEntry]:
        if call.resident_id is None:
            return []
        return [e for e in self._care.entries(call.resident_id) if e.call_id == call.id]

    @staticmethod
    def _parts(entries: list[CareEntry]) -> list[str]:
        parts: list[str] = []
        for kind in (EntryKind.MOOD, EntryKind.PAIN, EntryKind.DRINK, EntryKind.REPEAT_QUESTION):
            for e in (x for x in entries if x.kind == kind):
                if kind == EntryKind.MOOD and e.value is not None:
                    parts.append(f"mood {mood_word(e.value)}")
                elif kind == EntryKind.PAIN and e.value is not None:
                    parts.append(f"pain {e.value:g}/5")
                elif kind == EntryKind.DRINK:
                    parts.append(f"drank {e.note}" if e.note else "had a drink")
                elif kind == EntryKind.REPEAT_QUESTION and e.note:
                    parts.append(e.note)
        return parts
