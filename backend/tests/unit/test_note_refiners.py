from datetime import UTC, datetime

import pytest

from bellhop.adapters.claude_note_refiner import ClaudeNoteRefiner, _Out
from bellhop.adapters.rule_note_refiner import RuleNoteRefiner
from bellhop.domain.care import NoteCategory as C


class Clock:
    def now(self):
        return datetime(2026, 10, 24, 12, tzinfo=UTC)


rules = RuleNoteRefiner(Clock())


def test_trims_capitalises_and_drops_the_full_stop():
    out = rules.refine(C.LIKE, "  enjoys the garden.  ")
    assert out.text == "Enjoys the garden"
    assert "capital" in " ".join(out.notes).lower()


def test_pronoun_leads_become_third_person_facts():
    assert rules.refine(C.LIKE, "he likes his tea strong").text == "Likes his tea strong"


def test_shorthand_is_expanded_and_a_start_year_is_read():
    out = rules.refine(C.CONDITION, "htn since 2015")
    assert (out.text, out.since) == ("High blood pressure", "2015")
    assert "high blood pressure" in " ".join(out.notes)


def test_years_are_counted_back_from_now():
    out = rules.refine(C.CONDITION, "COPD for 8 years")
    assert (out.text, out.since) == ("COPD", "2018")


def test_medicines_keep_only_the_name():
    out = rules.refine(C.MEDICINE, "metformin 500mg twice daily")
    assert out.text == "Metformin"
    assert "dose" in " ".join(out.notes).lower()


def test_shouting_is_written_in_normal_case():
    assert rules.refine(C.DISLIKE, "LOUD TELEVISION AT NIGHT").text == "Loud television at night"


def test_an_empty_note_is_refused():
    with pytest.raises(ValueError, match="Nothing to add"):
        rules.refine(C.LIKE, "   ")


class Parsed:
    def __init__(self, parsed):
        self.parsed_output = parsed


class FakeClient:
    def __init__(self, result=None, fail=False):
        self.calls = []
        self._result, self._fail = result, fail
        self.messages = self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self._fail:
            raise RuntimeError("api down")
        return Parsed(self._result)


def test_claude_refiner_returns_the_models_wording():
    client = FakeClient(_Out(text="High blood pressure", since="2015", notes=["Expanded htn"]))
    out = ClaudeNoteRefiner(rules, client=client).refine(C.CONDITION, "htn since 2015")
    assert (out.text, out.since, out.notes) == ("High blood pressure", "2015", ["Expanded htn"])
    assert "htn since 2015" in client.calls[0]["messages"][0]["content"]
    assert "Never add a fact" in client.calls[0]["system"]


def test_claude_refiner_ignores_since_outside_conditions():
    client = FakeClient(_Out(text="Likes tea", since="2015"))
    assert ClaudeNoteRefiner(rules, client=client).refine(C.LIKE, "likes tea").since is None


def test_claude_failure_falls_back_to_the_rules():
    out = ClaudeNoteRefiner(rules, client=FakeClient(fail=True)).refine(C.LIKE, "he likes tea")
    assert out.text == "Likes tea"


def test_an_unparsed_reply_falls_back_to_the_rules():
    out = ClaudeNoteRefiner(rules, client=FakeClient(None)).refine(C.LIKE, "he likes tea")
    assert out.text == "Likes tea"
