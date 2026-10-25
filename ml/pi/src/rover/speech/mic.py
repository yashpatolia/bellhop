"""USB microphone: 16 kHz mono int16 blocks in a queue, a short pre-roll, half-duplex muting."""

import math
import queue
import time
from collections import deque

import numpy as np

from rover import config


def find_device(name: str, kind: str) -> int | None:
    """Index of the first `kind` ("input"/"output") device whose name contains `name`.

    None means the system default device; on Pi OS Lite that is usually HDMI (no mic), so set
    MIC_NAME and SPEAKER_NAME there.
    """
    if not name:
        return None
    import sounddevice as sd  # lazy: needs the PortAudio system library

    for index, device in enumerate(sd.query_devices()):
        if name.lower() in device["name"].lower() and device[f"max_{kind}_channels"] > 0:
            return index
    print(f"audio: no {kind} device matching '{name}', using the default")
    return None


class Mic:
    def __init__(self, device_name: str = config.MIC_NAME) -> None:
        self.device_name = device_name
        self._blocks: queue.Queue[np.ndarray] = queue.Queue()
        preroll_blocks = max(1, round(config.PREROLL_S * config.SAMPLE_RATE / config.BLOCK_SAMPLES))
        self._preroll: deque[np.ndarray] = deque(maxlen=preroll_blocks)
        self._stream = None  # sounddevice.InputStream once started
        self._muted_until = -math.inf  # when the robot's sound ends (inf: until told it stopped)

    def start(self) -> None:
        try:
            import sounddevice as sd  # lazy: needs the PortAudio system library

            self._stream = sd.InputStream(
                samplerate=config.SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=config.BLOCK_SAMPLES,
                device=find_device(self.device_name, "input"),
                callback=self._on_audio,
            )
            self._stream.start()
        except Exception as exc:
            print(
                f"mic: cannot open '{self.device_name or 'default'}' at {config.SAMPLE_RATE} Hz: "
                f"{exc} (on the Pi set MIC_NAME to part of the USB mic's name from "
                "`uv run python -m sounddevice`; an empty MIC_NAME uses the default device)"
            )
            raise

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _on_audio(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            print(f"mic: {status}")
        block = indata[:, 0].copy()
        # zeroed at capture time so blocks read late can never carry the robot's own voice
        if self.muted(time.monotonic()):
            block[:] = 0
        self._blocks.put_nowait(block)

    def read(self, timeout: float = 1.0) -> np.ndarray | None:
        """Next int16 block of config.BLOCK_SAMPLES, or None if the mic sent nothing in time."""
        try:
            block = self._blocks.get(timeout=timeout)
        except queue.Empty:
            print(f"mic: no audio for {timeout} s")
            return None
        self._preroll.append(block)
        return block

    def preroll(self) -> list[np.ndarray]:
        """The last config.PREROLL_S of blocks returned by read(), the latest one included."""
        return list(self._preroll)

    def set_speaking(self, speaking: bool, until: float = math.inf) -> None:
        """Speaking: muted until `until`, when its sound ends. Not speaking: unmuted from now."""
        if speaking:
            self._muted_until = until
        else:
            self._muted_until = min(self._muted_until, time.monotonic())

    def muted(self, now: float) -> bool:
        """True while the robot talks and for config.ECHO_TAIL_S after (now = time.monotonic())."""
        return now < self._muted_until + config.ECHO_TAIL_S
