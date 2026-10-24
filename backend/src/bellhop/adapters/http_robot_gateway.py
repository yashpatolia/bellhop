"""RobotGateway that commands the robot's HTTP server (the Pi). Failures raise."""

from __future__ import annotations

import httpx


class HttpRobotGateway:
    """POST {base}/go_to {"room"}, /led {"state"} and /stop; non-2xx or transport errors raise.

    The robot serves one robot per base URL, so `robot_id` is not sent. The caller
    (GuardedRobotGateway, Dispatcher) turns a raise into a nurse fallback.
    """

    def __init__(
        self, base_url: str, timeout: float = 2.0, client: httpx.Client | None = None
    ) -> None:
        self._base = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)

    def go_to(self, robot_id: str, room: str) -> None:
        self._post("/go_to", {"room": room})

    def set_led(self, robot_id: str, state: str) -> None:
        self._post("/led", {"state": state})

    def stop(self, robot_id: str) -> None:
        self._post("/stop", {})

    def _post(self, path: str, body: dict[str, str]) -> None:
        self._client.post(self._base + path, json=body).raise_for_status()
