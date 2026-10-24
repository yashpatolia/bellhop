"""Read and update resident preferences; derive robot speech settings."""

from __future__ import annotations

from typing import Any

from bellhop.domain.care import Preferences
from bellhop.ports import Clock
from bellhop.ports.care import PreferencesRepository

_FIELDS = frozenset(Preferences.model_fields) - {"resident_id"}


class PreferencesService:
    def __init__(self, repo: PreferencesRepository, clock: Clock) -> None:
        self._repo = repo
        self._clock = clock

    def get(self, resident_id: str) -> Preferences:
        return self._repo.get(resident_id)

    def update(self, resident_id: str, **fields: Any) -> Preferences:
        unknown = set(fields) - _FIELDS
        if unknown:
            raise ValueError(f"unknown preference fields: {sorted(unknown)}")
        merged = {**self._repo.get(resident_id).model_dump(), **fields}
        prefs = Preferences.model_validate(merged, strict=True)  # raises on bad types
        self._repo.save(prefs)
        return prefs

    def speech_settings(self, resident_id: str) -> dict[str, Any]:
        p = self._repo.get(resident_id)
        hard = p.hard_of_hearing
        return {
            "rate": "slow" if hard else "normal",
            "volume": "loud" if hard else "normal",
            "captions": hard,
            "tone": "calm" if p.night_mode else "normal",
        }
