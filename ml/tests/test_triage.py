import threading

from rover import config
from rover.triage import triage as triage_module
from rover.triage.triage import TriageResult, format_visit, jev_urgency, triage, triage_and_post

TRANSCRIPT = [
    ("resident", "Hello."),
    ("robot", "Hi! How can I help?"),
    ("resident", "  I went down by the bed and can't get up.  "),
]


def answer(result):
    return lambda transcript, risk_flags: result


JEV = TriageResult(4, "fall", "", 0.9, "jev")
CLAUDE = TriageResult(3, "mobility", "Says she went down by the bed.", 0.8, "claude")


def test_both_take_higher_urgency_with_claudes_summary_and_confidence():
    result = triage(TRANSCRIPT, [], ask_jev=answer(JEV), ask_claude=answer(CLAUDE))
    assert result == TriageResult(4, "fall", "Says she went down by the bed.", 0.8, "jev+claude")


def test_tie_keeps_claudes_category():
    jev = TriageResult(3, "pain", "", 0.9, "jev")
    result = triage(TRANSCRIPT, [], ask_jev=answer(jev), ask_claude=answer(CLAUDE))
    assert (result.urgency, result.category) == (3, "mobility")


def test_claude_only_is_used_as_is():
    assert triage(TRANSCRIPT, [], ask_jev=answer(None), ask_claude=answer(CLAUDE)) == CLAUDE


def test_jev_only_gets_low_confidence_and_quotes_the_resident():
    result = triage(TRANSCRIPT, [], ask_jev=answer(JEV), ask_claude=answer(None))
    assert result.confidence == config.JEV_ONLY_CONFIDENCE
    assert result.summary == 'Resident said: "I went down by the bed and can\'t get up."'
    assert (result.urgency, result.category, result.source) == (4, "fall", "jev")


def test_no_answer_is_none():
    assert triage(TRANSCRIPT, [], ask_jev=answer(None), ask_claude=answer(None)) is None


def test_slow_and_crashing_models_are_dropped(monkeypatch):
    monkeypatch.setattr(config, "TRIAGE_TIMEOUT_S", 0.1)
    release = threading.Event()

    def slow(transcript, risk_flags):
        release.wait(2)
        return CLAUDE

    def crash(transcript, risk_flags):
        raise RuntimeError("bug")

    try:
        assert triage(TRANSCRIPT, [], ask_jev=answer(JEV), ask_claude=slow).source == "jev"
        assert triage(TRANSCRIPT, [], ask_jev=crash, ask_claude=answer(CLAUDE)) == CLAUDE
    finally:
        release.set()


def test_jev_urgency_rounds_half_up_and_stays_in_range():
    assert [jev_urgency(s) for s in (0.0, 0.49, 0.5, 1.7, 2.5, 3.0, 9.0, -1.0)] == [
        1, 1, 2, 3, 4, 4, 4, 1]


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
