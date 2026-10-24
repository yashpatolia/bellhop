from datetime import UTC, datetime, timedelta

import pytest

from bellhop.adapters.care_store import InMemoryCareStore
from bellhop.domain.care import CareEntry, EntryKind, FlagType
from bellhop.services.care_signals import CareSignals


@pytest.fixture
def store() -> InMemoryCareStore:
    return InMemoryCareStore()


@pytest.fixture
def sig(store, clock, ids) -> CareSignals:
    return CareSignals(store.entries, store.flags, clock, ids)


def _seed(store, kind, days_ago, value, clock, hour=9, n=1):
    base = clock.now().replace(hour=hour, minute=0) - timedelta(days=days_ago)
    for i in range(n):
        store.entries.add(
            CareEntry(
                id=f"s{kind}{days_ago}{i}{value}",
                resident_id="r1",
                kind=kind,
                value=value,
                at=base + timedelta(minutes=i),
            )
        )


def test_no_data_everything_empty(sig, clock):
    now = clock.now()
    assert sig.pain_streak("r1", now).days == 0
    assert sig.mood_changed_from_usual("r1", now).changed is False
    assert sig.hydration_today("r1", now).drinks == 0
    assert sig.repeat_question_count("r1", now).count == 0


def test_record_functions_store_entries(sig, store):
    sig.record_mood("r1", 4, call_id="c1", note="chatty")
    sig.record_pain("r1", 2)
    sig.record_drink("r1")
    sig.record_repeat_question("r1")
    kinds = [e.kind for e in store.entries.entries("r1")]
    assert kinds == [EntryKind.MOOD, EntryKind.PAIN, EntryKind.DRINK, EntryKind.REPEAT_QUESTION]
    assert store.entries.entries("r1", kind=EntryKind.MOOD)[0].call_id == "c1"


def test_pain_streak_counts_consecutive_days(sig, store, clock):
    for d in (0, 1):
        _seed(store, EntryKind.PAIN, d, 3, clock)
    s = sig.pain_streak("r1", clock.now())
    assert s.days == 2


def test_pain_streak_ignores_low_scores_and_gaps(sig, store, clock):
    _seed(store, EntryKind.PAIN, 0, 3, clock)
    _seed(store, EntryKind.PAIN, 1, 1, clock)  # no pain
    _seed(store, EntryKind.PAIN, 2, 4, clock)
    assert sig.pain_streak("r1", clock.now()).days == 1


def test_pain_streak_needs_entry_today(sig, store, clock):
    _seed(store, EntryKind.PAIN, 1, 4, clock)
    _seed(store, EntryKind.PAIN, 2, 4, clock)
    assert sig.pain_streak("r1", clock.now()).days == 0


def test_pain_threshold_exactly_two_counts(sig, store, clock):
    _seed(store, EntryKind.PAIN, 0, 2, clock)
    assert sig.pain_streak("r1", clock.now()).days == 1


def test_pain_streak_utc_day_boundary(sig, store, clock):
    # 23:59 yesterday and 00:01 today are different calendar days.
    clock._now = datetime(2026, 10, 24, 0, 1, tzinfo=UTC)
    _seed(store, EntryKind.PAIN, 1, 3, clock, hour=23)
    sig.record_pain("r1", 3)
    assert sig.pain_streak("r1", clock.now()).days == 2


def test_pain_streak_three_days_raises_pain_flag(sig, store, clock):
    _seed(store, EntryKind.PAIN, 2, 3, clock)
    sig.record_pain("r1", 3)  # today only: streak 1
    assert store.flags.list() == []
    _seed(store, EntryKind.PAIN, 1, 3, clock)
    sig.record_pain("r1", 3)
    flags = store.flags.list("r1")
    assert len(flags) == 1
    assert flags[0].type is FlagType.PAIN
    assert flags[0].reason == "pain mentioned 3 days in a row"


def test_pain_streak_flag_is_deduplicated(sig, store, clock):
    for d in (1, 2):
        _seed(store, EntryKind.PAIN, d, 3, clock)
    sig.record_pain("r1", 3)
    sig.record_pain("r1", 4)
    assert len(store.flags.list("r1")) == 1


def test_mild_pain_does_not_flag(sig, store, clock):
    for d in (1, 2):
        _seed(store, EntryKind.PAIN, d, 3, clock)
    sig.record_pain("r1", 1)
    assert store.flags.list() == []


