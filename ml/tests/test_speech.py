import math
import time
from types import SimpleNamespace

import numpy as np
import pytest

from rover import config
from rover.speech import offline
from rover.speech.flux import FluxStream
from rover.speech.gates import FaceGate, Gates, block_dbfs
from rover.speech.mic import Mic
from rover.speech.tts import shift_pitch, tone_params


def tone_block(dbfs: float) -> np.ndarray:
    """A sine block whose RMS level is `dbfs`."""
    amplitude = 32768 * 10 ** (dbfs / 20) * math.sqrt(2)
    t = np.arange(config.BLOCK_SAMPLES)
    return (amplitude * np.sin(2 * np.pi * t / 32)).astype(np.int16)


class FakeVad:
    def __init__(self, prob: float) -> None:
        self.prob = prob

    def __call__(self, audio: bytes) -> float:
        assert len(audio) == config.BLOCK_SAMPLES * 2
        return self.prob


def warm_floor(gates: Gates, vad: FakeVad, dbfs: float, start: float = 0.0) -> float:
    """Feed enough non-speech blocks to set the floor; returns the time after them."""
    vad.prob = 0.0
    now = start
    for _ in range(config.FLOOR_MIN_BLOCKS):
        gates.check(tone_block(dbfs), now)
        now += 0.032
    return now


def test_block_dbfs_silence_and_full_scale():
    assert block_dbfs(np.zeros(config.BLOCK_SAMPLES, np.int16)) == -100.0
    assert block_dbfs(np.full(config.BLOCK_SAMPLES, -32768, np.int16)) == pytest.approx(0.0)
    assert block_dbfs(tone_block(-30)) == pytest.approx(-30, abs=0.2)


def test_floor_starts_at_default_and_follows_quiet_blocks():
    vad = FakeVad(0.0)
    gates = Gates(vad)
    assert gates.floor_db == config.FLOOR_START_DB
    warm_floor(gates, vad, -50)
    assert gates.floor_db == pytest.approx(-50, abs=0.2)


def test_speech_must_clear_floor_plus_margin():
    vad = FakeVad(0.0)
    gates = Gates(vad)
    now = warm_floor(gates, vad, -50)
    vad.prob = 0.9
    assert gates.check(tone_block(-50 + config.LOUDNESS_MARGIN_DB + 1), now)
    assert not gates.check(tone_block(-50 + config.LOUDNESS_MARGIN_DB - 2), now)
    vad.prob = 0.1  # loud but not speech
    assert not gates.check(tone_block(-10), now)


def test_attention_relief_lowers_the_margin_for_a_while():
    vad = FakeVad(0.0)
    gates = Gates(vad)
    now = warm_floor(gates, vad, -50)
    vad.prob = 0.9
    level = -50 + config.LOUDNESS_MARGIN_DB - config.ATTENTION_RELIEF_DB + 1
    assert not gates.check(tone_block(level), now)
    gates.open_attention(now)
    assert gates.check(tone_block(level), now + 1)
    assert not gates.check(tone_block(level), now + config.ATTENTION_WINDOW_S + 1)


def test_floor_forgets_old_blocks_and_ignores_speech_and_zeros():
    vad = FakeVad(0.0)
    gates = Gates(vad)
    now = warm_floor(gates, vad, -50)
    vad.prob = 0.9
    gates.check(tone_block(-10), now)  # speech never moves the floor
    vad.prob = 0.0
    gates.check(np.zeros(config.BLOCK_SAMPLES, np.int16), now)  # muted blocks neither
    assert gates.floor_db == pytest.approx(-50, abs=0.2)
    warm_floor(gates, vad, -40, start=now + config.FLOOR_WINDOW_S + 1)
    assert gates.floor_db == pytest.approx(-40, abs=0.2)


class FakeListener:
    def __init__(self, message: dict | None, age: float) -> None:
        self.message = message
        self._age = age

    def latest(self) -> dict | None:
        return self.message

    def age(self, now: float) -> float:
        return self._age


FACING = {"face": {"box": [0, 0, 50, 50], "score": 0.95, "facing": True, "width": 50.0}}
NOT_FACING = {"face": {"box": [0, 0, 50, 50], "score": 0.95, "facing": False, "width": 50.0}}


def test_face_gate_fresh_message(capsys):
    assert FaceGate(FakeListener(FACING, 0.1)).ok(0)
    assert not FaceGate(FakeListener(NOT_FACING, 0.1)).ok(0)
    assert not FaceGate(FakeListener({"face": None}, 0.1)).ok(0)
    assert "fallback" not in capsys.readouterr().out


def test_face_gate_passes_without_vision_and_says_so_once(capsys):
    stale = FaceGate(FakeListener(NOT_FACING, config.VISION_STALE_S + 1))
    assert stale.ok(0) and stale.ok(1)
    assert capsys.readouterr().out.count("fallback: no vision") == 1
    assert FaceGate(FakeListener(NOT_FACING, 0.1), disabled=True).ok(0)
    assert FaceGate(None).ok(0)


