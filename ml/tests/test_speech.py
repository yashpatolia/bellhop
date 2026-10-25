import math
import sys
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from rover import config
from rover.speech import offline
from rover.speech.flux import FluxStream
from rover.speech.gates import FaceGate, Gates, block_dbfs
from rover.speech.mic import Mic
from rover.speech.tts import Voice, shift_pitch, tone_params


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


def test_the_usual_tone_keeps_the_natural_pitch_and_voice_pitch_moves_every_tone(monkeypatch):
    assert tone_params(config.DEFAULT_TONE, None)[1] == 0.0
    pitches = [tone_params(tone, None)[1] for tone in config.TONES]
    monkeypatch.setattr(config, "VOICE_PITCH", -0.03)
    lower = [tone_params(tone, None)[1] for tone in config.TONES]
    assert lower == pytest.approx([pitch - 0.03 for pitch in pitches])
    assert tone_params("excited", {"volume": "loud"})[1] == -0.03  # hard of hearing: no tone shift


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


def test_mic_discards_stale_blocks_when_the_consumer_falls_behind(monkeypatch):
    """A busy cloud reply must not make the next heard sentence several seconds old."""
    monkeypatch.setattr(config, "MIC_QUEUE_BLOCKS", 2)
    mic = Mic()
    for value in (1, 2, 3):
        mic._on_audio(np.full((config.BLOCK_SAMPLES, 1), value, dtype=np.int16), 0, None, None)

    assert [mic.read()[0], mic.read()[0]] == [2, 3]


def test_flux_send_never_blocks_the_microphone_loop():
    class SlowSocket:
        def __init__(self):
            self.started = threading.Event()
            self.release = threading.Event()

        def send_media(self, pcm):
            self.started.set()
            self.release.wait(1)

    flux = FluxStream([], lambda *_: None)
    socket = SlowSocket()
    flux._socket, flux._live = socket, True
    flux._sender = threading.Thread(target=flux._send_loop, daemon=True)
    flux._sender.start()

    flux.send(b"first")
    assert socket.started.wait(0.2)
    started = time.monotonic()
    flux.send(b"second")
    assert time.monotonic() - started < 0.05

    socket.release.set()
    flux._live = False
    flux._media.put_nowait(None)
    flux._sender.join(1)


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


class FakeStream:
    def __init__(self, polls_until_done):
        self.polls, self.aborted, self.closed = polls_until_done, False, False
        self.latency = 0.05

    @property
    def active(self):
        self.polls -= 1
        return self.polls >= 0

    def abort(self, ignore_errors=False):
        self.aborted = True

    def close(self, ignore_errors=False):
        self.closed = True


def quiet_voice(monkeypatch, polls_until_done):
    """A Voice with a fake Piper and a fake sounddevice: each sentence plays for some polls."""
    streams, log = [], []

    def play(audio, samplerate, device):
        streams.append(FakeStream(polls_until_done))
        log.append(("play", len(streams)))

    def synthesize(sentence, synthesis):
        log.append(("make", sentence, [stream.polls >= 0 for stream in streams]))
        return [SimpleNamespace(audio_float_array=np.zeros(160, np.float32))]

    fake_sd = SimpleNamespace(play=play, get_stream=lambda: streams[-1])
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    monkeypatch.setattr("rover.speech.tts.PLAY_POLL_S", 0.0)
    voice = Voice.__new__(Voice)  # no model to load or device to find
    voice.settings, voice._stream, voice._device, voice._device_rate = None, None, None, 16000
    voice._voice = SimpleNamespace(synthesize=synthesize, config=SimpleNamespace(sample_rate=16000))
    voice.on_play = lambda until: log.append(("muted", until is not None))
    return voice, streams, log


def test_the_mic_unmutes_by_itself_when_the_sound_is_due_to_end(monkeypatch):
    voice, streams, _ = quiet_voice(monkeypatch, polls_until_done=3)
    mic = Mic()
    voice.on_play = lambda until: mic.set_speaking(until is not None, until or 0.0)
    started = time.monotonic()
    voice.say("Let me take a look.", "calm")  # then Claude runs a tool: no next sentence yet
    ends = started + 160 / 16000 + streams[0].latency
    assert mic.muted(time.monotonic())
    assert not mic.muted(ends + config.ECHO_TAIL_S + 0.05)  # no wait() was called


def test_the_next_sentence_is_made_while_the_last_one_plays(monkeypatch):
    voice, streams, log = quiet_voice(monkeypatch, polls_until_done=3)
    voice.say("One.", "calm")
    voice.say("Two.", "calm")
    assert log[:3] == [("make", "One.", []), ("play", 1), ("muted", True)]
    assert log[3] == ("make", "Two.", [True])  # made while One. was still playing
    assert log[4:] == [("muted", False), ("play", 2), ("muted", True)]
    assert streams[0].closed and not streams[0].aborted
    voice.wait()
    assert log[-1] == ("muted", False) and streams[1].closed
    voice.wait()  # nothing playing: no second unmute
    assert log.count(("muted", False)) == 2


