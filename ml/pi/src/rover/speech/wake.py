"""Asleep: listen for "Hey Bellhop". The mic and the gates run all the time, but a Deepgram Flux
stream is opened only when someone talks, and closed after WAKE_STREAM_IDLE_S without speech.
No model is loaded for it, so sleeping costs no extra memory."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable

import numpy as np

from rover import config
from rover.speech.flux import FluxStream
from rover.speech.gates import Gates
from rover.speech.mic import Mic
from rover.speech.visit import backfill, pair_blocks, wake_text

ZEROS = np.zeros(config.BLOCK_SAMPLES, dtype=np.int16)
MakeFlux = Callable[[Callable[[str, str], None]], FluxStream]


class WakeListener:
    """On its own thread: calls on_wake(the words after the name) once, then lets go of the mic."""

    def __init__(
        self,
        on_wake: Callable[[str], None],
        mic: Mic | None = None,
        gates: Gates | None = None,
        make_flux: MakeFlux | None = None,
    ) -> None:
        self.on_wake = on_wake
        self.mic = mic if mic is not None else Mic()
        self.gates = gates if gates is not None else Gates()
        self.make_flux = make_flux or (lambda on_event: FluxStream([config.ROBOT_NAME], on_event))
        self.flux: FluxStream | None = None
        self.events: queue.SimpleQueue[tuple[str, str]] = queue.SimpleQueue()
        self.outbox: list[np.ndarray] = []
        self.closed_run = 0  # blocks since the gate last passed one
        self.last_speech = 0.0
        self.retry_at = 0.0  # after a failed connect, the next speech before this opens nothing
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> WakeListener:
        self._thread = threading.Thread(target=self.run, daemon=True, name="wake")
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stop and wait for the mic to close: the chat or visit that follows opens its own."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def run(self) -> None:
        try:
            self.mic.start()
        except Exception:
            print("fallback: no microphone, so no wake word (robot.sh open still wakes the robot)")
            return
        print(f'wake: asleep; say "Hey {config.ROBOT_NAME}" to talk')
        try:
            while not self._stop.is_set():
                block = self.mic.read()
                now = time.monotonic()
                if block is not None:
                    self.hear(block, now)
                self.handle_events()
                if self.flux is not None and now - self.last_speech > config.WAKE_STREAM_IDLE_S:
                    self.close_flux()
        finally:
            self.close_flux()
            self.mic.stop()

    def hear(self, block: np.ndarray, now: float) -> None:
        if self.gates.check(block, now):
            if self.flux is None and now >= self.retry_at:
                self.open_flux(now)
            blocks = backfill(self.mic.preroll(), self.closed_run)  # the start of "Hey" too
            self.closed_run = 0
            self.last_speech = now
        else:
            blocks = [ZEROS]  # zeros keep the socket alive and the timing true
            self.closed_run += 1
        if self.flux is not None:
            pairs, self.outbox = pair_blocks(self.outbox + blocks)
            for pcm in pairs:
                self.flux.send(pcm)

    def open_flux(self, now: float) -> None:
        flux = self.make_flux(lambda event, text: self.events.put((event, text)))
        if flux.start():
            self.flux = flux
        else:  # FluxStream printed why
            print(f"fallback: no wake word for {config.WAKE_STREAM_IDLE_S:g} s, then Flux again")
            self.retry_at = now + config.WAKE_STREAM_IDLE_S

    def close_flux(self) -> None:
        if self.flux is not None:
            self.flux.close()
            self.flux, self.outbox = None, []

    def handle_events(self) -> None:
        while not self._stop.is_set():
            try:
                event, text = self.events.get_nowait()
            except queue.Empty:
                return
            if event == "Error":
                self.close_flux()  # that stream is dead; the next speech opens a new one
            elif event == "EndOfTurn" and (words := wake_text(text)) is not None:
                print(f"wake: heard {text!r}")
                self._stop.set()  # one wake: the mic is closed for whatever comes next
                self.on_wake(words)
