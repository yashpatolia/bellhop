"""The three demo scenes from docs/plan/01-project.md, run through the real container."""

import pytest

from bellhop.container import Settings, build_container
from bellhop.domain import CallStatus, Urgency


@pytest.fixture
def app():
    return build_container(Settings(seed_demo=True))


def test_scene1_lonely_resident_resolved_by_robot_without_nurse_alert(app):
    call = app.call_service.raise_call("12")
    stored = app.store.calls.get(call.id)
    assert stored.status is CallStatus.ASSIGNED
    assert stored.robot_id == "robot_1"
    assert app.gateway.commands == [("go_to", "robot_1", "12")]

    context = app.memory.prompt_context(stored.resident_id, "can I get a cup of tea and a chat")
    assert "two sugars" in context

    app.call_service.mark_in_visit(call.id)
    app.call_service.score(call.id, Urgency.CHAT, "social")
    app.call_service.resolve(call.id)

    assert app.notifier.sent == []
    assert app.analytics.resolved_without_nurse() == 1
    assert app.analytics.minutes_saved() == 4.0


def test_scene2_hip_pain_sends_nurse_one_summary_and_nurse_can_ack(app):
    call = app.call_service.raise_call("12")
    app.call_service.mark_in_visit(call.id)
    app.call_service.add_turn(call.id, "resident", "My hip has been aching since last night")
    app.call_service.score(call.id, Urgency.NURSE_SOON, "pain", summary="Hip pain since last night")

    (alert,) = app.notifier.sent
    assert alert.level is Urgency.NURSE_SOON
    assert alert.nurse_id is not None
    assert "Hip pain" in alert.message
    assert app.store.calls.get(call.id).status is CallStatus.ESCALATED

    app.call_service.ack_by_nurse(call.id, alert.nurse_id)
    assert app.store.calls.get(call.id).status is CallStatus.NURSE_ACKED


def test_scene3_fall_broadcasts_immediately_and_is_not_counted_as_robot_resolved(app):
    call = app.call_service.raise_call("12")
    app.call_service.score(call.id, Urgency.EMERGENCY, "fall", summary="Resident says she fell")

    (alert,) = app.notifier.sent
    assert alert.level is Urgency.EMERGENCY
    assert alert.nurse_id is None

    app.call_service.resolve(call.id)
    assert app.analytics.resolved_without_nurse() == 0


def test_urgency_never_ratchets_down_across_services(app):
    call = app.call_service.raise_call("12")
    app.call_service.score(call.id, Urgency.EMERGENCY, "fall")
    app.call_service.score(call.id, Urgency.CHAT, "social")
    assert app.store.calls.get(call.id).urgency is Urgency.EMERGENCY
    assert len(app.notifier.sent) == 1
