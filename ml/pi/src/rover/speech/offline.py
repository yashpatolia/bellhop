"""Offline STT fallback: Moonshine on one finished turn."""

import numpy as np
from moonshine_voice import get_model_for_language, string_to_model_arch
from moonshine_voice.transcriber import Transcriber

from rover import config


class OfflineSTT:
    def __init__(self) -> None:
        self._transcriber: Transcriber | None = None

    def transcribe(self, audio: np.ndarray) -> str:
        """int16 16 kHz mono -> text; "" (with the reason printed) on failure."""
        if audio is None or len(audio) == 0:
            print("offline: no audio to transcribe")
            return ""
        try:
            if self._transcriber is None:
                # cached models load without the network (scripts/download_models.py fetches them)
                arch = string_to_model_arch(config.MOONSHINE_ARCH)
                self._transcriber = Transcriber(*get_model_for_language("en", arch))
            samples = (audio.astype(np.float32) / 32768).tolist()
            transcript = self._transcriber.transcribe_without_streaming(
                samples, sample_rate=config.SAMPLE_RATE
            )
        except Exception as exc:
            print(f"offline: Moonshine failed: {exc}")
            return ""
        return " ".join(line.text.strip() for line in transcript.lines if line.text).strip()
