"""Family voice notes, resident replies and the daily postcard.

Postcards are built only from structured care entries (mood bucket, drink taken with an
allowlisted drink name). Free-text notes are never echoed, so pain, urgency, medication and
nurse wording cannot appear.
"""

from __future__ import annotations

import re
from datetime import datetime, time
from typing import Any

from bellhop.domain.care import CareEntry, EntryKind, FamilyMessage, MessageDirection
from bellhop.ports import CallRepository, Clock, IdGenerator, ResidentRepository
from bellhop.ports.care import CareRepository, FamilyMessageRepository

_QUIET_LINE = "Had a quiet day and enjoyed a visit from the robot"
_MAX_LINES = 3
# Privacy by construction: postcard text is never copied from free-text notes. Lines come from
# fixed templates, and the only note-derived content is a drink name found in this allowlist.
_DRINKS = frozenset(
    "tea coffee juice water milk cocoa chocolate lemonade squash cordial smoothie".split()
)
_WORD = re.compile(r"\w+")


def _drink_name(note: str) -> str | None:
    for word in _WORD.findall(note.lower()):
        if word in _DRINKS:
            return word
    return None


class _Deliveries:
    def __init__(self) -> None:
        self._items: dict[str, datetime] = {}

    def get(self, resident_id: str) -> datetime | None:
        return self._items.get(resident_id)

    def set(self, resident_id: str, at: datetime) -> None:
        self._items[resident_id] = at


class FamilyService:
    def __init__(
        self,
        messages: FamilyMessageRepository,
        residents: ResidentRepository,
        calls: CallRepository,
        care: CareRepository,
        clock: Clock,
        ids: IdGenerator,
        deliveries: Any = None,
    ) -> None:
        self._messages = messages
        self._residents = residents
        self._calls = calls
        self._care = care
        self._clock = clock
        self._ids = ids
        # Delivery times live in a repository with get(resident_id) and set(resident_id, at).
        self._deliveries = deliveries if deliveries is not None else _Deliveries()

    def _add(self, resident_id: str, text: str, direction: MessageDirection) -> FamilyMessage:
        msg = FamilyMessage(
            id=self._ids.new_id("fmsg"),
            resident_id=resident_id,
            direction=direction,
            text=text,
            created_at=self._clock.now(),
        )
        self._messages.add(msg)
        return msg

    def leave_voice_note(self, resident_id: str, text: str) -> FamilyMessage:
        return self._add(resident_id, text, MessageDirection.TO_RESIDENT)

    def record_reply(self, resident_id: str, text: str) -> FamilyMessage:
        return self._add(resident_id, text, MessageDirection.FROM_RESIDENT)

    def pending_for_resident(self, resident_id: str) -> list[FamilyMessage]:
        last = self._deliveries.get(resident_id)
        return [
            m
            for m in self._messages.list(resident_id)
            if m.direction == MessageDirection.TO_RESIDENT and (last is None or m.created_at > last)
        ]

    def mark_delivered(self, resident_id: str) -> None:
        self._deliveries.set(resident_id, self._clock.now())

    def daily_postcard(self, resident_id: str, now: datetime) -> list[str]:
        start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
        entries = [
            e for e in self._care.entries(resident_id, since=start) if e.at.date() == now.date()
        ]
        lines: list[str] = []
        for e in entries:
            line = self._line(e)
            if line and line not in lines:
                lines.append(line)
        lines.sort(key=lambda s: s == "Was in good spirits")  # specifics first
        return lines[:_MAX_LINES] or [_QUIET_LINE]

    @staticmethod
    def _line(e: CareEntry) -> str | None:
        if e.kind == EntryKind.MOOD and e.value is not None and e.value >= 4:
            return "Was in good spirits"
        if e.kind == EntryKind.DRINK:
            drink = _drink_name(e.note) if e.note else None
            return f"Enjoyed some {drink}" if drink else "Enjoyed a drink"
        return None
