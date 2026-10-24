"""Turns high-urgency scores and unreachable robots into staff alerts."""

from __future__ import annotations

from bellhop.domain import Alert, Call, Urgency
from bellhop.domain.events import AlertRaised, CallScored, RobotUnreachable
from bellhop.ports import (
    AlertRepository,
    CallRepository,
    Clock,
    EventBus,
    IdGenerator,
    Notifier,
    NurseRepository,
)

_SUMMARY_TURNS = 2


class Liaison:
    def __init__(
        self,
        calls: CallRepository,
        nurses: NurseRepository,
        alerts: AlertRepository,
        notifier: Notifier,
        bus: EventBus,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._calls = calls
        self._nurses = nurses
        self._alerts = alerts
        self._notifier = notifier
        self._bus = bus
        self._clock = clock
        self._ids = ids
        bus.subscribe(CallScored, self._on_scored)
        bus.subscribe(RobotUnreachable, self._on_robot_unreachable)

    def _on_scored(self, event: CallScored) -> None:
        if event.urgency < Urgency.NURSE_SOON:
            return
        call = self._calls.get(event.call_id)
        if call is None:
            return
        if any(a.level >= event.urgency for a in self._alerts.for_call(call.id)):
            return
        nurse_id = None
        if event.urgency < Urgency.EMERGENCY:
            nurse_id = self._claim_nurse(call)
        self._alert(call, event.urgency, nurse_id, self._summary(call))

    def _on_robot_unreachable(self, event: RobotUnreachable) -> None:
        """The robot could not be commanded: page a nurse. Never changes the call's urgency."""
        call = self._calls.get(event.call_id)
        if call is None:
            return
        if any(a.level >= Urgency.NURSE_SOON for a in self._alerts.for_call(call.id)):
            return
        message = f"The robot could not be sent to room {call.room}. Please check on the resident."
        self._alert(call, Urgency.NURSE_SOON, self._claim_nurse(call), message)

    def _alert(self, call: Call, level: Urgency, nurse_id: str | None, message: str) -> None:
        alert = Alert(
            id=self._ids.new_id("alert"),
            call_id=call.id,
            nurse_id=nurse_id,
            level=level,
            message=message,
            created_at=self._clock.now(),
        )
        self._alerts.save(alert)
        self._notifier.send(alert)
        self._bus.publish(AlertRaised(alert.id, call.id, alert.level))

    def _claim_nurse(self, call: Call) -> str | None:
        on_shift = self._nurses.list_on_shift()
        if not on_shift:
            return None
        already = [n for n in on_shift if n.id in call.nurse_tasks]  # dispatcher's nurse
        nurse = already[0] if already else min(on_shift, key=lambda n: n.open_tasks)
        call.charge(nurse)
        self._nurses.save(nurse)
        self._calls.save(call)
        return nurse.id

    @staticmethod
    def _summary(call: Call) -> str:
        if call.summary:
            return call.summary
        said = [t.text for t in call.transcript if t.speaker == "resident"]
        if said:
            return " / ".join(said[-_SUMMARY_TURNS:])
        return f"Resident in room {call.room} needs a nurse"
