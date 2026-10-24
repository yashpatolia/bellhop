from __future__ import annotations


class RecordingRobotGateway:
    """Default RobotGateway: records commands. The real Pi-backed gateway replaces it."""

    def __init__(self) -> None:
        self.commands: list[tuple[str, str, str]] = []

    def go_to(self, robot_id: str, room: str) -> None:
        self.commands.append(("go_to", robot_id, room))

    def set_led(self, robot_id: str, state: str) -> None:
        self.commands.append(("set_led", robot_id, state))
