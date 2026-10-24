"""Care signals: record mood/pain/drink/repeat entries and surface trends.

Observations only, never diagnoses. Wording says "mentioned" and "lower than usual".
Days are UTC calendar days. Repeat questions are information for the nurse, never flagged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from bellhop.domain.care import CareEntry, EntryKind, Flag, FlagType
from bellhop.ports import Clock, EventBus, IdGenerator
from bellhop.ports.care import CareRepository, FlagRepository

PAIN_MIN_SCORE = 2
PAIN_FLAG_DAYS = 3
MIN_BASELINE_ENTRIES = 3


@dataclass(frozen=True)
class PainStreak:
    days: int


@dataclass(frozen=True)
class MoodTrend:
    changed: bool
    recent_mean: float | None
    baseline_mean: float | None


@dataclass(frozen=True)
class Hydration:
    drinks: int


@dataclass(frozen=True)
class RepeatQuestions:
    count: int


def _mean(entries: list[CareEntry]) -> float | None:
    vals = [e.value for e in entries if e.value is not None]
    return sum(vals) / len(vals) if vals else None


def _day_start(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


class CareSignals:
    def __init__(
        self,
        care: CareRepository,
        flags: FlagRepository,
        clock: Clock,
        ids: IdGenerator,
        bus: EventBus | None = None,
    ) -> None:
        self._care = care
        self._flags = flags
        self._clock = clock
        self._ids = ids
        self._bus = bus

    # recording

    def _record(
        self,
        resident_id: str,
        kind: EntryKind,
        value: float | None,
        call_id: str | None,
        note: str,
        at: datetime | None = None,
    ) -> CareEntry:
        entry = CareEntry(
            id=self._ids.new_id("ce"),
            resident_id=resident_id,
            call_id=call_id,
            kind=kind,
            value=value,
            note=note,
            at=at or self._clock.now(),
        )
        self._care.add(entry)
        return entry

    def record_mood(
        self,
        resident_id: str,
        score: float,
        call_id: str | None = None,
        note: str = "",
        at: datetime | None = None,
    ) -> CareEntry:
        entry = self._record(resident_id, EntryKind.MOOD, score, call_id, note, at)
        if self.mood_changed_from_usual(resident_id, entry.at).changed:
            self.raise_flag(resident_id, FlagType.DISTRESS, "mood lower than usual", call_id)
        return entry

    def record_pain(
        self,
        resident_id: str,
        score: float,
        call_id: str | None = None,
        note: str = "",
        at: datetime | None = None,
    ) -> CareEntry:
        entry = self._record(resident_id, EntryKind.PAIN, score, call_id, note, at)
        days = self.pain_streak(resident_id, entry.at).days
        if days >= PAIN_FLAG_DAYS:
            self.raise_flag(
                resident_id, FlagType.PAIN, f"pain mentioned {days} days in a row", call_id
            )
        return entry

    def record_drink(
        self, resident_id: str, call_id: str | None = None, note: str = ""
    ) -> CareEntry:
        return self._record(resident_id, EntryKind.DRINK, None, call_id, note)

    def record_repeat_question(self, resident_id: str, call_id: str | None = None) -> CareEntry:
        return self._record(resident_id, EntryKind.REPEAT_QUESTION, None, call_id, "")

    # trends

    def pain_streak(self, resident_id: str, now: datetime) -> PainStreak:
        entries = self._care.entries(resident_id, kind=EntryKind.PAIN)
        pain_days: set[date] = {
            e.at.date() for e in entries if e.value is not None and e.value >= PAIN_MIN_SCORE
        }
        day = now.date()
        days = 0
        while day in pain_days:
            days += 1
            day -= timedelta(days=1)
        return PainStreak(days)

    def mood_changed_from_usual(
        self,
        resident_id: str,
        now: datetime,
        window_days: int = 3,
        baseline_days: int = 14,
        drop: float = 1.0,
    ) -> MoodTrend:
        window_start = now - timedelta(days=window_days)
        baseline_start = window_start - timedelta(days=baseline_days)
        entries = self._care.entries(resident_id, kind=EntryKind.MOOD, since=baseline_start)
        recent = [e for e in entries if window_start < e.at <= now]
        baseline = [e for e in entries if baseline_start <= e.at <= window_start]
        r_mean, b_mean = _mean(recent), _mean(baseline)
        changed = (
            r_mean is not None
            and b_mean is not None
            and len(baseline) >= MIN_BASELINE_ENTRIES
            and b_mean - r_mean >= drop
        )
        return MoodTrend(changed, r_mean, b_mean)

    def _today(self, resident_id: str, kind: EntryKind, now: datetime) -> int:
        start = _day_start(now)
        return sum(
            1
            for e in self._care.entries(resident_id, kind=kind, since=start)
            if e.at < start + timedelta(days=1)
        )

    def hydration_today(self, resident_id: str, now: datetime) -> Hydration:
        return Hydration(self._today(resident_id, EntryKind.DRINK, now))

    def repeat_question_count(self, resident_id: str, now: datetime) -> RepeatQuestions:
        return RepeatQuestions(self._today(resident_id, EntryKind.REPEAT_QUESTION, now))

    # flags

    def raise_flag(
        self, resident_id: str, type: FlagType, reason: str, call_id: str | None = None
    ) -> Flag:
        if not reason or not reason.strip():
            raise ValueError("a flag needs a reason")
        for f in self._flags.list(resident_id):
            if f.type == type:
                return f
        flag = Flag(
            id=self._ids.new_id("fl"),
            resident_id=resident_id,
            call_id=call_id,
            type=type,
            reason=reason.strip(),
            created_at=self._clock.now(),
        )
        self._flags.save(flag)
        return flag

    def resolve_flag(self, flag_id: str) -> Flag:
        flag = self._flags.get(flag_id)
        if flag is None:
            raise KeyError(flag_id)
        if flag.resolved_at is None:
            flag.resolved_at = self._clock.now()
            self._flags.save(flag)
        return flag