def test_mood_needs_three_baseline_entries(sig, store, clock):
    _seed(store, EntryKind.MOOD, 5, 5, clock, n=2)
    _seed(store, EntryKind.MOOD, 0, 1, clock)
    assert sig.mood_changed_from_usual("r1", clock.now()).changed is False


def test_mood_needs_window_entries(sig, store, clock):
    _seed(store, EntryKind.MOOD, 5, 5, clock, n=4)
    r = sig.mood_changed_from_usual("r1", clock.now())
    assert r.changed is False and r.recent_mean is None


def test_mood_drop_exactly_at_threshold(sig, store, clock):
    _seed(store, EntryKind.MOOD, 6, 4, clock, n=3)
    _seed(store, EntryKind.MOOD, 0, 3, clock)
    r = sig.mood_changed_from_usual("r1", clock.now())
    assert r.changed is True
    assert r.baseline_mean == 4 and r.recent_mean == 3


def test_mood_small_drop_not_changed(sig, store, clock):
    _seed(store, EntryKind.MOOD, 6, 4, clock, n=3)
    _seed(store, EntryKind.MOOD, 0, 3.5, clock)
    assert sig.mood_changed_from_usual("r1", clock.now()).changed is False


def test_mood_baseline_excludes_window_and_old_entries(sig, store, clock):
    _seed(store, EntryKind.MOOD, 30, 1, clock, n=5)  # too old
    _seed(store, EntryKind.MOOD, 6, 4, clock, n=3)
    r = sig.mood_changed_from_usual("r1", clock.now())
    assert r.baseline_mean == 4


def test_record_mood_lower_raises_distress_flag_once(sig, store, clock):
    _seed(store, EntryKind.MOOD, 6, 5, clock, n=3)
    sig.record_mood("r1", 2)
    sig.record_mood("r1", 2)
    flags = store.flags.list("r1")
    assert len(flags) == 1
    assert flags[0].type is FlagType.DISTRESS
    assert flags[0].reason == "mood lower than usual"


def test_record_mood_normal_does_not_flag(sig, store, clock):
    _seed(store, EntryKind.MOOD, 6, 4, clock, n=3)
    sig.record_mood("r1", 4)
    assert store.flags.list() == []


def test_hydration_counts_today_only(sig, store, clock):
    _seed(store, EntryKind.DRINK, 0, None, clock, n=3)
    _seed(store, EntryKind.DRINK, 1, None, clock, n=2)
    assert sig.hydration_today("r1", clock.now()).drinks == 3


def test_repeat_questions_counted_not_flagged(sig, store, clock):
    for _ in range(6):
        sig.record_repeat_question("r1")
    assert sig.repeat_question_count("r1", clock.now()).count == 6
    assert store.flags.list() == []


def test_repeat_count_resets_next_day(sig, clock):
    sig.record_repeat_question("r1")
    clock.advance(days=1)
    assert sig.repeat_question_count("r1", clock.now()).count == 0


def test_raise_flag_requires_reason(sig):
    for bad in ("", "   "):
        with pytest.raises(ValueError):
            sig.raise_flag("r1", FlagType.NO_ANSWER, bad)


def test_raise_flag_dedupes_open_same_type_only(sig, store):
    a = sig.raise_flag("r1", FlagType.NO_ANSWER, "no answer", call_id="c1")
    b = sig.raise_flag("r1", FlagType.NO_ANSWER, "again")
    assert a.id == b.id
    c = sig.raise_flag("r1", FlagType.DISTRESS, "mood lower than usual")
    d = sig.raise_flag("r2", FlagType.NO_ANSWER, "no answer")
    assert len({a.id, c.id, d.id}) == 3
    assert len(store.flags.list()) == 3


def test_resolve_flag_then_new_flag_allowed(sig, store, clock):
    a = sig.raise_flag("r1", FlagType.PAIN, "pain mentioned 3 days in a row")
    r = sig.resolve_flag(a.id)
    assert r.resolved_at == clock.now()
    assert store.flags.list("r1") == []
    b = sig.raise_flag("r1", FlagType.PAIN, "pain mentioned 3 days in a row")
    assert b.id != a.id


def test_resolve_unknown_flag_raises(sig):
    with pytest.raises(KeyError):
        sig.resolve_flag("nope")


def test_record_drink_keeps_what_was_drunk(sig, store):
    entry = sig.record_drink("r1", note="tea")
    assert entry.note == "tea"
    assert store.entries.entries("r1")[0].note == "tea"
