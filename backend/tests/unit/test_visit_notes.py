from datetime import UTC, datetime

import pytest

from bellhop.domain import Call, Urgency
from bellhop.domain.care import CareEntry, EntryKind
from bellhop.services.visit_notes import VisitNotes


class FakeCalls:
    def __init__(self, *calls: Call) -> None:
        self._d = {c.id: c for c in calls}

    def get(self, call_id: str) -> Call | None:
        return self._d.get(call_id)


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


def _call(urgency: Urgency | None = None) -> Call:
    return Call(
        id="c1",
        room="204",
        resident_id="r1",
        urgency=urgency,
        created_at=datetime(2026, 10, 24, 10, 32, tzinfo=UTC),
    )


def _e(kind, value=None, note="", call_id="c1", n=1):
    return CareEntry(
        id=f"e{n}",
        resident_id="r1",
        call_id=call_id,
        kind=kind,
        value=value,
        note=note,
        at=datetime(2026, 10, 24, 10, 33, tzinfo=UTC),
    )


def test_full_note(clock):
    care = FakeCare(
        _e(EntryKind.MOOD, 4, n=1),
        _e(EntryKind.PAIN, 2, n=2),
        _e(EntryKind.DRINK, note="juice", n=3),
        _e(EntryKind.REPEAT_QUESTION, note="asked about daughter", n=4),
    )
    note = VisitNotes(FakeCalls(_call()), care, clock).build("c1")
    assert note.text == "Room 204, 10:32: mood good, pain 2/5, drank juice, asked about daughter"
    assert note.resident_id == "r1"
    assert note.room == "204"


@pytest.mark.parametrize(
    ("value", "word"), [(5, "good"), (4, "good"), (3, "okay"), (2, "low"), (1, "low")]
)
def test_mood_words(clock, value, word):
    care = FakeCare(_e(EntryKind.MOOD, value))
    text = VisitNotes(FakeCalls(_call()), care, clock).build("c1").text
    assert text == f"Room 204, 10:32: mood {word}"


def test_no_entries(clock):
    text = VisitNotes(FakeCalls(_call()), FakeCare(), clock).build("c1").text
    assert text == "Room 204, 10:32: visited, no concerns noted"


def test_ignores_other_calls_entries(clock):
    care = FakeCare(_e(EntryKind.MOOD, 5, call_id="other"))
    text = VisitNotes(FakeCalls(_call()), care, clock).build("c1").text
    assert "mood" not in text


def test_only_what_was_recorded(clock):
    care = FakeCare(_e(EntryKind.DRINK))
    text = VisitNotes(FakeCalls(_call()), care, clock).build("c1").text
    assert text == "Room 204, 10:32: had a drink"


def test_urgency_appends_nurse_alerted(clock):
    care = FakeCare(_e(EntryKind.PAIN, 4))
    text = VisitNotes(FakeCalls(_call(Urgency(3))), care, clock).build("c1").text
    assert text.endswith("nurse alerted (urgency 3)")
    assert "pain 4/5" in text


def test_low_urgency_no_alert_text(clock):
    text = VisitNotes(FakeCalls(_call(Urgency(2))), FakeCare(), clock).build("c1").text
    assert "alerted" not in text


def test_unknown_call(clock):
    with pytest.raises(LookupError):
        VisitNotes(FakeCalls(), FakeCare(), clock).build("nope")
