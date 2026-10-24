"""Deepgram Flux (listen v2) streaming STT with turn events, one connection per visit."""

import contextlib
import os
import threading
from collections.abc import Callable

from deepgram import DeepgramClient

from rover import config

TURN_EVENTS = {"StartOfTurn", "EagerEndOfTurn", "TurnResumed", "EndOfTurn"}


class FluxStream:
    """Calls on_event(event, transcript) from a background thread.

    Events: "StartOfTurn", "EagerEndOfTurn", "TurnResumed", "EndOfTurn", and "Error" (once,
    with the reason as the text; the stream is dead after it).
    """

    def __init__(self, keyterms: list[str], on_event: Callable[[str, str], None]) -> None:
        self.keyterms = [term for term in keyterms if term]
        self.on_event = on_event
        self._stack = contextlib.ExitStack()
        self._socket = None
        self._live = False

    def start(self) -> bool:
        api_key = os.environ.get("DEEPGRAM_API_KEY", "")
        if not api_key:
            print("fallback: no DEEPGRAM_API_KEY")
            return False
        try:
            connection = DeepgramClient(api_key=api_key).listen.v2.connect(
                model=config.FLUX_MODEL,
                encoding="linear16",
                sample_rate=config.SAMPLE_RATE,
                eot_threshold=config.EOT_THRESHOLD,
                eager_eot_threshold=config.EAGER_EOT_THRESHOLD,
                eot_timeout_ms=config.EOT_TIMEOUT_MS,
                keyterm=self.keyterms or None,
            )
            self._socket = self._stack.enter_context(connection)
        except Exception as exc:
            print(f"fallback: Flux connect failed: {exc}")
            return False
        self._live = True
        threading.Thread(target=self._listen, daemon=True).start()
        return True

    def send(self, pcm: bytes) -> None:
        """Send int16 16 kHz mono audio; send zeros for gated blocks to keep the socket alive."""
        if not self._live:
            return
        try:
            self._socket.send_media(pcm)
        except Exception as exc:
            self._fail(f"Flux send failed: {exc}")

    def close(self) -> None:
        was_live, self._live = self._live, False
        try:
            if was_live:
                self._socket.send_close_stream()
            self._stack.close()
        except Exception as exc:
            print(f"flux: close failed: {exc}")

    def _listen(self) -> None:
        try:
            for message in self._socket:
                kind = getattr(message, "type", None)
                if kind == "TurnInfo" and message.event in TURN_EVENTS and self._live:
                    self.on_event(message.event, message.transcript)
                elif kind == "Error":
                    self._fail(f"Flux error {message.code}: {message.description}")
                elif kind == "Warning":
                    print(f"flux: warning {message.code}: {message.description}")
        except Exception as exc:
            self._fail(f"Flux connection lost: {exc}")
            return
        self._fail("Flux connection closed by the server")

    def _fail(self, reason: str) -> None:
        if not self._live:  # already failed or closed on purpose
            return
        self._live = False
        print(f"flux: {reason}")
        self.on_event("Error", reason)
