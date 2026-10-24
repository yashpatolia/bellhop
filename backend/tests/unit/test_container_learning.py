import threading
from datetime import UTC, datetime

import pytest

from bellhop.adapters.claude_extractor import ClaudeFactExtractor
from bellhop.adapters.rule_extractor import RuleFactExtractor
from bellhop.container import Settings, build_container
from bellhop.domain import Resident, Turn

AT = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)


def test_container_has_a_learner_using_the_offline_baseline_by_default():
    c = build_container(Settings())
    assert isinstance(c.memory_learner._extractor, RuleFactExtractor)


def test_default_learner_stores_a_grounded_fact_through_the_guard():
    c = build_container(Settings())
    talk = [Turn(speaker="resident", text="I love gardening, always have.", at=AT)]
    report = c.memory_learner.learn("r1", talk)
    assert [f.text for f in report.stored] == ["Likes gardening"]
    assert c.memory.recall("r1", "gardening")[0].text == "Likes gardening"


def test_learning_setting_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("BELLHOP_LEARNING", "claude")
    assert Settings.from_env().learning == "claude"


def test_claude_learning_builds_a_claude_extractor(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    c = build_container(Settings(learning="claude"))
    assert isinstance(c.memory_learner._extractor, ClaudeFactExtractor)


def test_unknown_learning_setting_is_rejected():
    with pytest.raises(ValueError, match="learning"):
        build_container(Settings(learning="magic"))


def test_resolving_a_call_stores_what_the_resident_said(monkeypatch):
    started = []
    real_thread = threading.Thread

    class TrackedThread(real_thread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            started.append(self)

    monkeypatch.setattr(threading, "Thread", TrackedThread)
    c = build_container(Settings())
    c.store.residents.save(Resident(id="res9", name="Test Person", room="9"))
    call = c.call_service.raise_call("9")
    c.call_service.add_turn(call.id, "resident", "I love gardening, always have.")
    c.call_service.resolve(call.id)
    for thread in started:
        thread.join(timeout=5)
    assert c.memory.recall("res9", "gardening")[0].text == "Likes gardening"
