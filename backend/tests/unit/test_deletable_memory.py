from datetime import UTC, datetime

from bellhop.adapters.deletable_memory import DeletableLocalMemoryIndex
from bellhop.domain import MemoryFact

T0 = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)


def fact(i, text, rid="r1"):
    return MemoryFact(id=i, resident_id=rid, text=text, tags=[], created_at=T0)


def idx():
    d = DeletableLocalMemoryIndex()
    d.add(fact("a", "likes tea with sugar"))
    d.add(fact("b", "grandson visits Sunday"))
    d.add(fact("c", "likes tea black", rid="r2"))
    return d


def test_facts_lists_resident_only():
    assert [f.id for f in idx().facts("r1")] == ["a", "b"]
    assert idx().facts("nobody") == []


def test_remove_drops_from_recall_and_listing():
    d = idx()
    assert d.remove("a") is True
    assert [f.id for f in d.facts("r1")] == ["b"]
    assert d.recall("r1", "tea sugar") == []


def test_remove_unknown_returns_false():
    assert idx().remove("zzz") is False


def test_remove_leaves_other_residents():
    d = idx()
    d.remove("a")
    assert [f.id for f in d.recall("r2", "tea")] == ["c"]


def test_remove_all_counts_and_isolates():
    d = idx()
    assert d.remove_all("r1") == 2
    assert d.facts("r1") == []
    assert d.recall("r1", "tea") == []
    assert len(d.facts("r2")) == 1
    assert d.remove_all("r1") == 0
