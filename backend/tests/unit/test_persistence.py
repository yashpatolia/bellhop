"""Memory facts, the review queue, care data and medical history survive a backend restart.

A fake SpacetimeDB plays the server. "Restart" means a second container built on the same server.
"""

from datetime import UTC, datetime

import pytest

from bellhop.container import Settings, build_container
from bellhop.domain import Resident, Turn
from bellhop.domain.care import EntryKind, NoteCategory, RefinedNote

from .stdb_fake import FakeStdb

R = "res_ada"


@pytest.fixture
def server() -> FakeStdb:
    return FakeStdb()


def boot(server: FakeStdb):
    c = build_container(
        Settings(store="spacetimedb", guard_timeouts=False), stdb_client=server.client()
    )
    if not c.store.residents.get(R):
        c.store.residents.save(Resident(id=R, name="Ada Reyes", room="21"))
    return c


def test_stored_facts_come_back_with_their_provenance(server):
    c = boot(server)
    c.memory_guard.propose(
        R,
        "Likes jasmine tea",
        ["like"],
        "conversation",
        0.9,
        quote="jasmine, always",
        call_id="call_1",
    )
    again = boot(server)
    [fact] = again.memory_guard.facts(R)
    assert (fact.text, fact.tags, fact.source, fact.confidence) == (
        "Likes jasmine tea", ["like"], "conversation", 0.9
    )  # fmt: skip
    assert (fact.quote, fact.call_id, fact.times_seen) == ("jasmine, always", "call_1", 1)
    assert again.memory.recall(R, "jasmine tea")[0].id == fact.id


def test_hearing_a_fact_again_is_remembered(server):
    c = boot(server)
    c.memory_guard.propose(R, "Likes jasmine tea", ["like"], "conversation", 0.9)
    c.memory_guard.propose(R, "Likes jasmine tea", ["like"], "conversation", 0.9)
    [fact] = boot(server).memory_guard.facts(R)
    assert fact.times_seen == 2


def test_forgetting_a_fact_survives_a_restart(server):
    c = boot(server)
    keep = c.memory_guard.propose(R, "Reads the paper at breakfast", [], "staff").fact
    gone = c.memory_guard.propose(R, "Likes jasmine tea", [], "staff").fact
    assert c.memory_guard.forget(R, gone.id)
    assert [f.id for f in boot(server).memory_guard.facts(R)] == [keep.id]


def test_forgetting_everything_survives_a_restart(server):
    c = boot(server)
    c.memory_guard.propose(R, "Reads the paper at breakfast", [], "staff")
    c.memory_guard.propose(R, "Likes jasmine tea", [], "staff")
    assert c.memory_guard.forget_all(R) == 2
    assert boot(server).memory_guard.facts(R) == []


def test_the_review_queue_survives_a_restart_and_can_be_decided_after_it(server):
    c = boot(server)
    c.memory_guard.propose(
        R, "Dislikes loud television", ["dislike"], "conversation", 0.4, quote="too loud"
    )
    c.memory_guard.propose(R, "Hips ache after lunch", ["health"], "conversation", 0.3)
    again = boot(server)
    pending = {p.text: p for p in again.memory_guard.pending(R)}
    assert set(pending) == {"Dislikes loud television", "Hips ache after lunch"}
    assert pending["Dislikes loud television"].quote == "too loud"
    again.memory_guard.approve(pending["Dislikes loud television"].id, R)
    again.memory_guard.reject(pending["Hips ache after lunch"].id, R)
    third = boot(server)
    assert third.memory_guard.pending(R) == []
    assert [f.text for f in third.memory_guard.facts(R)] == ["Dislikes loud television"]


def test_new_pending_ids_never_collide_with_ones_loaded_after_a_restart(server):
    c = boot(server)
    c.memory_guard.propose(R, "Dislikes loud television", [], "conversation", 0.4)
    again = boot(server)
    again.memory_guard.propose(R, "Hips ache after lunch", [], "conversation", 0.3)
    ids = [p.id for p in again.memory_guard.pending(R)]
    assert len(ids) == len(set(ids)) == 2


