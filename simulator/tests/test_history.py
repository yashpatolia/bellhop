from datetime import UTC, datetime

from bellhop_sim import data
from bellhop_sim.history import DAYS, earlier_today, past_calls

NOW = datetime(2026, 10, 24, 15, 0, tzinfo=UTC)


def test_history_is_the_same_every_time():
    assert past_calls(NOW) == past_calls(NOW)


def test_every_call_belongs_to_a_known_resident_and_the_last_two_weeks():
    ids = {r["id"] for r in data.residents()}
    for c in past_calls(NOW):
        assert c.resident_id in ids
        age_days = (NOW - c.created_at).days
        assert 0 <= age_days <= DAYS


def test_the_pattern_counts_are_what_the_data_file_says():
    pattern = data.patterns()["r103"]
    expected = sum(count for _, count, _, _ in pattern)
    assert len([c for c in past_calls(NOW) if c.resident_id == "r103"]) == expected


def test_a_resident_with_a_night_pattern_rings_at_night():
    hours = {c.created_at.astimezone().hour for c in past_calls(NOW) if c.category == "breathing"}
    assert hours <= {22, 23, 0, 1}


def test_calls_that_need_a_nurse_are_not_credited_to_the_robot():
    assert all(c.by_robot == (c.urgency <= 2) for c in past_calls(NOW))


def test_earlier_today_stays_inside_today_and_is_in_order():
    calls = earlier_today(NOW)
    assert calls and all(c.created_at.date() == NOW.date() for c in calls)
    assert [c.created_at for c in calls] == sorted(c.created_at for c in calls)
