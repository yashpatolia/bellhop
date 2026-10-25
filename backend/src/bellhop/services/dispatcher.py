"""Assigns a robot and/or nurse to each new call."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from bellhop.domain import Call, CallStatus, Nurse, Resident, Robot, RobotStatus
from bellhop.domain.events import CallAssigned, CallRaised, RobotAvailable, RobotUnreachable
from bellhop.ports import (
    CallRepository,
    Clock,
    EventBus,
    NurseRepository,
    ResidentRepository,
    RobotGateway,
    RobotRepository,
)

MIN_BATTERY = 0.2

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Decision:
    robot_id: str | None = None
    nurse_id: str | None = None


class DispatchPolicy(Protocol):
    def decide(
        self, call: Call, resident: Resident | None, robots: list[Robot], nurses: list[Nurse]
    ) -> Decision: ...


class DefaultPolicy:
    def decide(
        self, call: Call, resident: Resident | None, robots: list[Robot], nurses: list[Nurse]
    ) -> Decision:
        robot = self._pick_robot(call, robots)
        at_risk = bool(resident and resident.risk_flags)
        nurse = self._pick_nurse(nurses) if at_risk or robot is None else None
        return Decision(robot.id if robot else None, nurse.id if nurse else None)

    @staticmethod
    def _pick_robot(call: Call, robots: list[Robot]) -> Robot | None:
        free = [r for r in robots if r.status is RobotStatus.IDLE and r.battery >= MIN_BATTERY]
        # Only room labels are known, so "nearest" means already in the call's room.
        free.sort(key=lambda r: r.room != call.room)
        return free[0] if free else None

    @staticmethod
    def _pick_nurse(nurses: list[Nurse]) -> Nurse | None:
        on_shift = [n for n in nurses if n.on_shift]
        return min(on_shift, key=lambda n: n.open_tasks, default=None)


class Dispatcher:
    def __init__(
        self,
        calls: CallRepository,
        residents: ResidentRepository,
        robots: RobotRepository,
        nurses: NurseRepository,
        gateway: RobotGateway,
        policy: DispatchPolicy,
        bus: EventBus,
        clock: Clock,
    ) -> None:
        self._calls = calls
        self._residents = residents
        self._robots = robots
        self._nurses = nurses
        self._gateway = gateway
        self._policy = policy
        self._bus = bus
        self._clock = clock
        bus.subscribe(CallRaised, self._on_call_raised)
        bus.subscribe(RobotAvailable, self._on_robot_available)

    def _on_robot_available(self, event: RobotAvailable) -> None:
        """A bell that rang while every robot was busy went to a nurse alone. Once a robot is
        free, send it to the oldest such call so the resident is not left waiting."""
        robot = self._robots.get(event.robot_id)
        if robot is None or robot.status is not RobotStatus.IDLE or robot.battery < MIN_BATTERY:
            return
        waiting = [
            c
            for c in self._calls.list_open()
            if c.status is CallStatus.ASSIGNED and c.robot_id is None
        ]
        if not waiting:
            return
        call = min(waiting, key=lambda c: c.created_at)
        if not self._send_robot(robot.id, call.room):
            return  # the call keeps its nurse; nothing new to tell them
        call.transition(CallStatus.ROBOT_EN_ROUTE, self._clock.now())
        call.robot_id = robot.id
        call.assigned_to = [robot.id, *call.assigned_to]
        self._calls.save(call)
        self._bus.publish(CallAssigned(call_id=call.id, robot_id=robot.id, nurse_id=None))

    def _on_call_raised(self, event: CallRaised) -> None:
        call = self._calls.get(event.call_id)
        if call is None or call.status is not CallStatus.RINGING:
            return  # idempotent: already handled
        resident = self._residents.get(call.resident_id) if call.resident_id else None
        nurses = self._nurses.list_on_shift()
        decision = self._policy.decide(call, resident, self._robots.list_all(), nurses)
        now = self._clock.now()
        robot_id, nurse_id = decision.robot_id, decision.nurse_id
        unreachable = None
        if robot_id and not self._send_robot(robot_id, call.room):
            # A robot that cannot be commanded never leaves a call without an owner: fall back
            # to the policy's nurse choice with no robots, whatever the resident's risk flags.
            unreachable, robot_id = robot_id, None
            nurse_id = nurse_id or self._policy.decide(call, resident, [], nurses).nurse_id
        if robot_id is None and nurse_id is None:
            call.transition(CallStatus.ESCALATED, now)
            self._calls.save(call)
        else:
            call.transition(CallStatus.ASSIGNED, now)
            if robot_id:
                call.transition(CallStatus.ROBOT_EN_ROUTE, now)
            call.assigned_to = [i for i in (robot_id, nurse_id) if i]
            call.robot_id = robot_id
            self._charge_nurse(call, nurse_id)
            self._calls.save(call)
            self._bus.publish(CallAssigned(call_id=call.id, robot_id=robot_id, nurse_id=nurse_id))
        if unreachable:
            self._bus.publish(RobotUnreachable(call_id=call.id, robot_id=unreachable))

    def _charge_nurse(self, call: Call, nurse_id: str | None) -> None:
        nurse = self._nurses.get(nurse_id) if nurse_id else None
        if nurse is not None:
            call.charge(nurse)
            self._nurses.save(nurse)

    def _send_robot(self, robot_id: str, room: str) -> bool:
        """Command the robot; on failure leave it untouched so the call falls back to a nurse."""
        try:
            self._gateway.go_to(robot_id, room)
        except Exception:
            logger.exception("go_to failed for %s", robot_id)
            self._stop_robot(robot_id)
            return False
        robot = self._robots.get(robot_id)
        if robot is not None:
            robot.status = RobotStatus.BUSY
            self._robots.save(robot)
        return True

    def _stop_robot(self, robot_id: str) -> None:
        """Best effort: a go_to that failed or timed out may still land on the Pi later."""
        try:
            self._gateway.stop(robot_id)
        except Exception:
            logger.exception("stop failed for %s", robot_id)
