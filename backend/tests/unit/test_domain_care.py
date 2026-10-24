from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bellhop.domain.care import CareEntry, EntryKind, FlagType, Preferences

T0 = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)


def test_exactly_four_flag_types_to_avoid_alarm_fatigue():
    assert {f.value for f in FlagType} == {"pain", "asks_for_nurse", "distress", "no_answer"}


def test_care_entry_scores_are_bounded_one_to_five():
    CareEntry(id="e1", resident_id="r1", kind=EntryKind.MOOD, value=5, at=T0)
    with pytest.raises(ValidationError):
        CareEntry(id="e2", resident_id="r1", kind=EntryKind.MOOD, value=6, at=T0)


def test_drink_and_repeat_entries_need_no_value():
    entry = CareEntry(id="e3", resident_id="r1", kind=EntryKind.DRINK, at=T0)
    assert entry.value is None


def test_preferences_default_to_no_special_handling():
    prefs = Preferences(resident_id="r1")
    assert (prefs.hard_of_hearing, prefs.quiet_mode, prefs.night_mode) == (False, False, False)
    assert prefs.favourite_drink is None
