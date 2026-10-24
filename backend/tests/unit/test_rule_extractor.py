from datetime import UTC, datetime

from bellhop.adapters.rule_extractor import RuleFactExtractor
from bellhop.domain import Turn
from bellhop.domain.learning import FactKind, Subject

AT = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)


def run(*pairs):
    return RuleFactExtractor().extract([Turn(speaker=s, text=t, at=AT) for s, t in pairs])


def test_like_statement_becomes_a_like_fact_with_its_quote():
    [f] = run(("resident", "I love gardening, always have."))
    assert f.kind is FactKind.LIKE
    assert "gardening" in f.text.lower()
    assert f.quote == "I love gardening, always have"
    assert f.speaker == "resident" and f.subject is Subject.RESIDENT


def test_dislike_statement_becomes_a_dislike_fact():
    [f] = run(("resident", "I cannot stand fish."))
    assert f.kind is FactKind.DISLIKE


def test_family_member_becomes_a_person_fact_about_someone_else():
    [f] = run(("resident", "My grandson Mateo visits every Sunday."))
    assert f.kind is FactKind.PERSON and f.subject is Subject.OTHER


def test_robot_lines_are_ignored():
    assert run(("robot", "I hear you love the roses.")) == []


def test_questions_and_small_talk_produce_nothing():
    assert run(("resident", "Is it still raining out there?")) == []
