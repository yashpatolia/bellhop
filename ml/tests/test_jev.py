"""The optional Jev adapter is safe to leave disabled on every developer machine."""

from __future__ import annotations

import threading

import httpx

from rover.agent import jev
from rover.agent.tone import TonePick, ask_jev_tone


class Response:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


def test_no_key_never_attempts_a_jev_request(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    def must_not_request(*args, **kwargs):
        raise AssertionError("Jev request without a key")

    monkeypatch.setattr(jev.httpx, "post", must_not_request)
    assert jev.decide("hello", {}) is None
    assert ask_jev_tone([("resident", "hello")]) is None


def test_decide_sends_key_without_logging_or_retaining_it(monkeypatch):
    seen = {}
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")

    def post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return Response({"answers": {"tone": {"choice": "calm", "confidence": 0.9}}})

    monkeypatch.setattr(jev.httpx, "post", post)
    assert jev.decide("state", {"tone": {"type": "choice"}}) == {
        "tone": {"choice": "calm", "confidence": 0.9}
    }
    assert seen["url"] == jev.API_URL
    assert seen["headers"]["Authorization"] == "Bearer test-key"
    assert seen["timeout"] == 1.5


def test_jev_http_or_payload_failure_is_ignored(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")

    def timed_out(*args, **kwargs):
        raise httpx.ReadTimeout("x")

    monkeypatch.setattr(jev.httpx, "post", timed_out)
    assert jev.decide("state", {}) is None
    monkeypatch.setattr(jev.httpx, "post", lambda *args, **kwargs: Response({"wrong": "shape"}))
    assert jev.decide("state", {}) is None


def test_tone_pick_accepts_only_a_valid_confident_tone():
    pick = TonePick([], lambda _: ("excited", 0.95))
    assert pick._done.wait(1)
    assert pick.choose("calm") == "excited"
    invalid = TonePick([], lambda _: ("not-a-tone", 0.95))
    assert invalid._done.wait(1)
    assert invalid.choose("calm") == "calm"


def test_slow_tone_is_ignored_without_waiting():
    release = threading.Event()
    pick = TonePick([], lambda _: release.wait(2) and ("excited", 0.95))
    try:
        assert pick.choose("calm") == "calm"
    finally:
        release.set()
