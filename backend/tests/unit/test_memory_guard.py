from datetime import UTC, datetime

import pytest

from bellhop.adapters.deletable_memory import DeletableLocalMemoryIndex
from bellhop.services.memory_guard import Accepted, MemoryGuard, Rejected
from bellhop.services.memory_service import MemoryService


class Clock:
    def now(self):
        return datetime(2026, 10, 24, 9, 0, tzinfo=UTC)


class Ids:
    def __init__(self):
        self.n = 0

    def new_id(self, prefix="id"):
        self.n += 1
        return f"{prefix}-{self.n}"


def make():
    index = DeletableLocalMemoryIndex()
    svc = MemoryService(index, Clock(), Ids())
    return MemoryGuard(svc, index), svc, index


def reason(r):
    assert isinstance(r, Rejected)
    return r.reason


def test_accepts_good_fact_and_recalls_it():
    g, svc, _ = make()
    r = g.propose("r1", "Takes her tea with two sugars", tags=["tea"])
    assert isinstance(r, Accepted)
    assert [f.id for f in svc.recall("r1", "tea")] == [r.fact.id]


@pytest.mark.parametrize("text,ok", [("a" * 7, False), ("abcdefgh", True), ("   short  ", False)])
def test_min_length_boundary(text, ok):
    g, _, _ = make()
    assert isinstance(g.propose("r1", text), Accepted) is ok


def test_max_length_boundary():
    g, _, _ = make()
    assert isinstance(g.propose("r1", "x" * 280), Accepted)
    assert reason(g.propose("r1", "y" * 281)) == "too_long"


def test_exact_duplicate_rejected():
    g, _, _ = make()
    g.propose("r1", "Loves gardening in spring")
    assert reason(g.propose("r1", "Loves gardening in spring")) == "duplicate"


def test_near_duplicate_rejected_but_other_resident_ok():
    g, _, _ = make()
    g.propose("r1", "Loves gardening in spring")
    assert reason(g.propose("r1", "loves GARDENING in the spring!")) == "duplicate"
    assert isinstance(g.propose("r2", "Loves gardening in spring"), Accepted)


def test_different_fact_not_duplicate():
    g, _, _ = make()
    g.propose("r1", "Loves gardening in spring")
    assert isinstance(g.propose("r1", "Grandson Tom visits on Sundays"), Accepted)


@pytest.mark.parametrize(
    "text",
    [
        "She was diagnosed with diabetes last year",
        "Doctor prescribed warfarin",
        "Take a double dose in the morning",
        "Gets 50 mg of aspirin",
        "You have pneumonia",
    ],
)
def test_clinical_claims_rejected_even_from_staff(text):
    g, svc, _ = make()
    assert reason(g.propose("r1", text)) == "clinical_claim"
    assert reason(g.propose("r1", text, source="staff")) == "clinical_claim"
    assert svc.recall("r1", text) == []


def test_low_confidence_conversation_is_pending_not_stored():
    g, svc, _ = make()
    r = g.propose("r1", "Maybe likes jazz music", confidence=0.59)
    assert reason(r) == "pending_review"
    assert svc.recall("r1", "jazz") == []
    assert [p.text for p in g.pending("r1")] == ["Maybe likes jazz music"]
    assert g.pending("r2") == []


def test_confidence_boundary_accepted():
    g, _, _ = make()
    assert isinstance(g.propose("r1", "Likes jazz music", confidence=0.6), Accepted)


def test_approve_stores_and_clears_pending():
    g, svc, _ = make()
    g.propose("r1", "Maybe likes jazz music", tags=["music"], confidence=0.2)
    pid = g.pending("r1")[0].id
    r = g.approve(pid)
    assert isinstance(r, Accepted)
    assert [f.id for f in svc.recall("r1", "jazz")] == [r.fact.id]
    assert g.pending("r1") == []


def test_reject_discards_pending():
    g, svc, _ = make()
    g.propose("r1", "Maybe likes jazz music", confidence=0.2)
    g.reject(g.pending("r1")[0].id)
    assert g.pending("r1") == []
    assert svc.recall("r1", "jazz") == []


def test_unknown_pending_id_raises():
    g, _, _ = make()
    with pytest.raises(KeyError):
        g.approve("nope")


def test_staff_skips_confidence_rule():
    g, _, _ = make()
    assert isinstance(
        g.propose("r1", "Prefers the window seat", source="staff", confidence=0.1), Accepted
    )
    assert g.pending("r1") == []


def test_forget_removes_only_that_fact_and_recall_never_returns_it():
    g, svc, _ = make()
    a = g.propose("r1", "Takes tea with sugar")
    b = g.propose("r1", "Grandson visits Sundays")
    c = g.propose("r2", "Takes tea black")
    assert g.forget("r1", a.fact.id) is True
    assert svc.recall("r1", "tea sugar") == []
    assert [f.id for f in svc.recall("r1", "grandson")] == [b.fact.id]
    assert [f.id for f in svc.recall("r2", "tea")] == [c.fact.id]


def test_forget_wrong_resident_or_unknown_is_noop():
    g, svc, _ = make()
    c = g.propose("r2", "Takes tea black")
    assert g.forget("r1", c.fact.id) is False
    assert g.forget("r1", "zzz") is False
    assert len(svc.recall("r2", "tea")) == 1


def test_forget_all_leaves_other_residents_and_clears_pending():
    g, svc, _ = make()
    g.propose("r1", "Takes tea with sugar")
    g.propose("r1", "Maybe likes jazz", confidence=0.1)
    g.propose("r2", "Takes tea black")
    assert g.forget_all("r1") == 1
    assert svc.recall("r1", "tea") == []
    assert g.pending("r1") == []
    assert len(svc.recall("r2", "tea")) == 1


def test_forgotten_fact_can_be_re_added():
    g, _, _ = make()
    a = g.propose("r1", "Takes tea with sugar")
    g.forget("r1", a.fact.id)
    assert isinstance(g.propose("r1", "Takes tea with sugar"), Accepted)


def test_approve_or_reject_for_another_resident_is_refused():
    g, _, _ = make()
    g.propose("r1", "Has a grandson named Theo", confidence=0.2)
    pid = g.pending("r1")[0].id
    with pytest.raises(KeyError):
        g.approve(pid, resident_id="r2")
    with pytest.raises(KeyError):
        g.reject(pid, resident_id="r2")
    assert len(g.pending("r1")) == 1
