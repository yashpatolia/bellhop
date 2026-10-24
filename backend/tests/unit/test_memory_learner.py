from datetime import UTC, datetime

from bellhop.adapters.deletable_memory import DeletableLocalMemoryIndex
from bellhop.domain import Turn
from bellhop.domain.learning import CandidateFact, FactKind, Subject
from bellhop.services.memory_guard import MemoryGuard
from bellhop.services.memory_learner import MemoryLearner
from bellhop.services.memory_service import MemoryService

AT = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)


class Clock:
    def now(self):
        return AT


class Ids:
    def __init__(self):
        self.n = 0

    def new_id(self, prefix="id"):
        self.n += 1
        return f"{prefix}-{self.n}"


class FakeExtractor:
    def __init__(self, facts):
        self.facts = facts
        self.seen = None

    def extract(self, transcript, known_facts=()):
        self.seen = list(transcript)
        return list(self.facts)


def turns(*pairs):
    return [Turn(speaker=s, text=t, at=AT) for s, t in pairs]


def fact(text="Likes tea with two sugars", quote="I like tea with two sugars", **kw):
    base = dict(
        kind=FactKind.LIKE,
        text=text,
        quote=quote,
        speaker="resident",
        subject=Subject.RESIDENT,
        confidence=0.9,
    )
    base.update(kw)
    return CandidateFact(**base)


def make(extracted):
    index = DeletableLocalMemoryIndex()
    memory = MemoryService(index, Clock(), Ids())
    guard = MemoryGuard(memory, index)
    extractor = FakeExtractor(extracted)
    return MemoryLearner(extractor, guard), memory, guard, extractor


TALK = turns(
    ("resident", "I like tea with two sugars, always have."),
    ("robot", "Lovely. Two sugars it is."),
)


def test_grounded_fact_is_stored_with_its_kind_as_a_tag():
    learner, memory, _, _ = make([fact()])
    report = learner.learn("r1", TALK)
    assert [f.text for f in report.stored] == ["Likes tea with two sugars"]
    assert report.stored[0].tags == ["like"]
    assert memory.recall("r1", "tea") == report.stored


def test_fact_whose_quote_is_not_in_the_transcript_is_dropped():
    learner, memory, _, _ = make([fact(quote="I adore green tea")])
    report = learner.learn("r1", TALK)
    assert report.stored == []
    assert report.dropped == {"not_grounded": 1}
    assert memory.recall("r1", "tea") == []


def test_quote_matching_ignores_case_and_punctuation():
    learner, _, _, _ = make([fact(quote="I LIKE tea with two sugars")])
    assert len(learner.learn("r1", TALK).stored) == 1


def test_quote_must_come_from_the_claimed_speaker():
    # The robot said it, not the resident.
    learner, _, _, _ = make([fact(quote="Two sugars it is")])
    report = learner.learn("r1", TALK)
    assert report.stored == []
    assert report.dropped == {"not_grounded": 1}


def test_non_person_fact_about_someone_else_is_dropped():
    talk = turns(("resident", "My neighbour likes dogs, I find them noisy."))
    f = fact(text="Likes dogs", quote="My neighbour likes dogs", subject=Subject.OTHER)
    learner, _, _, _ = make([f])
    report = learner.learn("r1", talk)
    assert report.stored == []
    assert report.dropped == {"not_about_resident": 1}


def test_person_fact_about_family_is_kept():
    talk = turns(("resident", "My grandson Mateo visits every Sunday."))
    f = fact(
        kind=FactKind.PERSON,
        text="Grandson Mateo visits every Sunday",
        quote="My grandson Mateo visits every Sunday",
        subject=Subject.OTHER,
    )
    learner, _, _, _ = make([f])
    assert len(learner.learn("r1", talk).stored) == 1


def test_hedged_statement_goes_to_review_instead_of_memory():
    talk = turns(("resident", "I would love a dog one day, maybe."))
    f = fact(text="Wants a dog", quote="I would love a dog one day", confidence=0.9)
    learner, memory, guard, _ = make([f])
    report = learner.learn("r1", talk)
    assert report.stored == []
    assert report.pending == 1
    assert memory.recall("r1", "dog") == []
    assert len(guard.pending("r1")) == 1


def test_health_facts_always_wait_for_a_nurse():
    talk = turns(("resident", "My knee hurts when it rains, every time."))
    f = fact(
        kind=FactKind.HEALTH,
        text="Knee hurts when it rains",
        quote="My knee hurts when it rains",
        confidence=0.99,
    )
    learner, memory, _, _ = make([f])
    report = learner.learn("r1", talk)
    assert report.stored == []
    assert report.pending == 1
    assert memory.recall("r1", "knee") == []


def test_very_low_confidence_is_dropped_not_queued():
    learner, _, guard, _ = make([fact(confidence=0.2)])
    report = learner.learn("r1", TALK)
    assert report.dropped == {"low_confidence": 1}
    assert guard.pending("r1") == []


def test_unsure_but_plausible_fact_is_queued_for_review():
    learner, _, guard, _ = make([fact(confidence=0.5)])
    report = learner.learn("r1", TALK)
    assert report.pending == 1
    assert len(guard.pending("r1")) == 1


def test_duplicate_of_a_stored_fact_is_counted_and_not_stored_twice():
    learner, memory, _, _ = make([fact()])
    learner.learn("r1", TALK)
    report = learner.learn("r1", TALK)
    assert report.stored == []
    assert report.dropped == {"duplicate": 1}
    assert len(memory.recall("r1", "tea", k=10)) == 1


def test_clinical_claim_is_rejected_by_the_guard_and_counted():
    talk = turns(("resident", "The doctor said I was diagnosed with diabetes last year."))
    f = fact(
        kind=FactKind.HEALTH,
        text="Was diagnosed with diabetes last year",
        quote="I was diagnosed with diabetes last year",
        confidence=0.9,
    )
    learner, _, _, _ = make([f])
    report = learner.learn("r1", talk)
    assert report.stored == []
    assert report.dropped == {"clinical_claim": 1}


def test_extractor_sees_a_scrubbed_transcript():
    talk = turns(("resident", "I am Margaret Alvarez and my number is 4155550132."))
    learner, _, _, extractor = make([])
    learner.learn("r1", talk, resident_name="Margaret Alvarez")
    seen = " ".join(t.text for t in extractor.seen)
    assert "Margaret" not in seen
    assert "4155550132" not in seen


def test_quote_is_checked_against_the_scrubbed_transcript():
    talk = turns(("resident", "Margaret likes the radio on in the evening."))
    f = fact(
        text="Likes the radio on in the evening",
        quote="the resident likes the radio on in the evening",
    )
    learner, _, _, _ = make([f])
    assert len(learner.learn("r1", talk, resident_name="Margaret").stored) == 1


def test_nothing_extracted_gives_an_empty_report():
    learner, _, _, _ = make([])
    report = learner.learn("r1", TALK)
    assert report.stored == [] and report.pending == 0 and report.dropped == {}
