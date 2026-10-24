from bellhop.adapters.local_memory import LocalMemoryIndex
from bellhop.services.memory_service import MemoryService


def make(clock, ids) -> MemoryService:
    return MemoryService(LocalMemoryIndex(), clock, ids)


def test_remember_stores_fact_with_generated_id_and_time(clock, ids):
    svc = make(clock, ids)
    fact = svc.remember("r1", "Takes tea with two sugars", tags=["tea"])
    assert fact.id == "fact1"
    assert fact.created_at == clock.now()
    assert fact.tags == ["tea"]
    assert svc.recall("r1", "some tea") == [fact]


def test_recall_respects_k_and_resident(clock, ids):
    svc = make(clock, ids)
    for n in range(4):
        svc.remember("r1", f"likes tea {n}")
        clock.advance(minutes=1)
    svc.remember("r2", "likes tea")
    assert len(svc.recall("r1", "tea", k=2)) == 2
    assert all(f.resident_id == "r1" for f in svc.recall("r1", "tea", k=10))


def test_prompt_context_is_bulleted_facts(clock, ids):
    svc = make(clock, ids)
    svc.remember("r1", "Takes tea with two sugars", tags=["tea"])
    svc.remember("r1", "Grandson Tom visits Sundays")
    assert svc.prompt_context("r1", "tea") == "- Takes tea with two sugars"


def test_prompt_context_is_empty_string_when_nothing_recalled(clock, ids):
    assert make(clock, ids).prompt_context("r1", "tea") == ""
