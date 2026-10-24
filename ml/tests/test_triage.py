import threading

from rover import config
from rover.triage import triage as triage_module
from rover.triage.triage import TriageResult, format_visit, triage, triage_and_post

TRANSCRIPT = [
    ("resident", "Hello."),
    ("robot", "Hi! How can I help?"),
    ("resident", "  I went down by the bed and can't get up.  "),
]
CLAUDE = TriageResult(3, "mobility", "Says she went down by the bed.", 0.8, "claude")


def answer(result):
    return lambda transcript, risk_flags: result


def test_claude_result_is_used_as_is():
    assert triage(TRANSCRIPT, [], ask_claude=answer(CLAUDE)) == CLAUDE


def test_no_answer_is_none():
    assert triage(TRANSCRIPT, [], ask_claude=answer(None)) is None


def test_slow_and_crashing_claude_are_dropped(monkeypatch):
    monkeypatch.setattr(config, "TRIAGE_TIMEOUT_S", 0.1)
    release = threading.Event()

    def slow(transcript, risk_flags):
        release.wait(2)
        return CLAUDE

    def crash(transcript, risk_flags):
        raise RuntimeError("bug")

    try:
        assert triage(TRANSCRIPT, [], ask_claude=slow) is None
        assert triage(TRANSCRIPT, [], ask_claude=crash) is None
    finally:
        release.set()


def test_models_see_labelled_speakers_and_risk_flags():
    text = format_visit(TRANSCRIPT, ["falls", "dementia"])
    assert "Risk flags: falls, dementia" in text
    assert "robot: Hi! How can I help?" in text and "resident: Hello." in text
    assert "Risk flags: none" in format_visit(TRANSCRIPT, [])


class FakeBackend:
    def __init__(self):
        self.posted = []

    def score(self, *args):
        self.posted.append(("score", *args))
        return {"id": args[0], "urgency": args[1]}

    def triage_failed(self, call_id):
        self.posted.append(("triage_failed", call_id))
        return {"id": call_id, "urgency": 3}


def test_triage_and_post_posts_the_score(monkeypatch):
    monkeypatch.setattr(triage_module, "triage", lambda transcript, flags: CLAUDE)
    backend = FakeBackend()
    call = triage_and_post(backend, "c1", TRANSCRIPT, [])
    assert backend.posted == [("score", "c1", 3, "mobility", CLAUDE.summary, 0.8)]
    assert call == {"id": "c1", "urgency": 3}


def test_triage_and_post_reports_failure(monkeypatch):
    monkeypatch.setattr(triage_module, "triage", lambda transcript, flags: None)
    backend = FakeBackend()
    triage_and_post(backend, "c1", TRANSCRIPT, [])
    assert backend.posted == [("triage_failed", "c1")]


def test_timeout_budget_fits_a_retry():
    assert config.TRIAGE_TIMEOUT_S >= 6.0
    assert config.TRIAGE_ATTEMPT_S < config.TRIAGE_TIMEOUT_S


class Flaky:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, transcript, risk_flags):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_claude_is_retried_once_after_a_failure():
    flaky = Flaky(None, CLAUDE)
    result = triage(TRANSCRIPT, [], ask_claude=flaky)
    assert result == CLAUDE and flaky.calls == 2


def test_claude_is_retried_once_after_a_crash():
    flaky = Flaky(RuntimeError("boom"), CLAUDE)
    assert triage(TRANSCRIPT, [], ask_claude=flaky) == CLAUDE


def test_claude_gets_only_one_retry():
    flaky = Flaky(None, None, CLAUDE)
    assert triage(TRANSCRIPT, [], ask_claude=flaky) is None
    assert flaky.calls == 2


def test_no_retry_when_the_budget_is_spent():
    now = iter([0.0, 100.0, 100.0, 100.0])
    flaky = Flaky(None, CLAUDE)
    result = triage(TRANSCRIPT, [], ask_claude=flaky, clock=lambda: next(now, 100.0))
    assert result is None and flaky.calls == 1
