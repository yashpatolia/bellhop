"""Turns call events into robot LED states. Gateway failures never propagate."""

from __future__ import annotations

import logging

from bellhop.domain import LedState, Urgency
from bellhop.domain.events import CallAssigned, CallResolved, CallScored
from bellhop.ports import CallRepository, EventBus, RobotGateway

logger = logging.getLogger(__name__)


class RobotSignals:
    def __init__(self, calls: CallRepository, gateway: RobotGateway, bus: EventBus) -> None:
        self._calls = calls
        self._gateway = gateway
        bus.subscribe(CallScored, self._on_scored)
        bus.subscribe(CallAssigned, self._on_assigned)
        bus.subscribe(CallResolved, self._on_resolved)

    def _on_scored(self, event: CallScored) -> None:
        if event.urgency >= Urgency.EMERGENCY:
            self._signal(event.call_id, LedState.EMERGENCY)
        elif event.urgency >= Urgency.NURSE_SOON:
            self._signal(event.call_id, LedState.NURSE_ON_WAY)

    def _on_assigned(self, event: CallAssigned) -> None:
        self._signal(event.call_id, LedState.LISTENING)

    def _on_resolved(self, event: CallResolved) -> None:
        self._signal(event.call_id, LedState.IDLE)

    def _signal(self, call_id: str, state: LedState) -> None:
        call = self._calls.get(call_id)
        if call is None or call.robot_id is None:
            return
        try:
            self._gateway.set_led(call.robot_id, state.value)
        except Exception:
            logger.exception("set_led %s failed for %s", state.value, call.robot_id)
