from datetime import UTC, datetime

from bellhop.adapters.deletable_memory import DeletableLocalMemoryIndex
from bellhop.adapters.local_memory import LocalMemoryIndex
from bellhop.adapters.moss_memory import MossMemoryIndex
from bellhop.domain import MemoryFact


def fact(i: str, text: str, rid: str = "r1") -> MemoryFact:
    return MemoryFact(id=i, resident_id=rid, text=text, created_at=datetime(2026, 1, 1, tzinfo=UTC))


def test_without_credentials_it_uses_the_fallback():
    idx = MossMemoryIndex(LocalMemoryIndex())
    idx.add(fact("f1", "Takes tea with two sugars"))
    assert [f.id for f in idx.recall("r1", "some tea")] == ["f1"]


def test_missing_sdk_falls_back_even_with_credentials():
    idx = MossMemoryIndex(LocalMemoryIndex(), project_id="p", project_key="k")
    idx.add(fact("f1", "Takes tea with two sugars"))
    assert [f.id for f in idx.recall("r1", "some tea")] == ["f1"]


class Exploding(MossMemoryIndex):
    def _search(self, resident_id: str, utterance: str, k: int) -> list[str]:
        raise RuntimeError("moss down")


def test_failing_moss_search_falls_back():
    idx = Exploding(LocalMemoryIndex(), project_id="p", project_key="k")
    idx.add(fact("f1", "Takes tea with two sugars"))
    assert [f.id for f in idx.recall("r1", "some tea")] == ["f1"]


class Fake(MossMemoryIndex):
    def __init__(self, ids: list[str]) -> None:
        super().__init__(LocalMemoryIndex(), project_id="p", project_key="k")
        self.ids = ids

    def _search(self, resident_id: str, utterance: str, k: int) -> list[str]:
        return self.ids


def test_moss_ids_are_resolved_to_facts_of_that_resident_only():
    idx = Fake(["f2", "x1", "missing"])
    idx.add(fact("f1", "a"))
    idx.add(fact("f2", "b"))
    idx.add(fact("x1", "c", rid="r2"))
    assert [f.id for f in idx.recall("r1", "anything")] == ["f2"]


def test_empty_moss_result_falls_back_to_lexical():
    idx = Fake([])
    idx.add(fact("f1", "Takes tea with two sugars"))
    assert [f.id for f in idx.recall("r1", "some tea")] == ["f1"]


def test_moss_resolves_a_fact_hydrated_before_the_wrapper_starts():
    """A persisted fact is in the local source of truth, not Moss's process-local cache."""

    local = DeletableLocalMemoryIndex()
    # ``PersistentMemoryIndex.load`` deliberately calls the base add to avoid writing a
    # loaded row back to SpacetimeDB.  Reproduce that startup path here.
    LocalMemoryIndex.add(local, fact("f1", "Takes tea with two sugars"))

    class Hydrated(Fake):
        def __init__(self) -> None:
            MossMemoryIndex.__init__(self, local, project_id="p", project_key="k")
            self.ids = ["f1"]

    assert [f.id for f in Hydrated().recall("r1", "unrelated wording")] == ["f1"]


def test_empty_briefing_never_calls_the_optional_remote_index():
    class NoNetwork(Fake):
        def _search(self, resident_id: str, utterance: str, k: int) -> list[str]:
            raise AssertionError("briefings must be served locally")

    idx = NoNetwork(["f1"])
    idx.add(fact("f1", "Takes tea with two sugars"))
    assert [f.id for f in idx.recall("r1", "")] == ["f1"]