def test_care_readings_flags_preferences_and_messages_survive(server):
    c = boot(server)
    at = datetime(2026, 10, 20, 9, tzinfo=UTC)
    for day in range(3):  # three days of pain in a row opens a flag
        c.care_signals.record_pain(R, 3, at=at.replace(day=20 + day))
    c.care_signals.record_mood(R, 4, "call_1", "chatty", at=at)
    c.preferences.update(R, hard_of_hearing=True, favourite_drink="tea")
    c.family.leave_voice_note(R, "Tom visits on Sunday")
    again = boot(server)
    entries = again.care_store.entries.entries(R)
    assert [(e.kind, e.value) for e in entries].count((EntryKind.PAIN, 3)) == 3
    mood = next(e for e in entries if e.kind is EntryKind.MOOD)
    assert (mood.value, mood.call_id, mood.note, mood.at) == (4, "call_1", "chatty", at)
    assert [f.type.value for f in again.care_store.flags.list(R)] == ["pain"]
    prefs = again.care_store.preferences.get(R)
    assert (prefs.hard_of_hearing, prefs.favourite_drink) == (True, "tea")
    assert [m.text for m in again.care_store.messages.list(R)] == ["Tom visits on Sunday"]
    assert [m.text for m in again.family.pending_for_resident(R)] == ["Tom visits on Sunday"]


def test_a_resolved_flag_stays_resolved(server):
    c = boot(server)
    at = datetime(2026, 10, 20, 9, tzinfo=UTC)
    for day in range(3):
        c.care_signals.record_pain(R, 3, at=at.replace(day=20 + day))
    [flag] = c.care_store.flags.list(R)
    c.care_signals.resolve_flag(flag.id)
    assert boot(server).care_store.flags.list(R) == []


def test_medical_history_survives(server):
    c = boot(server)
    c.medical.add_entry(
        R, RefinedNote(category=NoteCategory.CONDITION, text="COPD", since="2018"), "Nurse Okoro"
    )
    c.medical.add_entry(R, RefinedNote(category=NoteCategory.ALLERGY, text="Penicillin"))
    c.medical.add_entry(R, RefinedNote(category=NoteCategory.DIET, text="Soft food"))
    m = boot(server).medical.get(R)
    assert [(x.name, x.since) for x in m.conditions] == [("COPD", "2018")]
    assert (m.allergies, m.diet) == (["Penicillin"], "Soft food")
    assert m.reviewed_by == "Staff" and m.last_review is not None


def test_a_call_remembers_who_resolved_it(server):
    c = boot(server)
    call = c.call_service.raise_call("21")
    c.call_service.resolve(call.id, by_robot=False)
    assert boot(server).store.calls.get(call.id).resolved_by_robot is False


def test_a_dead_server_does_not_stop_the_data_being_used_and_writes_are_retried(server):
    c = boot(server)
    server.down = True
    c.memory_guard.propose(R, "Likes jasmine tea", [], "staff")  # must not raise
    assert [f.text for f in c.memory_guard.facts(R)] == ["Likes jasmine tea"]
    server.down = False
    c.memory_guard.propose(
        R, "Reads the paper at breakfast", [], "staff"
    )  # flushes the backlog first
    assert {f.text for f in boot(server).memory_guard.facts(R)} == {
        "Likes jasmine tea",
        "Reads the paper at breakfast",
    }


def test_an_out_of_date_module_keeps_the_rest_working_in_memory(server, caplog):
    c = boot(server)  # the residents table is there
    server.missing = {
        "memory_fact",
        "pending_fact",
        "care_entry",
        "flag",
        "preferences",
        "family_message",
        "medical_record",
    }
    again = boot(server)  # hydrating the new tables fails
    again.memory_guard.propose(R, "Likes jasmine tea", [], "staff")
    assert [f.text for f in again.memory_guard.facts(R)] == ["Likes jasmine tea"]
    assert "not persisted" in caplog.text
    assert c is not again


def test_the_in_memory_store_is_unchanged():
    c = build_container(Settings(guard_timeouts=False))
    c.memory_guard.propose(R, "Likes jasmine tea", [], "staff")
    assert [f.text for f in c.memory_guard.facts(R)] == ["Likes jasmine tea"]
    assert not hasattr(c.store, "link")


def test_turns_still_round_trip_with_the_call(server):
    c = boot(server)
    call = c.call_service.raise_call("21")
    c.call_service.add_turn(call.id, "resident", "I love jasmine tea")
    assert [t.text for t in boot(server).store.calls.get(call.id).transcript] == [
        "I love jasmine tea"
    ]
    assert Turn  # imported for the type only


def test_a_delivered_voice_note_is_not_delivered_again_after_a_restart(server):
    c = boot(server)
    c.family.leave_voice_note(R, "Tom visits on Sunday")
    c.family.mark_delivered(R)
    again = boot(server)
    assert again.family.pending_for_resident(R) == []
    again.family.leave_voice_note(R, "And bring the dog")
    assert [m.text for m in again.family.pending_for_resident(R)] == ["And bring the dog"]
