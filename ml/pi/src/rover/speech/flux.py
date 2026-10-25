"""Deepgram Flux (listen v2) streaming STT with turn events, one connection per visit."""

import contextlib
import os
import queue
import threading
from collections.abc import Callable

from deepgram import DeepgramClient

from rover import config

TURN_EVENTS = {"StartOfTurn", "EagerEndOfTurn", "TurnResumed", "EndOfTurn"}


class FluxStream:
    """Calls on_event(event, transcript) from a background thread.

    Events: "StartOfTurn", "EagerEndOfTurn", "TurnResumed", "EndOfTurn", and "Error" (once,
    with the reason as the text; the stream is dead after it). Audio goes out from its own
    thread, so a slow network never stalls the mic loop. A short stall only delays it; a full
    send queue (FLUX_SEND_QUEUE_BLOCKS, about 4 s behind) is an Error, so Moonshine takes the
    turns instead of Flux answering stale or broken speech.
    """

    def __init__(self, keyterms: list[str], on_event: Callable[[str, str], None]) -> None:
        self.keyterms = [term for term in keyterms if term]
        self.on_event = on_event
        self._stack = contextlib.ExitStack()
        self._socket = None
        self._live = False
        self._lock = threading.Lock()  # one Error, even when sending and listening both fail
        self._media: queue.Queue[bytes | None] = queue.Queue(maxsize=config.FLUX_SEND_QUEUE_BLOCKS)
        self._sender: threading.Thread | None = None

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
        threading.Thread(target=self._listen, daemon=True, name="flux-listen").start()
        self._sender = threading.Thread(target=self._send_loop, daemon=True, name="flux-send")
        self._sender.start()
        return True

    def send(self, pcm: bytes) -> None:
        """Queue int16 16 kHz mono audio; send zeros for gated blocks to keep the socket alive."""
        if not self._live:
            return
        try:
            self._media.put_nowait(pcm)
        except queue.Full:  # a dead or too slow network: dropping audio would garble the turn
            self._fail(f"Flux send fell {self._media.maxsize} messages behind")

    def close(self) -> None:
        with self._lock:
            was_live, self._live = self._live, False
        self._stop_sender()  # what is queued goes out first
        if self._sender is not None:
            self._sender.join(config.FLUX_CLOSE_S)
            if self._sender.is_alive():
                # stuck in a send that holds the websocket's lock, which closing needs too
                print("flux: the network is stuck; closing the stream in the background")
                threading.Thread(target=self._close, args=(False,), daemon=True).start()
                return
        self._close(was_live)

    def _close(self, goodbye: bool) -> None:
        try:
            if goodbye:
                self._socket.send_close_stream()
            self._stack.close()
        except Exception as exc:
            print(f"flux: close failed: {exc}")

    def _stop_sender(self) -> None:
        """None ends the sender after what is queued; a full queue (a stuck network) gives up its
        oldest block to make room."""
        while True:
            try:
                self._media.put_nowait(None)
                return
            except queue.Full:
                with contextlib.suppress(queue.Empty):
                    self._media.get_nowait()

    def _send_loop(self) -> None:
        while (pcm := self._media.get()) is not None:
            try:
                self._socket.send_media(pcm)
            except Exception as exc:
                self._fail(f"Flux send failed: {exc}")
                return

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
        with self._lock:
            if not self._live:  # already failed or closed on purpose
                return
            self._live = False
        self._stop_sender()
        print(f"flux: {reason}")
        self.on_event("Error", reason)
