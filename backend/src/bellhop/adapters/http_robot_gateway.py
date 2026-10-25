"""RobotGateway that commands the robot's HTTP server (the Pi). Failures raise."""

from __future__ import annotations

import httpx


class HttpRobotGateway:
    """POST {base}/go_to {"room"}, /led {"state"} and /stop; non-2xx or transport errors raise.

    The robot serves one robot per base URL, so `robot_id` is not sent. The caller
    (GuardedRobotGateway, Dispatcher) turns a raise into a nurse fallback.
    """

    def __init__(
        self, base_url: str, timeout: float = 5.0, client: httpx.Client | None = None
    ) -> None:
        self._base = base_url.rstrip("/")
        # The Pi is addressed on the tailnet. Never route its private address through a
        # developer-machine HTTP proxy, which can turn a reachable rover into a false 503.
        self._client = client or httpx.Client(timeout=timeout, trust_env=False)

    def go_to(self, robot_id: str, room: str) -> None:
        self._post("/go_to", {"room": room})

    def follow_marker(self, robot_id: str, marker: str) -> None:
        self._post("/follow_marker", {"room": marker})

    def set_led(self, robot_id: str, state: str) -> None:
        self._post("/led", {"state": state})

    def stop(self, robot_id: str) -> None:
        self._post("/stop", {})

    def _post(self, path: str, body: dict[str, str]) -> None:
        self._client.post(self._base + path, json=body).raise_for_status()
