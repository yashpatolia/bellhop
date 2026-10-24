from datetime import UTC, datetime, timedelta

from bellhop.adapters.deletable_memory import DeletableLocalMemoryIndex
from bellhop.services.memory_guard import Accepted, MemoryGuard
from bellhop.services.memory_service import MemoryService


class Ids:
    def __init__(self):
        self.n = 0

    def new_id(self, prefix="id"):
        self.n += 1
        return f"{prefix}-{self.n}"


class TickingClock:
    def __init__(self):
        self.t = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)

    def now(self):
        return self.t


def make():
    index = DeletableLocalMemoryIndex()
    clock = TickingClock()
    return MemoryGuard(MemoryService(index, clock, Ids()), index), clock


def test_a_fact_defaults_to_staff_full_confidence_seen_once():
    g, clock = make()
    fact = g.propose("r1", "Takes her tea with two sugars", source="staff").fact
    assert (fact.source, fact.confidence, fact.quote, fact.call_id) == ("staff", 1.0, None, None)
    assert (fact.times_seen, fact.last_confirmed) == (1, clock.now())


def test_provenance_is_stored_on_an_accepted_fact():
    g, _ = make()
    result = g.propose(
        "r1",
        "Likes gardening",
        tags=["like"],
        source="conversation",
        confidence=0.9,
        quote="I love my garden",
        call_id="call_1",
    )
    assert isinstance(result, Accepted)
    f = result.fact
    assert (f.source, f.confidence, f.quote, f.call_id) == (
        "conversation",
        0.9,
        "I love my garden",
        "call_1",
    )


def test_a_repeated_fact_counts_as_seen_again_and_is_reconfirmed():
    g, clock = make()
    first = g.propose("r1", "Likes gardening in spring", source="conversation").fact
    clock.t += timedelta(days=2)
    again = g.propose("r1", "Likes gardening in spring", source="conversation")
    assert again.reason == "duplicate"
    [stored] = g.facts("r1")
    assert stored.id == first.id
    assert stored.times_seen == 2
    assert stored.last_confirmed == clock.now()


def test_pending_facts_keep_their_provenance_when_approved():
    g, _ = make()
    g.propose(
        "r1",
        "Dislikes loud television",
        tags=["dislike"],
        source="conversation",
        confidence=0.5,
        quote="far too loud",
        call_id="call_2",
    )
    [p] = g.pending("r1")
    assert (p.quote, p.call_id) == ("far too loud", "call_2")
    fact = g.approve(p.id, "r1").fact
    assert (fact.source, fact.confidence, fact.quote, fact.call_id) == (
        "conversation",
        0.5,
        "far too loud",
        "call_2",
    )


def test_facts_lists_everything_stored_for_a_resident():
    g, _ = make()
    g.propose("r1", "Likes gardening in spring")
    g.propose("r1", "Takes her tea with two sugars")
    g.propose("r2", "Reads the paper at breakfast")
    assert [f.text for f in g.facts("r1")] == [
        "Likes gardening in spring",
        "Takes her tea with two sugars",
    ]
