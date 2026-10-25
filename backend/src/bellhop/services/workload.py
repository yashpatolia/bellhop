"""Frees resources when a call ends: the robot goes idle, nurses' task counts drop."""

from __future__ import annotations

from bellhop.domain import RobotStatus
from bellhop.domain.events import CallResolved, RobotAvailable
from bellhop.ports import CallRepository, EventBus, NurseRepository, RobotRepository


class Workload:
    def __init__(
        self,
        calls: CallRepository,
        robots: RobotRepository,
        nurses: NurseRepository,
        bus: EventBus,
    ) -> None:
        self._calls = calls
        self._robots = robots
        self._nurses = nurses
        self._bus = bus
        bus.subscribe(CallResolved, self._on_resolved)

    def _on_resolved(self, event: CallResolved) -> None:
        call = self._calls.get(event.call_id)
        if call is None:
            return
        robot = self._robots.get(call.robot_id) if call.robot_id else None
        freed = None
        if robot is not None and robot.status is RobotStatus.BUSY:
            robot.status = RobotStatus.IDLE
            self._robots.save(robot)
            freed = robot.id
        for nurse_id in sorted(call.nurse_tasks):
            nurse = self._nurses.get(nurse_id)
            if nurse is not None and nurse.open_tasks > 0:
                nurse.open_tasks -= 1
                self._nurses.save(nurse)
        if freed:
            self._bus.publish(RobotAvailable(robot_id=freed))
        call.nurse_tasks.clear()
        self._calls.save(call)