def test_facing_for_counts_continuous_facing():
    listener = FakeListener(FACING, 0.1)
    gate = FaceGate(listener)
    assert gate.facing_for(10.0) == 0.0
    assert gate.facing_for(11.5) == pytest.approx(1.5)
    listener.message = NOT_FACING
    assert gate.facing_for(12.0) == 0.0
    listener.message = FACING
    assert gate.facing_for(13.0) == 0.0
    assert FaceGate(listener, disabled=True).facing_for(13.0) == 0.0


def test_marker_distance_for_room():
    message = {
        "markers": [
            {"id": 201, "room": "12", "distance_m": 1.4},
            {"id": 202, "room": "14", "distance_m": 0.8},
            {"id": 201, "room": "12", "distance_m": float("nan")},
        ]
    }
    gate = FaceGate(FakeListener(message, 0.1))
    assert gate.marker_distance("12") == pytest.approx(1.4)
    assert gate.marker_distance("14") == pytest.approx(0.8)
    assert gate.marker_distance("99") is None
    stale = FaceGate(FakeListener(message, config.VISION_STALE_S + 1))
    assert stale.marker_distance("12") is None


def test_tone_params_rows_and_clamps():
    assert tone_params("calm", None) == config.TONES["calm"]
    assert tone_params("no-such-tag", None) == config.TONES[config.DEFAULT_TONE]
    for tone in config.TONES:
        length, pitch, _ = tone_params(tone, None)
        assert length >= config.MIN_LENGTH_SCALE
        assert abs(pitch) <= config.MAX_PITCH


def test_tone_params_speech_settings():
    calm = tone_params("excited", {"tone": "calm"})
    assert calm == config.TONES["calm"]
    hard = {"rate": "slow", "volume": "loud", "captions": True, "tone": "normal"}
    length, pitch, noise = tone_params("cheerful", hard)
    cheerful = config.TONES["cheerful"]
    assert length == pytest.approx(cheerful[0] + config.SLOW_LENGTH_BONUS)
    assert pitch == 0.0
    assert noise == cheerful[2]
    assert tone_params("excited", {"volume": "loud"})[1] == 0.0


def test_shift_pitch_keeps_length_and_raises_frequency():
    rate, freq, pitch = 22050, 440.0, 0.06
    audio = np.sin(2 * np.pi * freq * np.arange(rate) / rate).astype(np.float32)
    shifted = shift_pitch(audio, pitch)
    assert abs(len(shifted) - len(audio) / (1 + pitch)) <= 1
    assert shifted.dtype == np.float32
    spectrum = np.abs(np.fft.rfft(shifted))
    peak_hz = np.argmax(spectrum) * rate / len(shifted)
    assert peak_hz == pytest.approx(freq * (1 + pitch), rel=0.01)
    assert shift_pitch(audio, 0.0) is audio


def test_flux_maps_turn_events_and_reports_one_error():
    events = []
    flux = FluxStream(["Bellhop"], lambda event, text: events.append((event, text)))
    flux._socket = [
        SimpleNamespace(type="Connected"),
        SimpleNamespace(type="TurnInfo", event="Update", transcript="I have"),
        SimpleNamespace(type="TurnInfo", event="EndOfTurn", transcript="I have fallen"),
        SimpleNamespace(type="Error", code="BAD", description="oops"),
    ]
    flux._live = True
    flux._listen()  # the server closing after the error must not add a second Error
    assert events == [("EndOfTurn", "I have fallen"), ("Error", "Flux error BAD: oops")]
    flux.send(b"\0" * 1024)  # dead stream: ignored, no exception


def test_mic_half_duplex_mute_and_echo_tail():
    mic = Mic()  # no stream is opened until start()
    assert not mic.muted(time.monotonic())
    mic.set_speaking(True)
    assert mic.muted(time.monotonic() + 100)
    mic.set_speaking(False)
    stopped = time.monotonic()
    assert mic.muted(stopped)
    assert not mic.muted(stopped + config.ECHO_TAIL_S + 0.05)
    mic.set_speaking(False)  # a repeated "not speaking" must not restart the tail
    assert not mic.muted(stopped + config.ECHO_TAIL_S + 0.05)


def test_moonshine_requires_a_complete_cached_model(tmp_path):
    group = {
        "base_url": "https://download.moonshine.ai/models/en/small-streaming",
        "files": [{"name": "encoder.onnx"}, {"name": "decoder.onnx"}],
    }
    root = tmp_path / "download.moonshine.ai" / "models" / "en" / "small-streaming"
    root.mkdir(parents=True)
    (root / "encoder.onnx").write_bytes(b"model")

    with pytest.raises(RuntimeError, match="decoder.onnx"):
        offline.cached_model_path(tmp_path, group, "small-streaming")

    (root / "decoder.onnx").write_bytes(b"model")
    path, arch = offline.cached_model_path(tmp_path, group, "small-streaming")
    assert path == str(root) and arch == "small-streaming"
