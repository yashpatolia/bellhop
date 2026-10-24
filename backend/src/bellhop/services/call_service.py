"""Call lifecycle use cases."""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

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


def _locked[F: Callable[..., Any]](fn: F) -> F:
    @functools.wraps(fn)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return fn(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


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
        self._lock = threading.RLock()  # guards read-modify-write of a call

    @_locked
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

    @_locked
    def add_turn(self, call_id: str, speaker: str, text: str) -> None:
        call = self._get(call_id)
        call.add_turn(speaker, text, self._clock.now())
        self._calls.save(call)

    @_locked
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

    @_locked
    def mark_in_visit(self, call_id: str) -> None:
        call = self._get(call_id)
        call.start_visit(self._clock.now())
        self._calls.save(call)

    @_locked
    def resolve(self, call_id: str, by_robot: bool = True) -> None:
        call = self._transition(call_id, CallStatus.RESOLVED)
        # a call that needed a nurse is never credited to the robot alone
        credited = by_robot and call.robot_id is not None and not call.needs_nurse
        call.resolved_by_robot = credited
        self._calls.save(call)
        self._bus.publish(CallResolved(call_id=call_id, by_robot=credited))

    @_locked
    def backfill(
        self,
        room: str,
        urgency: Urgency,
        category: str,
        created_at: datetime,
        resolved_at: datetime,
        *,
        resident_id: str | None = None,
        robot_id: str | None = None,
        summary: str | None = None,
        first_response_at: datetime | None = None,
        by_robot: bool = True,
        turns: Sequence[tuple[str, str, datetime]] = (),
    ) -> Call:
        """Store a finished call from the past (history import). Publishes no events, so it
        raises no alerts and triggers no learning."""
        if resolved_at < created_at:
            raise ValueError("resolved_at is before created_at")
        resident = (
            self._residents.get(resident_id) if resident_id else self._residents.by_room(room)
        )
        call = Call(
            id=self._ids.new_id("call"),
            room=room,
            resident_id=resident.id if resident else None,
            urgency=urgency,
            category=category,
            status=CallStatus.RESOLVED,
            summary=summary,
            robot_id=robot_id,
            assigned_to=[robot_id] if robot_id else [],
            created_at=created_at,
            assigned_at=created_at,
            first_response_at=first_response_at,
            resolved_at=resolved_at,
        )
        call.resolved_by_robot = by_robot and robot_id is not None and not call.needs_nurse
        for speaker, text, at in turns:
            call.add_turn(speaker, text, at)
        self._calls.save(call)
        return call

    @_locked
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
