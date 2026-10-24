"""Listen gates: Silero speech + loudness over the room's noise floor, and the vision face gate."""

import json
import math
import socket
import statistics
import threading
import time
from collections import deque
from collections.abc import Callable

import numpy as np
from pysilero_vad import SileroVoiceActivityDetector

from rover import config

SILENCE_DBFS = -100.0  # what block_dbfs returns for digital silence


def block_dbfs(block: np.ndarray) -> float:
    rms = math.sqrt(float(np.mean(block.astype(np.float64) ** 2)))
    if rms <= 0:
        return SILENCE_DBFS
    return max(20 * math.log10(rms / 32768), SILENCE_DBFS)


class Gates:
    """A block passes when Silero hears speech AND it is loud enough over the noise floor."""

    def __init__(self, vad: Callable[[bytes], float] | None = None) -> None:
        if vad is None:
            if SileroVoiceActivityDetector.chunk_samples() != config.BLOCK_SAMPLES:
                raise ValueError(
                    f"Silero needs {SileroVoiceActivityDetector.chunk_samples()}-sample blocks, "
                    f"config.BLOCK_SAMPLES is {config.BLOCK_SAMPLES}"
                )
            vad = SileroVoiceActivityDetector()
        self._vad = vad
        self._quiet: deque[tuple[float, float]] = deque()  # (time, dBFS) of non-speech blocks
        self._attention_until = -math.inf
        self.floor_db: float = config.FLOOR_START_DB

    def check(self, block: np.ndarray, now: float) -> bool:
        speech = self._vad(block.tobytes()) >= config.SILERO_THRESHOLD
        db = block_dbfs(block)
        if not speech and db > SILENCE_DBFS:  # muted (zeroed) blocks say nothing about the room
            self._update_floor(db, now)
        margin = config.LOUDNESS_MARGIN_DB
        if now < self._attention_until:
            margin -= config.ATTENTION_RELIEF_DB
        return speech and db >= self.floor_db + margin

    def open_attention(self, now: float) -> None:
        """Lower the loudness margin for a while, e.g. right after the robot asked something."""
        self._attention_until = now + config.ATTENTION_WINDOW_S

    def _update_floor(self, db: float, now: float) -> None:
        self._quiet.append((now, db))
        while self._quiet and self._quiet[0][0] < now - config.FLOOR_WINDOW_S:
            self._quiet.popleft()
        if len(self._quiet) >= config.FLOOR_MIN_BLOCKS:
            self.floor_db = statistics.median(db for _, db in self._quiet)


class VisionListener:
    """Keeps the latest vision UDP message; times are time.monotonic()."""

    def __init__(self) -> None:
        self._latest: tuple[dict, float] | None = None

    def start(self) -> None:
        address = (config.VISION_HOST, config.VISION_PORTS[0])
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(address)
        except OSError as exc:
            print(f"vision listener: cannot bind {address[0]}:{address[1]}: {exc}")
            sock.close()
            return
        threading.Thread(target=self._receive, args=(sock,), daemon=True).start()

    def _receive(self, sock: socket.socket) -> None:
        while True:
            try:
                data, _ = sock.recvfrom(65535)
            except OSError as exc:
                print(f"vision listener: stopped: {exc}")
                return
            try:
                message = json.loads(data)
            except ValueError as exc:
                print(f"vision listener: bad message: {exc}")
                continue
            if not isinstance(message, dict):
                print(f"vision listener: message is not an object: {message!r:.80}")
                continue
            self._latest = (message, time.monotonic())

    def latest(self) -> dict | None:
        latest = self._latest
        return latest[0] if latest else None

    def age(self, now: float) -> float:
        latest = self._latest
        return now - latest[1] if latest else math.inf


class FaceGate:
    """Turns count only while the resident faces the robot; passes when vision is off or stale."""

    def __init__(self, listener: VisionListener | None, disabled: bool = False) -> None:
        self.listener = listener
        self.disabled = disabled
        self._warned = False
        self._facing_since: float | None = None

    def _fresh(self, now: float) -> dict | None:
        if self.disabled or self.listener is None:
            return None
        if self.listener.age(now) > config.VISION_STALE_S:
            return None
        return self.listener.latest()

    def _facing(self, now: float) -> bool | None:
        """True/False from a fresh message, None when there is no vision."""
        message = self._fresh(now)
        if message is None:
            return None
        face = message.get("face")
        return isinstance(face, dict) and face.get("facing") is True

    def ok(self, now: float) -> bool:
        facing = self._facing(now)
        if facing is None:
            if not self._warned:
                print("fallback: no vision")
                self._warned = True
            return True
        self._warned = False
        return facing

    def facing_for(self, now: float) -> float:
        """Seconds the face has been facing, as seen by successive calls (0 without vision)."""
        if not self._facing(now):
            self._facing_since = None
            return 0.0
        if self._facing_since is None:
            self._facing_since = now
        return now - self._facing_since

    def reset_facing(self) -> None:
        self._facing_since = None

    def marker_distance(self, room: str) -> float | None:
        message = self._fresh(time.monotonic())
        if message is None:
            return None
        distances = [
            marker.get("distance_m")
            for marker in message.get("markers") or []
            if isinstance(marker, dict) and marker.get("room") == room
        ]
        valid = [d for d in distances if isinstance(d, int | float) and math.isfinite(d) and d > 0]
        return float(min(valid)) if valid else None
