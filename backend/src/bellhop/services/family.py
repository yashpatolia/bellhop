"""Family voice notes, resident replies and the daily postcard.

Postcards are built only from recorded, positive, non-medical entries. Pain and urgency
never appear in them.
"""

from __future__ import annotations

from datetime import datetime, time

from bellhop.domain.care import CareEntry, EntryKind, FamilyMessage, MessageDirection
from bellhop.ports import CallRepository, Clock, IdGenerator, ResidentRepository
from bellhop.ports.care import CareRepository, FamilyMessageRepository

_QUIET_LINE = "Had a quiet day and enjoyed a visit from the robot"
_MAX_LINES = 3
_BLOCKED = (
    "pain", "hurt", "ache", "sore", "nurse", "urgent", "alert", "dizzy", "fall", "fell",
    "medic", "pill", "doctor", "sick", "bleed", "sad", "cry", "upset", "angry", "confus",
    "scared", "worr", "complain", "lonely", "bad", "afraid", "distress",
)  # fmt: skip


def _safe(text: str) -> bool:
    low = text.lower()
    return bool(text.strip()) and not any(b in low for b in _BLOCKED)


class FamilyService:
    def __init__(
        self,
        messages: FamilyMessageRepository,
        residents: ResidentRepository,
        calls: CallRepository,
        care: CareRepository,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._messages = messages
        self._residents = residents
        self._calls = calls
        self._care = care
        self._clock = clock
        self._ids = ids
        self._delivered: dict[str, datetime] = {}

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
        last = self._delivered.get(resident_id)
        return [
            m
            for m in self._messages.list(resident_id)
            if m.direction == MessageDirection.TO_RESIDENT and (last is None or m.created_at > last)
        ]

    def mark_delivered(self, resident_id: str) -> None:
        self._delivered[resident_id] = self._clock.now()

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
        if e.kind == EntryKind.MOOD and e.value is not None and e.value >= 3:
            if e.note and _safe(e.note):
                return e.note[0].upper() + e.note[1:]
            return "Was in good spirits" if e.value >= 4 else None
        if e.kind == EntryKind.DRINK:
            if e.note and _safe(e.note):
                return f"Enjoyed some {e.note}"
            return "Enjoyed a drink"
        return None
