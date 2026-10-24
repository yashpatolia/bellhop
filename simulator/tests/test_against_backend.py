"""The simulator against the real backend: what it seeds is what the dashboard will read."""

import random
from datetime import UTC, datetime

import pytest

from bellhop_sim import data, seeding
from bellhop_sim.client import Backend
from bellhop_sim.live import Home, new_fleet
from bellhop_sim.visit import Pace, VisitOptions

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def api(backend_url):
    api = Backend(backend_url)
    api.wait_ready()
    seeding.seed_home(api, datetime.now(UTC))
    return api


def test_every_resident_arrives_with_facts_medical_history_and_care_entries(api):
    people = {r["id"]: r for r in api.get("/residents")}
    assert set(people) == {r["id"] for r in data.residents()}
    for r in data.residents():
        stored = api.get(f"/residents/{r['id']}/memory/all")
        pending = api.get(f"/residents/{r['id']}/memory/pending")
        assert len(stored) + len(pending) == len(r["facts"]), r["id"]
        assert len(pending) == sum(1 for f in r["facts"] if f["status"] == "pending")
        assert api.get(f"/residents/{r['id']}/medical")["mobility"] == r["medical"]["mobility"]
        assert len(api.get(f"/residents/{r['id']}/care/history", params={"days": 14})) == 14


def test_a_fact_heard_several_times_is_counted_that_often(api):
    [fact] = [f for f in api.get("/residents/r101/memory/all") if f["text"].startswith("Takes tea")]
    assert fact["times_seen"] == 6
    assert fact["quote"] == "I take two sugars, always have"


def test_history_is_imported_with_its_conversations_and_counts_in_metrics(api):
    calls = api.get("/calls", params={"limit": 1000})
    assert len(calls) >= 80
    assert all(c["status"] == "resolved" and c["transcript"] for c in calls)
    assert api.get("/metrics")["resolved_without_nurse"] > 0
    assert api.get("/alerts") == []


def test_seeding_twice_changes_nothing(api):
    before = len(api.get("/calls", params={"limit": 1000}))
    seeding.seed_home(api, datetime.now(UTC), history=False)
    assert len(api.get("/calls", params={"limit": 1000})) == before
    assert len(api.get("/residents")) == len(data.residents())


def test_a_played_emergency_reaches_the_nurse_and_resolves_after_the_ack(api):
    home = Home(
        api, Pace(0), random.Random(3), new_fleet(), VisitOptions(nurse_delay_s=1, poll_s=1)
    )
    home.heartbeat()
    scenario = next(s for s in data.scenarios() if s.category == "fall")
    assert home.press(home.resident("r103"), scenario)
    home.join(timeout=30)
    call = api.get("/calls", params={"limit": 1})[0]
    assert (call["urgency"], call["status"], call["resolved_by_robot"]) == (4, "resolved", False)
    assert [a for a in api.get("/alerts") if a["call_id"] == call["id"] and a["level"] == 4]
    home.heartbeat()
    assert {r["status"] for r in api.get("/robots")} <= {"idle", "charging"}


def test_a_call_rung_from_the_dashboard_is_played_by_the_robot_that_was_sent(api):
    home = Home(
        api, Pace(0), random.Random(5), new_fleet(), VisitOptions(nurse_delay_s=1, poll_s=1)
    )
    home.heartbeat()
    call = api.post("/calls", {"room": "108"})  # what the dashboard's "send a robot" does
    assert call["robot_id"]
    assert home.adopt(min_age_s=0) == 1
    assert home.adopt(min_age_s=0) == 0  # taken once only
    home.join(timeout=30)
    done = api.get(f"/calls/{call['id']}")
    assert done["status"] in ("resolved", "escalated", "nurse_acked")
    assert done["transcript"]


def test_a_call_to_a_place_with_no_resident_is_played_too(api):
    home = Home(
        api, Pace(0), random.Random(6), new_fleet(), VisitOptions(nurse_delay_s=1, poll_s=1)
    )
    home.heartbeat()
    call = api.post("/calls", {"room": "lobby"})
    assert call["robot_id"]
    assert home.adopt(min_age_s=0) == 1
    home.join(timeout=30)
    assert api.get(f"/calls/{call['id']}")["transcript"]
