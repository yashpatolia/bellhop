from datetime import UTC, datetime

from bellhop.domain import Call, Resident, Urgency
from bellhop.domain.care import CareEntry, EntryKind, MessageDirection
from bellhop.services.family import FamilyService

NOW = datetime(2026, 10, 24, 18, 0, tzinfo=UTC)


class FakeMessages:
    def __init__(self) -> None:
        self.items = []

    def add(self, message) -> None:
        self.items.append(message)

    def list(self, resident_id):
        return [m for m in self.items if m.resident_id == resident_id]


class FakeCare:
    def __init__(self, *entries: CareEntry) -> None:
        self.items = list(entries)

    def entries(self, resident_id, kind=None, since=None):
        return [
            e
            for e in self.items
            if e.resident_id == resident_id
            and (kind is None or e.kind == kind)
            and (since is None or e.at >= since)
        ]


class FakeResidents:
    def get(self, resident_id):
        return Resident(id=resident_id, name="Rose", room="204")


class FakeCalls:
    def __init__(self, *calls: Call) -> None:
        self._d = {c.id: c for c in calls}

    def get(self, call_id):
        return self._d.get(call_id)


def _e(kind, value=None, note="", n=1, day=24):
    return CareEntry(
        id=f"e{n}",
        resident_id="r1",
        call_id="c1",
        kind=kind,
        value=value,
        note=note,
        at=datetime(2026, 10, day, 11, n, tzinfo=UTC),
    )


def _svc(clock, ids, *entries, calls=None):
    msgs = FakeMessages()
    svc = FamilyService(msgs, FakeResidents(), calls or FakeCalls(), FakeCare(*entries), clock, ids)
    return svc, msgs


def test_leave_and_reply(clock, ids):
    svc, msgs = _svc(clock, ids)
    a = svc.leave_voice_note("r1", "Love you")
    b = svc.record_reply("r1", "Love you too")
    assert a.direction == MessageDirection.TO_RESIDENT
    assert b.direction == MessageDirection.FROM_RESIDENT
    assert a.created_at == clock.now()
    assert len(msgs.items) == 2


def test_pending_and_mark_delivered(clock, ids):
    svc, _ = _svc(clock, ids)
    svc.leave_voice_note("r1", "one")
    svc.record_reply("r1", "reply")
    assert [m.text for m in svc.pending_for_resident("r1")] == ["one"]
    clock.advance(minutes=1)
    svc.mark_delivered("r1")
    assert svc.pending_for_resident("r1") == []
    clock.advance(minutes=1)
    svc.leave_voice_note("r1", "two")
    assert [m.text for m in svc.pending_for_resident("r1")] == ["two"]
    assert svc.pending_for_resident("r2") == []


def test_postcard_cheerful_and_capped(clock, ids):
    entries = [
        _e(EntryKind.MOOD, 5, "talked about her roses", 1),
        _e(EntryKind.DRINK, note="juice", n=2),
        _e(EntryKind.MOOD, 4, "won checkers twice", 3),
        _e(EntryKind.MOOD, 4, "sang a song", 4),
    ]
    svc, _ = _svc(clock, ids, *entries)
    lines = svc.daily_postcard("r1", NOW)
    assert 1 <= len(lines) <= 3
    assert "Enjoyed some juice" in lines
    assert "Was in good spirits" in lines
    assert not any("roses" in line or "checkers" in line for line in lines)  # notes not echoed


def test_postcard_good_mood_only(clock, ids):
    svc, _ = _svc(clock, ids, _e(EntryKind.MOOD, 5))
    assert svc.daily_postcard("r1", NOW) == ["Was in good spirits"]


def test_postcard_quiet_day(clock, ids):
    svc, _ = _svc(clock, ids)
    assert svc.daily_postcard("r1", NOW) == ["Had a quiet day and enjoyed a visit from the robot"]


def test_postcard_ignores_yesterday(clock, ids):
    svc, _ = _svc(clock, ids, _e(EntryKind.MOOD, 5, "sang", 1, day=23))
    assert svc.daily_postcard("r1", NOW)[0].startswith("Had a quiet day")


def test_postcard_skips_negative_and_medical(clock, ids):
    entries = [
        _e(EntryKind.MOOD, 1, "felt sad", 1),
        _e(EntryKind.MOOD, 4, "complained of dizzy spell", 2),
        _e(EntryKind.REPEAT_QUESTION, note="asked about daughter", n=3),
    ]
    svc, _ = _svc(clock, ids, *entries)
    assert svc.daily_postcard("r1", NOW) == ["Was in good spirits"]


def test_postcard_never_leaks_pain_or_urgency(clock, ids):
    entries = [
        _e(EntryKind.PAIN, 5, "sharp pain in hip", 1),
        _e(EntryKind.MOOD, 4, "chatted about pain pills", 2),
        _e(EntryKind.DRINK, note="water", n=3),
    ]
    call = Call(
        id="c1",
        room="204",
        resident_id="r1",
        urgency=Urgency(4),
        created_at=datetime(2026, 10, 24, 11, 0, tzinfo=UTC),
    )
    svc, _ = _svc(clock, ids, *entries, calls=FakeCalls(call))
    text = " ".join(svc.daily_postcard("r1", NOW)).lower()
    for banned in ("pain", "urgency", "hip", "nurse", "alert", "/5", "4"):
        assert banned not in text
