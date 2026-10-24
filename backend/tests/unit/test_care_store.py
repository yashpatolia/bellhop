from datetime import UTC, datetime, timedelta

from bellhop.adapters.care_store import InMemoryCareStore
from bellhop.domain.care import (
    CareEntry,
    EntryKind,
    FamilyMessage,
    Flag,
    FlagType,
    MessageDirection,
    Preferences,
)

T0 = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)


def _entry(i: str, rid: str = "r1", kind: EntryKind = EntryKind.MOOD, at: datetime = T0):
    return CareEntry(id=i, resident_id=rid, kind=kind, value=3, at=at)


def test_entries_empty_for_unknown_resident():
    assert InMemoryCareStore().entries.entries("nobody") == []


def test_entries_filter_by_resident_kind_since_oldest_first():
    s = InMemoryCareStore()
    s.entries.add(_entry("e2", at=T0 + timedelta(hours=1)))
    s.entries.add(_entry("e1", at=T0))
    s.entries.add(_entry("e3", kind=EntryKind.PAIN, at=T0 + timedelta(hours=2)))
    s.entries.add(_entry("e4", rid="r2"))
    assert [e.id for e in s.entries.entries("r1")] == ["e1", "e2", "e3"]
    assert [e.id for e in s.entries.entries("r1", kind=EntryKind.MOOD)] == ["e1", "e2"]
    since = s.entries.entries("r1", since=T0 + timedelta(hours=1))
    assert [e.id for e in since] == ["e2", "e3"]  # since is inclusive


def test_entries_copy_safe():
    s = InMemoryCareStore()
    e = _entry("e1")
    s.entries.add(e)
    e.note = "mutated"
    got = s.entries.entries("r1")[0]
    got.note = "also"
    assert s.entries.entries("r1")[0].note == ""


def _flag(i: str, rid: str = "r1", resolved: bool = False) -> Flag:
    return Flag(
        id=i,
        resident_id=rid,
        type=FlagType.PAIN,
        reason="why",
        created_at=T0,
        resolved_at=T0 if resolved else None,
    )


def test_flags_save_get_list_open_only_and_copy_safe():
    s = InMemoryCareStore()
    assert s.flags.get("nope") is None
    s.flags.save(_flag("f1"))
    s.flags.save(_flag("f2", resolved=True))
    s.flags.save(_flag("f3", rid="r2"))
    assert {f.id for f in s.flags.list()} == {"f1", "f3"}
    assert {f.id for f in s.flags.list("r1", open_only=False)} == {"f1", "f2"}
    got = s.flags.get("f1")
    assert got is not None
    got.reason = "x"
    assert s.flags.get("f1").reason == "why"  # type: ignore[union-attr]
    got.resolved_at = T0
    s.flags.save(got)
    assert {f.id for f in s.flags.list("r1")} == set()


def test_preferences_default_and_roundtrip():
    s = InMemoryCareStore()
    assert s.preferences.get("r1") == Preferences(resident_id="r1")
    s.preferences.save(Preferences(resident_id="r1", quiet_mode=True))
    assert s.preferences.get("r1").quiet_mode is True
    assert s.preferences.get("r2").quiet_mode is False


def test_messages_oldest_first_per_resident():
    s = InMemoryCareStore()

    def m(i: str, rid: str, at: datetime) -> FamilyMessage:
        return FamilyMessage(
            id=i, resident_id=rid, direction=MessageDirection.TO_RESIDENT, text="hi", created_at=at
        )

    s.messages.add(m("m2", "r1", T0 + timedelta(minutes=1)))
    s.messages.add(m("m1", "r1", T0))
    s.messages.add(m("m3", "r2", T0))
    assert [x.id for x in s.messages.list("r1")] == ["m1", "m2"]
    assert s.messages.list("none") == []
