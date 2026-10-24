import threading

from rover import config
from rover.agent.tone import TonePick, ask_jev_tone


def test_a_sure_jev_tone_is_used_for_the_whole_reply():
    pick = TonePick([("resident", "I won!")], lambda transcript: ("excited", 0.9))
    assert pick.choose("calm") == "excited"
    assert pick.choose("gentle") == "excited"  # one tone per reply


def test_unsure_failed_or_slow_jev_falls_back_to_claudes_tag(monkeypatch):
    monkeypatch.setattr(config, "JEV_TONE_WAIT_S", 0.05)
    release = threading.Event()

    def crash(transcript):
        raise RuntimeError("bug")

    try:
        for ask in (
            lambda t: ("excited", 0.3),
            lambda t: None,
            crash,
            lambda t: release.wait(2) and ("excited", 0.9),
        ):
            assert TonePick([], ask).choose("gentle") == "gentle"
    finally:
        release.set()


def test_no_key_means_no_jev_call():
    assert ask_jev_tone([("resident", "hello")]) is None
