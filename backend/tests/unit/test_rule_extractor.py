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


def test_a_routine_is_rewritten_about_the_resident():
    [f] = run(("resident", "I always say my prayers before bed."))
    assert f.kind is FactKind.ROUTINE
    assert f.text == "Always says their prayers before bed"
    assert f.quote == "I always say my prayers before bed"


def test_a_family_member_reads_as_a_fact_not_a_quote():
    [f] = run(("resident", "My granddaughter Sophie visits every Sunday."))
    assert f.text == "Granddaughter Sophie visits every Sunday"


def test_a_routine_about_someone_else_or_a_fragment_is_not_stored():
    assert run(("resident", "He always comes home at six.")) == []
    assert run(("resident", "Stew, always stew.")) == []


def test_liking_a_pronoun_says_nothing():
    assert run(("resident", "It keeps my mind sharp, and I love it.")) == []
    assert run(("resident", "That television, I hate it.")) == []
    assert run(("resident", "I always take them after breakfast.")) == []


def test_sarcasm_is_not_a_like():
    assert run(("resident", "Oh yes, I just love being woken at five by the nurses.")) == []
