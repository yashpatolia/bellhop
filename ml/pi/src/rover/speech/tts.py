"""Piper voice (Poppy): one sentence at a time, tone tags set speed, pitch and expressiveness."""

import time
from collections.abc import Callable

import numpy as np
from piper import PiperVoice, SynthesisConfig

from rover import config
from rover.speech.mic import find_device

PLAY_POLL_S = 0.02  # how often a playing sentence is checked for its end


def effective_tone(tone: str, settings: dict | None) -> str:
    """The tag the voice and the eyes use: speech-settings "always calm" wins over Claude's tag."""
    if (settings or {}).get("tone") == "calm":
        return "calm"
    return tone if tone in config.TONES else config.DEFAULT_TONE


def tone_params(tone: str, settings: dict | None) -> tuple[float, float, float]:
    """(length_scale, pitch, noise_scale) for a tone tag, adjusted by backend speech-settings.
    VOICE_PITCH moves every tone alike, on top of the tone's own (clamped) shift."""
    length, pitch, noise = config.TONES[effective_tone(tone, settings)]
    settings = settings or {}
    slow = settings.get("rate") == "slow"
    if slow:
        length += config.SLOW_LENGTH_BONUS
    if slow or settings.get("volume") == "loud" or settings.get("captions"):
        pitch = 0.0  # hard of hearing: keep the natural pitch
    length = max(length, config.MIN_LENGTH_SCALE)
    pitch = min(max(pitch, -config.MAX_PITCH), config.MAX_PITCH) + config.VOICE_PITCH
    return length, pitch, noise


def resample(audio: np.ndarray, samples: int) -> np.ndarray:
    positions = np.linspace(0, len(audio) - 1, samples)
    return np.interp(positions, np.arange(len(audio)), audio).astype(audio.dtype)


def shift_pitch(audio: np.ndarray, pitch: float) -> np.ndarray:
    """Squeeze to len/(1+pitch) samples: at the same rate it plays (1+pitch) faster and higher.

    Synthesize with length_scale*(1+pitch) first so the duration comes back to normal.
    """
    if pitch == 0 or len(audio) < 2:
        return audio
    return resample(audio, round(len(audio) / (1 + pitch)))


class Voice:
    def __init__(
        self, settings: dict | None = None, device_name: str = config.SPEAKER_NAME
    ) -> None:
        self.settings = settings
        # a visit mutes its mic: on_play(when the sound ends) as it starts, on_play(None) at the end
        self.on_play: Callable[[float | None], None] = lambda until: None
        self._stream = None  # the sentence playing now, until wait() sees it end
        self._ends_by = 0.0
        self._voice: PiperVoice | None = None
        self._device: int | None = None
        self._device_rate = 0
        try:
            self._voice = PiperVoice.load(str(config.PIPER_VOICE))
        except Exception as exc:
            print(f"tts: cannot load {config.PIPER_VOICE} ({exc}); printing lines only")
            return
        try:
            import sounddevice as sd  # lazy: needs the PortAudio system library

            self._device = find_device(device_name, "output")
            self._device_rate = int(sd.query_devices(self._device, "output")["default_samplerate"])
        except Exception as exc:
            print(f"tts: no output device ({exc}); printing lines only")
            self._voice = None

    def say(self, sentence: str, tone: str) -> None:
        """Make one sentence, then play it once the sentence before it has finished. It returns as
        this one starts (PortAudio's own thread plays it), so the caller makes the next sentence
        meanwhile and there is no gap between them. wait() for the last one."""
        print(f"robot: {sentence}")
        if self._voice is None or not sentence.strip():
            return
        length, pitch, noise = tone_params(tone, self.settings)
        loud = (self.settings or {}).get("volume") == "loud"
        synthesis = SynthesisConfig(
            speaker_id=config.PIPER_SPEAKER_ID,
            length_scale=length * (1 + pitch),
            noise_scale=noise,
            volume=config.LOUD_GAIN if loud else 1.0,  # piper clips to full scale after the gain
        )
        try:
            chunks = [c.audio_float_array for c in self._voice.synthesize(sentence, synthesis)]
            if not chunks:
                print(f"tts: nothing to say for {sentence!r}")
                return
            audio = shift_pitch(np.concatenate(chunks), pitch)
            # USB speakers often refuse Piper's 22.05 kHz, so play at the device's own rate
            voice_rate = self._voice.config.sample_rate
            audio = resample(audio, round(len(audio) * self._device_rate / voice_rate))
            self.wait()  # the sentence before this one ends while this one was made
            self._start(audio)
        except Exception as exc:
            print(f"tts: speaking failed: {exc}")

    def _start(self, audio: np.ndarray) -> None:
        import sounddevice as sd  # lazy: needs the PortAudio system library

        sd.play(audio, samplerate=self._device_rate, device=self._device)
        stream = sd.get_stream()
        ends = time.monotonic() + len(audio) / self._device_rate + stream.latency
        self._ends_by = ends + config.PLAYBACK_GRACE_S
        self._stream = stream
        self.on_play(ends)  # muted until then by itself, not when the next sentence is ready

    def wait(self) -> None:
        """Block until the sentence playing now has finished. A speaker that stops mid-sentence (an
        HDMI screen re-syncing drops its audio) is cut off at the sentence's length plus
        PLAYBACK_GRACE_S, so the robot never hangs here with its mic muted."""
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            while stream.active:
                if time.monotonic() > self._ends_by:
                    print("fallback: the speaker stopped playing; cut the sentence off")
                    stream.abort(ignore_errors=True)  # stop() waits for audio that never drains
                    break
                time.sleep(PLAY_POLL_S)
            stream.close(ignore_errors=True)  # as sd.wait() did: frees the device
        finally:
            self.on_play(None)
