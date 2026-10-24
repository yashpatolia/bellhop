"""Latest marker frame received from ``rover.vision`` over local UDP."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

from rover import config


class VisionReceiver:
    """Keep only the latest complete vision message; stale vision is never used for motion."""

    def __init__(
        self,
        port: int = config.DRIVE_VISION_PORT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._port, self._clock = port, clock
        self._lock = threading.Lock()
        self._message: dict[str, Any] | None = None
        self._received_at: float | None = None
        self._stop = threading.Event()
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((config.VISION_HOST, self._port))
        sock.settimeout(0.25)
        self._socket = sock
        self._thread = threading.Thread(target=self._listen, name="drive-vision", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=0.5)

    def ingest(self, payload: bytes | str | dict[str, Any]) -> bool:
        """Store a valid frame. Public for deterministic tests; malformed input is ignored."""
        try:
            value = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        if not isinstance(value, dict) or not isinstance(value.get("markers"), list):
            return False
        with self._lock:
            self._message, self._received_at = value, self._clock()
        return True

    def markers(self, max_age_s: float = config.VISION_WATCHDOG_S) -> list[dict[str, Any]] | None:
        with self._lock:
            if self._message is None or self._received_at is None:
                return None
            if self._clock() - self._received_at > max_age_s:
                return None
            return list(self._message["markers"])

    def _listen(self) -> None:
        assert self._socket is not None
        while not self._stop.is_set():
            try:
                payload, _ = self._socket.recvfrom(65535)
            except TimeoutError:
                continue
            except OSError:
                return
            self.ingest(payload)
