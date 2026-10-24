import json
import threading
import time

import pytest

from rover import config
from rover.speech import __main__ as voice_main
from rover.speech import textmode


def test_load_script_skips_blanks_and_comments(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(
        '# a comment\n\n{"greeting": "Hello!"}\n'
        '{"say": "Can I have water?", "reply": "Of course."}\n'
        '{"say": "bye"}\n',
        encoding="utf-8",
    )
    script = textmode.load_script(path)
    assert script.greeting == "Hello!"
    assert [t.say for t in script.turns] == ["Can I have water?", "bye"]
    assert script.turns[0].reply == "Of course."
    assert script.turns[1].reply is None
    assert script.turns[0].pause_s == 0.0


@pytest.mark.parametrize("line", ["not json", '{"say": 3}', '{"nothing": 1}', '{"say": ""}', "[1]"])
def test_load_script_names_the_bad_line(tmp_path, line):
    path = tmp_path / "s.jsonl"
    path.write_text('{"say": "ok"}\n' + line + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        textmode.load_script(path)


@pytest.mark.parametrize(
    ("text", "urgency"),
    [
        ("Lovely weather today", 1),
        ("Could I have a glass of water please", 2),
        ("My tummy hurts and I feel dizzy", 3),
        ("Please get me a nurse", 3),
        ("I fell and I can't get up", 4),
        ("I have chest pain", 4),
        ("I can't breathe", 4),
    ],
)
def test_mock_triage_levels(text, urgency):
    result = textmode.mock_triage([("resident", text)], [])
    assert result.urgency == urgency
    assert 0.0 <= result.confidence <= 1.0
    assert result.category


def test_mock_triage_uses_the_most_urgent_line():
    transcript = [("resident", "I fell"), ("robot", "Oh no"), ("resident", "thanks, nice day")]
    assert textmode.mock_triage(transcript, []).urgency == 4


# ---- the whole visit in text mode, against an in-memory backend


class MemoryBackend:
    """Enough of rover.backend.Backend for one visit."""

    def __init__(self, status="assigned"):
        self.log = []
        self.call = {"id": "c1", "room": "12", "urgency": None, "status": status}

    def in_visit(self, call_id):
        self.log.append(("in_visit",))
        self.call["status"] = "in_visit"
        return True

    def resident(self, resident_id):
        return None

    preferences = speech_settings = resident

    def memory(self, resident_id, q="", k=3):
        return []

    def add_turn(self, call_id, speaker, text):
        self.log.append(("turn", speaker, text))
        return dict(self.call)

    def score(self, call_id, urgency, category, summary, confidence):
        self.log.append(("score", urgency, category, confidence))
        self.call["urgency"] = max(urgency, self.call["urgency"] or 0)
        if urgency >= 3:
            self.call["status"] = "escalated"
        return dict(self.call)

    def triage_failed(self, call_id):
        self.log.append(("triage_failed",))
        return dict(self.call)

    def get_call(self, call_id):
        return dict(self.call)

    def resolve(self, call_id, by_robot):
        self.log.append(("resolve", by_robot))
        self.call["status"] = "resolved"
        return dict(self.call)


@pytest.fixture
def fast(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "VISIT_QUIET_END_S", 0.3)
    monkeypatch.setattr(config, "CALL_POLL_S", 0.05)
    monkeypatch.setenv("ROVER_TEXT_RUNS", str(tmp_path / "runs"))
    sent = []
    monkeypatch.setattr(voice_main, "post_pi", lambda path, body: sent.append((path, body)))
    return sent


def run_visit(backend, lines, tmp_path, timeout=10.0):
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    visit = textmode.TextVisit(backend.call, "12", backend, textmode.load_script(path))
    started = time.monotonic()
    visit.run()
    assert time.monotonic() - started < timeout
    return visit


def test_routine_chat_is_resolved_by_the_robot(fast, tmp_path):
    backend = MemoryBackend()
    run_visit(backend, [{"say": "Isn't it a lovely day"}, {"say": "Yes, thank you"}], tmp_path)
    kinds = [entry[0] for entry in backend.log]
    assert kinds[0] == "in_visit"
    assert [e[2] for e in backend.log if e[0] == "turn" and e[1] == "resident"] == [
        "Isn't it a lovely day",
        "Yes, thank you",
    ]
    assert [e[1] for e in backend.log if e[0] == "score"] == [1, 1]
    assert all(e[3] > 0 for e in backend.log if e[0] == "score")
    assert backend.log[-1] == ("resolve", True)
    assert fast == [("/go_to", {"room": config.HOME_ROOM})]
    robot = [e[2] for e in backend.log if e[0] == "turn" and e[1] == "robot"]
    assert robot == [
        textmode.DEFAULT_GREETING,
        textmode.DEFAULT_REPLY,
        textmode.DEFAULT_REPLY,
        voice_main.QUIET_GOODBYE,
    ]


def test_goodbye_ends_the_visit_without_waiting(fast, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VISIT_QUIET_END_S", 60.0)
    backend = MemoryBackend()
    run_visit(backend, [{"say": "Thanks for visiting. Goodbye!"}], tmp_path, timeout=5.0)
    assert ("resolve", True) in backend.log


def test_emergency_waits_for_the_nurse_then_resolves_not_by_robot(fast, tmp_path):
    backend = MemoryBackend()

    def nurse_arrives():
        time.sleep(0.6)
        backend.call["status"] = "nurse_acked"

    threading.Thread(target=nurse_arrives, daemon=True).start()
    run_visit(backend, [{"say": "I fell and I can't get up"}], tmp_path)
    assert any(e[0] == "score" and e[1] == 4 for e in backend.log)
    assert backend.log[-1] == ("resolve", False)
    assert fast[-1] == ("/go_to", {"room": config.HOME_ROOM})


def test_unfinished_triage_does_not_resolve_by_robot(fast, tmp_path, monkeypatch):
    monkeypatch.setattr(textmode, "mock_triage", lambda transcript, flags: None)
    backend = MemoryBackend()

    def nurse():
        time.sleep(0.6)
        backend.call["status"] = "nurse_acked"

    threading.Thread(target=nurse, daemon=True).start()
    run_visit(backend, [{"say": "hello there"}], tmp_path)
    assert ("triage_failed",) in backend.log
    assert ("resolve", True) not in backend.log


def test_pause_s_is_read_and_validated(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text('{"say": "hi", "pause_s": 2.5}\n', encoding="utf-8")
    assert textmode.load_script(path).turns[0].pause_s == 2.5
    path.write_text('{"say": "hi", "pause_s": -1}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        textmode.load_script(path)


def test_pause_delays_the_next_turn(fast, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VISIT_QUIET_END_S", 5.0)  # the quiet timer must not fire first
    backend = MemoryBackend()
    started = time.monotonic()
    run_visit(backend, [{"say": "hello", "pause_s": 0.7}, {"say": "tea please"}], tmp_path)
    turns = [e for e in backend.log if e[0] == "turn" and e[1] == "resident"]
    assert [t[2] for t in turns] == ["hello", "tea please"]
    assert time.monotonic() - started >= 0.7
