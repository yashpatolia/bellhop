"""Piper voice (Poppy): one sentence at a time, tone tags set speed, pitch and expressiveness."""

import numpy as np
from piper import PiperVoice, SynthesisConfig

from rover import config
from rover.speech.mic import find_device


def effective_tone(tone: str, settings: dict | None) -> str:
    """The tag the voice and the eyes use: speech-settings "always calm" wins over Claude's tag."""
    if (settings or {}).get("tone") == "calm":
        return "calm"
    return tone if tone in config.TONES else config.DEFAULT_TONE


def tone_params(tone: str, settings: dict | None) -> tuple[float, float, float]:
    """(length_scale, pitch, noise_scale) for a tone tag, adjusted by backend speech-settings."""
    length, pitch, noise = config.TONES[effective_tone(tone, settings)]
    settings = settings or {}
    slow = settings.get("rate") == "slow"
    if slow:
        length += config.SLOW_LENGTH_BONUS
    if slow or settings.get("volume") == "loud" or settings.get("captions"):
        pitch = 0.0  # hard of hearing: keep the natural pitch
    length = max(length, config.MIN_LENGTH_SCALE)
    pitch = min(max(pitch, -config.MAX_PITCH), config.MAX_PITCH)
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
        """Speak one sentence and block until it has played."""
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
            import sounddevice as sd  # lazy: needs the PortAudio system library

            sd.play(audio, samplerate=self._device_rate, device=self._device)
            sd.wait()
        except Exception as exc:
            print(f"tts: speaking failed: {exc}")
