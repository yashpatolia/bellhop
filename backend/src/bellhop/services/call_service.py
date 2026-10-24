"""Call lifecycle use cases."""

from __future__ import annotations

from bellhop.domain import Call, CallStatus, Urgency
from bellhop.domain.events import CallRaised, CallResolved, CallScored
from bellhop.ports import (
    CallRepository,
    Clock,
    EventBus,
    IdGenerator,
    NurseRepository,
    ResidentRepository,
)

_ESCALATABLE = {
    CallStatus.RINGING,
    CallStatus.ASSIGNED,
    CallStatus.ROBOT_EN_ROUTE,
    CallStatus.IN_VISIT,
}


class CallNotFound(LookupError):
    pass


class CallService:
    def __init__(
        self,
        calls: CallRepository,
        residents: ResidentRepository,
        bus: EventBus,
        clock: Clock,
        ids: IdGenerator,
        nurses: NurseRepository | None = None,
    ) -> None:
        self._nurses = nurses
        self._calls = calls
        self._residents = residents
        self._bus = bus
        self._clock = clock
        self._ids = ids

    def raise_call(self, room: str) -> Call:
        resident = self._residents.by_room(room)
        call = Call(
            id=self._ids.new_id("call"),
            room=room,
            resident_id=resident.id if resident else None,
            created_at=self._clock.now(),
        )
        self._calls.save(call)
        self._bus.publish(CallRaised(call_id=call.id, room=room))
        return call

    def add_turn(self, call_id: str, speaker: str, text: str) -> None:
        call = self._get(call_id)
        call.add_turn(speaker, text, self._clock.now())
        self._calls.save(call)

    def score(
        self, call_id: str, urgency: Urgency, category: str, summary: str | None = None
    ) -> None:
        call = self._get(call_id)
        if call.status in (CallStatus.RESOLVED, CallStatus.CLOSED):
            return  # late triage result for a finished call: ignore, never page
        call.score(urgency, category)
        if summary is not None:
            call.summary = summary
        if call.needs_nurse and call.status in _ESCALATABLE:
            call.transition(CallStatus.ESCALATED, self._clock.now())
        self._calls.save(call)
        assert call.urgency is not None
        self._bus.publish(
            CallScored(call_id=call.id, urgency=call.urgency, category=call.category or category)
        )

    def mark_in_visit(self, call_id: str) -> None:
        self._transition(call_id, CallStatus.IN_VISIT)

    def resolve(self, call_id: str, by_robot: bool = True) -> None:
        call = self._transition(call_id, CallStatus.RESOLVED)
        # a call that needed a nurse is never credited to the robot alone
        self._bus.publish(
            CallResolved(
                call_id=call_id,
                by_robot=by_robot and call.robot_id is not None and not call.needs_nurse,
            )
        )

    def ack_by_nurse(self, call_id: str, nurse_id: str) -> None:
        call = self._get(call_id)
        if self._nurses is not None and self._nurses.get(nurse_id) is None:
            raise LookupError(f"unknown nurse: {nurse_id}")
        call.transition(CallStatus.NURSE_ACKED, self._clock.now())
        if nurse_id not in call.assigned_to:
            call.assigned_to.append(nurse_id)
        self._calls.save(call)

    def _transition(self, call_id: str, to: CallStatus) -> Call:
        call = self._get(call_id)
        call.transition(to, self._clock.now())
        self._calls.save(call)
        return call

    def _get(self, call_id: str) -> Call:
        call = self._calls.get(call_id)
        if call is None:
            raise CallNotFound(call_id)
        return call
