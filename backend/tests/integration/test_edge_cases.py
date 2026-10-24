"""Adversarial edge cases run through the real container.

Tests marked xfail(strict=True) record known bugs; when a bug is fixed the test starts
passing, strict mode fails the suite, and the marker must be removed.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from bellhop.container import Settings, build_container
from bellhop.domain import CallStatus, Robot, RobotStatus, Urgency
from bellhop.domain.events import CallRaised, CallScored
from bellhop.services.call_service import CallNotFound


@pytest.fixture
def app():
    return build_container(Settings(seed_demo=True))


def _robot(app, robot_id="robot_1"):
    return app.store.robots.get(robot_id)


def _nurse_tasks(app):
    return {n.id: n.open_tasks for n in app.store.nurses.list_all()}


def _take_nurses_off_shift(app):
    for nurse in app.store.nurses.list_all():
        nurse.on_shift = False
        app.store.nurses.save(nurse)


# --- robot contention -------------------------------------------------------------------


def test_second_call_never_double_assigns_busy_robot(app):
    first = app.call_service.raise_call("12")
    second = app.call_service.raise_call("14")
    first, second = app.store.calls.get(first.id), app.store.calls.get(second.id)

    assert first.robot_id == "robot_1"
    assert second.robot_id is None
    assert second.status is CallStatus.ASSIGNED
    assert len(second.assigned_to) == 1  # fell back to a nurse
    assert second.assigned_to[0].startswith("nurse_")
    assert [c for c in app.gateway.commands if c[0] == "go_to"] == [("go_to", "robot_1", "12")]


def test_second_call_escalates_when_robot_busy_and_no_nurse_on_shift(app):
    _take_nurses_off_shift(app)
    app.call_service.raise_call("12")
    second = app.call_service.raise_call("14")
    assert app.store.calls.get(second.id).status is CallStatus.ESCALATED
    assert app.store.calls.get(second.id).robot_id is None
    assert len([c for c in app.gateway.commands if c[0] == "go_to"]) == 1


def test_concurrent_calls_to_same_room_use_one_robot_command(app):
    first = app.call_service.raise_call("12")
    second = app.call_service.raise_call("12")
    assert app.store.calls.get(first.id).robot_id == "robot_1"
    assert app.store.calls.get(second.id).robot_id is None
    assert [c for c in app.gateway.commands if c[0] == "go_to"] == [("go_to", "robot_1", "12")]


def test_threaded_calls_never_double_assign_single_robot():
    for _ in range(100):
        app = build_container(Settings(seed_demo=True))
        barrier = Barrier(2)

        def ring(room, app=app, barrier=barrier):
            barrier.wait()
            return app.call_service.raise_call(room).id

        with ThreadPoolExecutor(2) as pool:
            ids = list(pool.map(ring, ["12", "14"]))
        with_robot = [i for i in ids if app.store.calls.get(i).robot_id == "robot_1"]
        assert len(with_robot) == 1
        assert len([c for c in app.gateway.commands if c[0] == "go_to"]) == 1


def test_low_battery_robot_skipped_and_nurse_used(app):
    app.store.robots.save(Robot(id="robot_1", battery=0.1, room="lobby"))
    call = app.call_service.raise_call("14")
    stored = app.store.calls.get(call.id)
    assert stored.robot_id is None
    assert stored.assigned_to and stored.assigned_to[0].startswith("nurse_")
    assert app.gateway.commands == []
    assert _robot(app).status is RobotStatus.IDLE


def test_low_battery_robot_and_no_nurse_escalates(app):
    _take_nurses_off_shift(app)
    app.store.robots.save(Robot(id="robot_1", battery=0.05))
    call = app.call_service.raise_call("12")
    assert app.store.calls.get(call.id).status is CallStatus.ESCALATED


def test_robot_at_exact_minimum_battery_is_usable(app):
    app.store.robots.save(Robot(id="robot_1", battery=0.2))
    call = app.call_service.raise_call("14")
    assert app.store.calls.get(call.id).robot_id == "robot_1"


@pytest.mark.parametrize("status", [RobotStatus.CHARGING, RobotStatus.FAULT])
def test_unavailable_robot_status_not_dispatched(app, status):
    app.store.robots.save(Robot(id="robot_1", status=status))
    call = app.call_service.raise_call("14")
    assert app.store.calls.get(call.id).robot_id is None


def test_robot_idle_again_after_call_resolves(app):
    call = app.call_service.raise_call("14")
    assert _robot(app).status is RobotStatus.BUSY
    app.call_service.mark_in_visit(call.id)
    app.call_service.resolve(call.id)
    assert _robot(app).status is RobotStatus.IDLE


def test_next_call_dispatched_to_robot_after_first_resolves(app):
    first = app.call_service.raise_call("14")
    app.call_service.resolve(first.id)
    second = app.call_service.raise_call("14")
    assert app.store.calls.get(second.id).robot_id == "robot_1"


def test_robot_released_when_escalated_call_resolves(app):
    call = app.call_service.raise_call("14")
    app.call_service.score(call.id, Urgency.EMERGENCY, "fall")
    app.call_service.resolve(call.id)
    assert _robot(app).status is RobotStatus.IDLE


class _BoomGateway:
    def go_to(self, robot_id, room):
        raise RuntimeError("radio down")

    def set_led(self, robot_id, state):
        pass


def test_failed_robot_command_does_not_strand_robot_or_call(app):
    app.dispatcher._gateway = _BoomGateway()
    call = app.call_service.raise_call("14")
    stored = app.store.calls.get(call.id)
    assert _robot(app).status is RobotStatus.IDLE or stored.status is CallStatus.ESCALATED


# --- unknown rooms / lifecycle ----------------------------------------------------------


def test_call_from_unknown_room_has_no_resident_and_flows(app):
    call = app.call_service.raise_call("999")
    stored = app.store.calls.get(call.id)
    assert stored.resident_id is None
    assert stored.status is CallStatus.ASSIGNED
    app.call_service.score(call.id, Urgency.NURSE_SOON, "unknown")
    app.call_service.resolve(call.id)
    (visit,) = app.store.visits.list_all()
    assert visit.resident_id is None


def test_operations_on_unknown_call_id_raise_call_not_found(app):
    with pytest.raises(CallNotFound):
        app.call_service.score("nope", Urgency.CHAT, "x")
    with pytest.raises(CallNotFound):
        app.call_service.resolve("nope")
    with pytest.raises(CallNotFound):
        app.call_service.ack_by_nurse("nope", "nurse_priya")


def test_resolving_twice_raises_and_creates_one_visit(app):
    call = app.call_service.raise_call("12")
    app.call_service.resolve(call.id)
    with pytest.raises(Exception, match="resolved"):
        app.call_service.resolve(call.id)
    assert len(app.store.visits.list_all()) == 1
    assert app.analytics.resolved_without_nurse() <= 1


def test_ack_before_escalation_is_rejected_and_leaves_state(app):
    call = app.call_service.raise_call("12")
    with pytest.raises(Exception, match="nurse_acked"):
        app.call_service.ack_by_nurse(call.id, "nurse_priya")
    stored = app.store.calls.get(call.id)
    assert stored.status is CallStatus.ASSIGNED
    assert "nurse_extra" not in stored.assigned_to


def test_ack_twice_is_rejected(app):
    call = app.call_service.raise_call("12")
    app.call_service.score(call.id, Urgency.NURSE_SOON, "pain")
    app.call_service.ack_by_nurse(call.id, "nurse_priya")
    with pytest.raises(Exception, match="nurse_acked"):
        app.call_service.ack_by_nurse(call.id, "nurse_sam")


def test_ack_by_unknown_nurse_is_rejected(app):
    call = app.call_service.raise_call("12")
    app.call_service.score(call.id, Urgency.NURSE_SOON, "pain")
    with pytest.raises(LookupError):
        app.call_service.ack_by_nurse(call.id, "nurse_ghost")


def test_resolving_acked_call_is_not_credited_to_robot(app):
    call = app.call_service.raise_call("12")
    app.call_service.score(call.id, Urgency.NURSE_SOON, "pain")
    app.call_service.ack_by_nurse(call.id, "nurse_priya")
    app.call_service.resolve(call.id)
    assert app.analytics.resolved_without_nurse() == 0


# --- alerts -----------------------------------------------------------------------------


def test_urgency_3_then_4_sends_exactly_one_of_each_level(app):
    call = app.call_service.raise_call("12")
    app.call_service.score(call.id, Urgency.NURSE_SOON, "pain")
    app.call_service.score(call.id, Urgency.EMERGENCY, "fall")
    levels = sorted(a.level for a in app.notifier.sent)
    assert levels == [Urgency.NURSE_SOON, Urgency.EMERGENCY]
    assert len(app.store.alerts.for_call(call.id)) == 2
    assert app.store.calls.get(call.id).status is CallStatus.ESCALATED


def test_urgency_4_then_3_sends_only_the_emergency_alert(app):
    call = app.call_service.raise_call("12")
    app.call_service.score(call.id, Urgency.EMERGENCY, "fall")
    app.call_service.score(call.id, Urgency.NURSE_SOON, "pain")
    assert [a.level for a in app.notifier.sent] == [Urgency.EMERGENCY]


@pytest.mark.parametrize("level", [Urgency.NURSE_SOON, Urgency.EMERGENCY])
def test_rescoring_same_level_never_duplicates_alert(app, level):
    call = app.call_service.raise_call("12")
    for _ in range(5):
        app.call_service.score(call.id, level, "pain")
    assert len(app.notifier.sent) == 1
    assert len(app.store.alerts.for_call(call.id)) == 1


def test_low_urgency_scores_never_alert_or_escalate(app):
    call = app.call_service.raise_call("14")
    app.call_service.score(call.id, Urgency.CHAT, "social")
    app.call_service.score(call.id, Urgency.ROUTINE, "request")
    assert app.notifier.sent == []
    assert app.store.calls.get(call.id).status is CallStatus.ASSIGNED


@pytest.mark.parametrize("level", [Urgency.NURSE_SOON, Urgency.EMERGENCY])
def test_no_nurse_on_shift_still_alerts_as_broadcast(app, level):
    _take_nurses_off_shift(app)
    call = app.call_service.raise_call("12")
    app.call_service.score(call.id, level, "pain")
    (alert,) = app.notifier.sent
    assert alert.nurse_id is None
    assert alert.level is level
    assert set(_nurse_tasks(app).values()) == {0}


def test_no_nurse_urgency_3_then_4_gives_two_alerts(app):
    _take_nurses_off_shift(app)
    call = app.call_service.raise_call("12")
    app.call_service.score(call.id, Urgency.NURSE_SOON, "pain")
    app.call_service.score(call.id, Urgency.EMERGENCY, "fall")
    assert [a.level for a in app.notifier.sent] == [Urgency.NURSE_SOON, Urgency.EMERGENCY]


def test_alert_message_falls_back_when_no_summary_or_transcript(app):
    call = app.call_service.raise_call("12")
    app.call_service.score(call.id, Urgency.NURSE_SOON, "pain")
    assert "12" in app.notifier.sent[0].message


def test_downscoring_keeps_first_category(app):
    call = app.call_service.raise_call("12")
    app.call_service.score(call.id, Urgency.EMERGENCY, "fall")
    app.call_service.score(call.id, Urgency.CHAT, "social")
    stored = app.store.calls.get(call.id)
    assert (stored.urgency, stored.category) == (Urgency.EMERGENCY, "fall")


def test_scoring_a_resolved_call_does_not_page_nurses(app):
    call = app.call_service.raise_call("14")
    app.call_service.resolve(call.id)
    app.call_service.score(call.id, Urgency.EMERGENCY, "late")
    assert app.notifier.sent == []


# --- nurse bookkeeping ------------------------------------------------------------------


def test_alerts_balance_open_tasks_across_nurses(app):
    for _ in range(2):
        call = app.call_service.raise_call("12")
        app.call_service.score(call.id, Urgency.NURSE_SOON, "pain")
    assert sorted(_nurse_tasks(app).values()) == [1, 1]


def test_rescoring_and_escalating_to_emergency_does_not_inflate_open_tasks(app):
    call = app.call_service.raise_call("12")
    app.call_service.score(call.id, Urgency.NURSE_SOON, "pain")
    app.call_service.score(call.id, Urgency.NURSE_SOON, "pain")
    app.call_service.score(call.id, Urgency.EMERGENCY, "fall")
    assert sum(_nurse_tasks(app).values()) == 1


def test_open_tasks_decrease_after_resolve(app):
    call = app.call_service.raise_call("12")
    app.call_service.score(call.id, Urgency.NURSE_SOON, "pain")
    assert sum(_nurse_tasks(app).values()) == 1
    app.call_service.ack_by_nurse(call.id, app.notifier.sent[0].nurse_id)
    app.call_service.resolve(call.id)
    assert sum(_nurse_tasks(app).values()) == 0


def test_dispatch_assigned_nurse_counts_toward_open_tasks(app):
    call = app.call_service.raise_call("12")  # falls-risk resident: robot plus nurse
    stored = app.store.calls.get(call.id)
    nurse_ids = [i for i in stored.assigned_to if i.startswith("nurse_")]
    assert nurse_ids
    assert _nurse_tasks(app)[nurse_ids[0]] >= 1


# --- memory -----------------------------------------------------------------------------


def test_recall_never_leaks_other_residents_facts(app):
    margaret = app.memory.recall("res_margaret", "coffee black paper daughter Ruth Wednesdays")
    arthur = app.memory.recall("res_arthur", "tea sugar grandson Tom vet hip pain", k=10)
    assert all(f.resident_id == "res_margaret" for f in margaret)
    assert all(f.resident_id == "res_arthur" for f in arthur)
    assert not any("Tom" in f.text or "sugar" in f.text for f in arthur)


def test_recall_for_resident_without_facts_is_empty(app):
    assert app.memory.recall("res_nobody", "tea") == []
    assert app.memory.prompt_context("res_nobody", "tea") == ""


def test_recall_edge_inputs_do_not_crash(app):
    assert app.memory.recall("res_margaret", "") == []
    assert app.memory.recall("res_margaret", "tea", k=0) == []
    assert app.memory.recall("res_margaret", "tea", k=-1) == []
    assert app.memory.recall("res_margaret", "zzzz qqqq") == []


def test_memory_added_later_is_isolated_per_resident(app):
    app.memory.remember("res_arthur", "Allergic to penicillin", tags=["health"])
    assert app.memory.recall("res_margaret", "penicillin allergic") == []
    assert len(app.memory.recall("res_arthur", "penicillin")) == 1


# --- event bus resilience ---------------------------------------------------------------


def test_raising_call_raised_handler_does_not_stop_call_creation(app):
    def boom(event):
        raise RuntimeError("bad subscriber")

    app.bus.subscribe(CallRaised, boom)
    call = app.call_service.raise_call("12")
    stored = app.store.calls.get(call.id)
    assert stored is not None
    assert stored.status is CallStatus.ASSIGNED  # dispatcher still ran


def test_raising_scored_handler_does_not_block_alert_or_state(app):
    def boom(event):
        raise RuntimeError("bad subscriber")

    app.bus.subscribe(CallScored, boom)
    call = app.call_service.raise_call("12")
    app.call_service.score(call.id, Urgency.EMERGENCY, "fall")
    assert len(app.notifier.sent) == 1
    assert app.store.calls.get(call.id).status is CallStatus.ESCALATED


# --- analytics / feedback ---------------------------------------------------------------


def test_analytics_with_zero_calls_has_no_division_by_zero():
    empty = build_container(Settings())
    assert empty.analytics.resolved_without_nurse() == 0
    assert empty.analytics.minutes_saved() == 0.0
    assert empty.analytics.share_answered_within() == 0.0
    assert empty.analytics.calls_by("room") == {}
    assert empty.analytics.calls_by("hour") == {}
    assert empty.analytics.labelled_examples() == []


def test_analytics_calls_without_response_do_not_divide_by_zero(app):
    app.call_service.raise_call("12")
    assert app.analytics.share_answered_within() == 0.0


def test_labelled_examples_after_nurse_override(app):
    call = app.call_service.raise_call("12")
    app.call_service.add_turn(call.id, "resident", "I feel dizzy")
    app.call_service.score(call.id, Urgency.ROUTINE, "dizzy")
    app.call_service.resolve(call.id)
    app.feedback.nurse_override(call.id, Urgency.EMERGENCY)
    (example,) = app.analytics.labelled_examples()
    assert example["call_id"] == call.id
    assert example["robot_urgency"] == 2
    assert example["nurse_urgency"] == 4
    assert example["transcript"] == [{"speaker": "resident", "text": "I feel dizzy"}]


def test_labelled_examples_excludes_visits_without_override(app):
    call = app.call_service.raise_call("12")
    app.call_service.resolve(call.id)
    app.feedback.rate(call.id, 5, "happy")
    assert app.analytics.labelled_examples() == []


def test_nurse_override_before_resolution_raises_lookup_error(app):
    call = app.call_service.raise_call("12")
    with pytest.raises(LookupError):
        app.feedback.nurse_override(call.id, Urgency.EMERGENCY)


def test_rating_out_of_range_rejected(app):
    call = app.call_service.raise_call("12")
    app.call_service.resolve(call.id)
    for bad in (0, 6, -1):
        with pytest.raises(ValueError):
            app.feedback.rate(call.id, bad)


def test_visit_created_exactly_once_per_resolved_call(app):
    call = app.call_service.raise_call("12")
    app.call_service.resolve(call.id)
    app.feedback.record_resolution(call.id, "robot_1")
    app.feedback.record_resolution(call.id, "robot_1")
    assert [v.call_id for v in app.store.visits.list_all()] == [call.id]


def test_unresolved_calls_have_no_visit(app):
    app.call_service.raise_call("12")
    assert app.store.visits.list_all() == []


def test_one_visit_per_call_across_many_calls(app):
    ids = [app.call_service.raise_call(room).id for room in ("12", "14", "12")]
    for call_id in ids:
        app.call_service.resolve(call_id)
    assert sorted(v.call_id for v in app.store.visits.list_all()) == sorted(ids)


def test_call_never_visited_by_robot_not_credited_to_robot(app):
    app.call_service.raise_call("12")  # takes the only robot
    second = app.call_service.raise_call("14")  # nurse fallback, no robot
    assert app.store.calls.get(second.id).robot_id is None
    app.call_service.resolve(second.id)
    assert app.analytics.resolved_without_nurse() == 0


def test_unscored_call_resolution_not_counted_as_saved_minutes(app):
    _take_nurses_off_shift(app)
    app.store.robots.save(Robot(id="robot_1", status=RobotStatus.FAULT))
    call = app.call_service.raise_call("12")  # no robot, no nurse: escalated
    app.call_service.resolve(call.id)
    assert app.analytics.minutes_saved() == 0.0
