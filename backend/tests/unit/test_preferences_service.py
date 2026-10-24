from datetime import UTC, datetime

import pytest

from bellhop.domain.care import Preferences
from bellhop.services.preferences_service import PreferencesService


class FakeRepo:
    def __init__(self):
        self.store = {}

    def get(self, resident_id):
        return self.store.get(resident_id, Preferences(resident_id=resident_id))

    def save(self, prefs):
        self.store[prefs.resident_id] = prefs


class Clock:
    def now(self):
        return datetime(2026, 10, 24, tzinfo=UTC)


def svc():
    return PreferencesService(FakeRepo(), Clock())


def test_get_defaults():
    assert svc().get("r1") == Preferences(resident_id="r1")


def test_update_persists_and_merges():
    s = svc()
    s.update("r1", night_mode=True)
    p = s.update("r1", favourite_drink="tea")
    assert p.night_mode and p.favourite_drink == "tea"
    assert s.get("r1") == p
    assert s.get("r2").night_mode is False


def test_update_rejects_unknown_field():
    with pytest.raises(ValueError):
        svc().update("r1", shoe_size=9)


def test_update_rejects_bad_type():
    with pytest.raises(ValueError):
        svc().update("r1", hard_of_hearing="maybe")


def test_speech_defaults():
    assert svc().speech_settings("r1") == {
        "rate": "normal",
        "volume": "normal",
        "captions": False,
        "tone": "normal",
    }


def test_hard_of_hearing():
    s = svc()
    s.update("r1", hard_of_hearing=True)
    assert s.speech_settings("r1") == {
        "rate": "slow",
        "volume": "loud",
        "captions": True,
        "tone": "normal",
    }


def test_night_mode_is_calm():
    s = svc()
    s.update("r1", night_mode=True)
    assert s.speech_settings("r1")["tone"] == "calm"
