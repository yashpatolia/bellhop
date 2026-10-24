"""Staff send a chosen robot to a room. The call and the visit then run as for any bell."""

from __future__ import annotations

from bellhop.domain import Call, RobotStatus
from bellhop.ports import CallRepository, RobotRepository
from bellhop.services.admin import Conflict
from bellhop.services.call_service import CallService
from bellhop.services.dispatcher import MIN_BATTERY


class ManualDispatch:
    def __init__(self, calls: CallRepository, robots: RobotRepository, call_service: CallService):
        self._calls = calls
        self._robots = robots
        self._call_service = call_service

    def send(self, robot_id: str, room: str) -> Call:
        """Ring the bell for `room` with `robot_id` as the robot to send.

        Raises LookupError for an unknown robot and Conflict (409) when the robot cannot go:
        it is busy, charging, faulty or low on charge, or the room already has an open call.
        """
        robot = self._robots.get(robot_id)
        if robot is None:
            raise LookupError(robot_id)
        if robot.status is not RobotStatus.IDLE:
            raise Conflict(f"{robot_id} is {robot.status.value}, not idle")
        if robot.battery < MIN_BATTERY:
            raise Conflict(f"{robot_id} has too little charge ({round(robot.battery * 100)}%)")
        if any(c.room == room for c in self._calls.list_open()):
            raise Conflict(f"room {room} already has an open call")
        call = self._call_service.raise_call(room, robot_id)
        sent = self._calls.get(call.id)
        if sent is None or sent.robot_id != robot_id:
            # The robot could not be commanded (the dispatcher fell back to a nurse).
            raise Conflict(f"{robot_id} could not be reached; a nurse was asked instead")
        return sent
