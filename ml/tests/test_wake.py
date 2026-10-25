import time

import numpy as np

from rover import config
from rover.speech.wake import WakeListener

LOUD = np.full(config.BLOCK_SAMPLES, 1000, np.int16)
QUIET = np.zeros(config.BLOCK_SAMPLES, np.int16)


class FakeMic:
    def __init__(self, blocks=()):
        self.blocks = list(blocks)
        self.recent = []
        self.stopped = False

    def start(self):
        pass

    def stop(self):
        self.stopped = True

    def read(self, timeout=1.0):
        if not self.blocks:
            time.sleep(0.01)
            return None
        self.recent = [*self.recent, self.blocks.pop(0)][-3:]
        return self.recent[-1]

    def preroll(self):
        return list(self.recent)


class FakeGates:
    def check(self, block, now):
        return bool(block.any())


class FakeFlux:
    def __init__(self, on_event, opened):
        self.on_event, self.sent, self.closed = on_event, [], False
        opened.append(self)

    def start(self):
        return True

    def send(self, pcm):
        self.sent.append(pcm)

    def close(self):
        self.closed = True


def make_listener(mic, heard, opened):
    return WakeListener(
        heard.append, mic=mic, gates=FakeGates(), make_flux=lambda on: FakeFlux(on, opened)
    )


def test_flux_opens_on_speech_with_the_pre_roll_and_wakes_only_on_the_name():
    mic, heard, opened = FakeMic([QUIET, LOUD]), [], []
    listener = make_listener(mic, heard, opened)
    listener.hear(mic.read(), 0.0)
    assert opened == []  # nobody talking: no Deepgram
    listener.hear(mic.read(), 0.1)
    (flux,) = opened
    assert flux.sent == [np.concatenate([QUIET, LOUD]).tobytes()]  # the block before speech too
    flux.on_event("EndOfTurn", "nice weather today")
    listener.handle_events()
    assert heard == []
    flux.on_event("EndOfTurn", "Hey Bellhop, what games do you have?")
    listener.handle_events()
    assert heard == ["what games do you have"]


def test_flux_closes_after_quiet_and_the_mic_is_released(monkeypatch):
    monkeypatch.setattr(config, "WAKE_STREAM_IDLE_S", 0.0)
    mic, opened = FakeMic([LOUD, QUIET]), []
    listener = make_listener(mic, [], opened).start()
    deadline = time.monotonic() + 5
    while mic.blocks and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)
    listener.stop()
    assert len(opened) == 1 and opened[0].closed and mic.stopped