def test_a_speaker_that_stalls_is_cut_off_and_the_mic_comes_back(monkeypatch, capsys):
    voice, streams, log = quiet_voice(monkeypatch, polls_until_done=10**9)
    monkeypatch.setattr(config, "PLAYBACK_GRACE_S", 0.0)
    voice.say("Hello.", "calm")
    started = time.monotonic()
    voice.wait()
    assert streams[0].aborted and log[-1] == ("muted", False) and time.monotonic() - started < 1
    assert "fallback: the speaker stopped playing" in capsys.readouterr().out


class SlowSocket:
    def __init__(self):
        self.sent, self.closed_stream, self.release = [], False, threading.Event()

    def send_media(self, pcm):
        self.release.wait(5)  # a stalled network
        self.sent.append(pcm)

    def send_close_stream(self):
        self.closed_stream = True


def live_flux(socket):
    events = []
    flux = FluxStream([], lambda event, text: events.append((event, text)))
    flux._socket, flux._live = socket, True
    flux._sender = threading.Thread(target=flux._send_loop, daemon=True)
    flux._sender.start()
    return flux, events


def test_flux_sends_from_its_own_thread_and_flushes_on_close():
    socket = SlowSocket()
    flux, events = live_flux(socket)
    started = time.monotonic()
    for _ in range(3):
        flux.send(b"\0" * 2048)
    assert time.monotonic() - started < 0.5  # the mic loop never waits for the network
    socket.release.set()
    flux.close()
    assert len(socket.sent) == 3 and socket.closed_stream and events == []


def test_flux_that_falls_a_full_queue_behind_is_an_error_once(monkeypatch):
    """A dead or too slow network: Moonshine takes the turns, not a Flux missing their words."""
    monkeypatch.setattr(config, "FLUX_SEND_QUEUE_BLOCKS", 2)
    monkeypatch.setattr(config, "FLUX_CLOSE_S", 0.05)
    socket = SlowSocket()
    flux, events = live_flux(socket)
    for pcm in (b"a", b"b", b"c"):
        flux.send(pcm)
        time.sleep(0.02)  # "a" is in send_media; "b" and "c" fill the queue
    assert events == []
    started = time.monotonic()
    flux.send(b"d")
    flux.send(b"e")
    assert time.monotonic() - started < 0.05  # the mic loop never waits
    assert events == [("Error", "Flux send fell 2 messages behind")]
    flux.close()  # already failed: no goodbye on the socket
    assert not socket.closed_stream
    socket.release.set()


def test_closing_flux_on_a_stuck_network_does_not_hang_the_visit(monkeypatch):
    monkeypatch.setattr(config, "FLUX_CLOSE_S", 0.05)
    socket = SlowSocket()
    flux, events = live_flux(socket)
    flux.send(b"\0" * 2048)
    time.sleep(0.05)  # the sender is now inside send_media
    started = time.monotonic()
    flux.close()
    assert time.monotonic() - started < 1 and not socket.closed_stream and events == []
    socket.release.set()


def test_a_silent_stream_keeps_the_speaker_awake(monkeypatch, capsys):
    opened = []

    class FakeOutputStream:
        def __init__(self, **kwargs):
            opened.append(kwargs)

        def start(self):
            opened.append("started")

        def stop(self, ignore_errors=True):
            pass

        def close(self, ignore_errors=True):
            opened.append("closed")

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(OutputStream=FakeOutputStream))
    voice = Voice.__new__(Voice)
    voice._device, voice._device_rate = 3, 48000
    assert voice._keep_awake() is not None
    settings, started, probe, probe_closed = opened
    assert settings["device"] == 3 and settings["samplerate"] == 48000 and started == "started"
    assert probe["device"] == 3 and probe_closed == "closed"  # a sentence can still open it
    block = np.ones((8, 1), np.float32)
    settings["callback"](block, 8, None, None)
    assert not block.any()  # silence

    def broken(**kwargs):
        raise OSError("device busy")

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(OutputStream=broken))
    assert voice._keep_awake() is None
    assert "fallback: could not keep the speaker awake" in capsys.readouterr().out

    class OneAtATime(FakeOutputStream):  # raw ALSA: a second open is refused
        def __init__(self, **kwargs):
            if opened and opened[-1] == "started":
                raise OSError("Device unavailable")
            super().__init__(**kwargs)

    opened.clear()
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(OutputStream=OneAtATime))
    assert voice._keep_awake() is None and opened[-1] == "closed"  # sentences get the device
    assert "plays one sound at a time" in capsys.readouterr().out
