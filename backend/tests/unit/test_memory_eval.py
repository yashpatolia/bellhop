from bellhop.domain.learning import CandidateFact, FactKind, Subject
from bellhop.labelled.memory_cases import CASES, ExpectedFact, MemoryCase
from bellhop.labelled.memory_eval import format_report, run_eval

LIKES_TEA = MemoryCase(
    id="t1",
    transcript=(("resident", "I like tea with two sugars."),),
    expected=(ExpectedFact(FactKind.LIKE, ("tea", "sugar")),),
)
NEGATION = MemoryCase(
    id="t2",
    transcript=(("resident", "I don't take sugar any more."),),
    forbidden=(("two", "sugar"),),
)


def cand(text, quote, kind=FactKind.LIKE, confidence=0.9):
    return CandidateFact(
        kind=kind,
        text=text,
        quote=quote,
        speaker="resident",
        subject=Subject.RESIDENT,
        confidence=confidence,
    )


class ScriptedExtractor:
    """Returns canned candidates keyed by the first resident line."""

    def __init__(self, by_first_line):
        self.by = by_first_line

    def extract(self, transcript, known_facts=()):
        return list(self.by.get(transcript[0].text, []))


def test_perfect_extraction_scores_full_marks():
    ex = ScriptedExtractor(
        {
            "I like tea with two sugars.": [
                cand("Likes tea with two sugars", "I like tea with two sugars")
            ]
        }
    )
    result = run_eval(ex, [LIKES_TEA])
    assert result.recall == 1.0
    assert result.recall_auto == 1.0
    assert result.precision_auto == 1.0


def test_extra_unexpected_fact_lowers_precision():
    ex = ScriptedExtractor(
        {
            "I like tea with two sugars.": [
                cand("Likes tea with two sugars", "I like tea with two sugars"),
                cand(
                    "Likes tea", "I like tea"
                ),  # grounded but not an expected fact, and a duplicate-ish
            ]
        }
    )
    ex.by["I like tea with two sugars."][1] = cand("Enjoys sugar", "two sugars")
    result = run_eval(ex, [LIKES_TEA])
    assert result.precision_auto == 0.5


def test_forbidden_fact_that_is_auto_stored_is_a_hard_violation():
    ex = ScriptedExtractor(
        {"I don't take sugar any more.": [cand("Takes two sugars in tea", "take sugar")]}
    )
    result = run_eval(ex, [NEGATION])
    assert result.forbidden_auto == 1
    assert result.cases[0].violations == ["two sugar"]


def test_fact_waiting_for_review_counts_for_recall_but_not_auto_recall():
    ex = ScriptedExtractor(
        {
            "I like tea with two sugars.": [
                cand("Likes tea with two sugars", "I like tea with two sugars", confidence=0.5)
            ]
        }
    )
    result = run_eval(ex, [LIKES_TEA])
    assert result.recall == 1.0
    assert result.recall_auto == 0.0


def test_dropped_candidates_are_tallied_by_reason():
    ex = ScriptedExtractor({"I like tea with two sugars.": [cand("Likes coffee", "I like coffee")]})
    result = run_eval(ex, [LIKES_TEA])
    assert result.dropped == {"not_grounded": 1}


def test_report_lists_headline_numbers():
    ex = ScriptedExtractor({})
    text = format_report(run_eval(ex, [LIKES_TEA]), title="empty")
    assert "empty" in text and "recall" in text and "precision" in text


def test_labelled_set_is_large_and_well_formed():
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids)) >= 25
    for c in CASES:
        assert c.transcript and all(s in ("resident", "robot", "nurse") for s, _ in c.transcript)
        for e in c.expected:
            assert e.keywords and all(k == k.casefold() for k in e.keywords)
        for f in c.forbidden:
            assert f and all(k == k.casefold() for k in f)


def test_labelled_set_covers_the_traps_models_fall_for():
    notes = " ".join(c.note.lower() for c in CASES)
    for trap in (
        "negation",
        "hypothetical",
        "third party",
        "declined",
        "sarcasm",
        "confus",
        "clinical",
    ):
        assert trap in notes, trap
