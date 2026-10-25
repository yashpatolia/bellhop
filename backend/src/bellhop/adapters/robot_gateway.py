from __future__ import annotations

from bellhop.adapters.notifiers import BoundedLog


class RecordingRobotGateway:
    """Default RobotGateway: records commands. The real Pi-backed gateway replaces it."""

    def __init__(self) -> None:
        self.commands: BoundedLog = BoundedLog()  # last 1000 (kind, robot_id, arg)

    def go_to(self, robot_id: str, room: str) -> None:
        self.commands.append(("go_to", robot_id, room))

    def follow_marker(self, robot_id: str, marker: str) -> None:
        self.commands.append(("follow_marker", robot_id, marker))

    def set_led(self, robot_id: str, state: str) -> None:
        self.commands.append(("set_led", robot_id, state))

    def stop(self, robot_id: str) -> None:
        self.commands.append(("stop", robot_id, ""))
