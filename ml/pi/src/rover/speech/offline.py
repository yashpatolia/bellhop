"""Offline STT fallback: Moonshine on one finished turn.

The model must be downloaded by ``scripts/download_models.py`` before the
speech process starts. A conversation must never trigger a model download.
"""

from pathlib import Path

import numpy as np
from moonshine_voice import string_to_model_arch
from moonshine_voice.download import _primary_stt_group, find_model_info
from moonshine_voice.download_file import get_cache_dir
from moonshine_voice.transcriber import Transcriber

from rover import config


def cached_model_path(cache_dir: Path, group: dict, arch: object) -> tuple[str, object]:
    """Return a complete cached Moonshine model or fail without network I/O."""
    root = cache_dir / group["base_url"].removeprefix("https://")
    missing = [file["name"] for file in group["files"] if not (root / file["name"]).is_file()]
    if missing:
        raise RuntimeError(
            "Moonshine cache incomplete (missing "
            + ", ".join(missing)
            + "); run scripts/download_models.py before starting speech"
        )
    return str(root), arch


def cached_model() -> tuple[str, object]:
    """Find the configured model in the local cache. Never call the downloader."""
    arch = string_to_model_arch(config.MOONSHINE_ARCH)
    info = find_model_info("en", arch)
    group = _primary_stt_group(info)
    return cached_model_path(get_cache_dir(), group, arch)


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
                self._transcriber = Transcriber(*cached_model())
            samples = (audio.astype(np.float32) / 32768).tolist()
            transcript = self._transcriber.transcribe_without_streaming(
                samples, sample_rate=config.SAMPLE_RATE
            )
        except Exception as exc:
            print(f"offline: Moonshine failed: {exc}")
            return ""
        return " ".join(line.text.strip() for line in transcript.lines if line.text).strip()
