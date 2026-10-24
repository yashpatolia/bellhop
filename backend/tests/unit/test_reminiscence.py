from bellhop.adapters.local_content import LocalContentFeed
from bellhop.adapters.local_memory import LocalMemoryIndex
from bellhop.adapters.memory_store import InMemoryStore
from bellhop.domain import Resident
from bellhop.services.memory_service import MemoryService
from bellhop.services.reminiscence import ReminiscenceService


def make(clock, ids, birth_year=1940):
    store = InMemoryStore()
    store.residents.save(Resident(id="r1", name="Ada", room="12", birth_year=birth_year))
    store.residents.save(Resident(id="r2", name="Bo", room="13"))
    memory = MemoryService(LocalMemoryIndex(), clock, ids)
    return ReminiscenceService(LocalContentFeed(), memory, store.residents), memory


def test_resident_birth_year_is_optional():
    assert Resident(id="x", name="X", room="1").birth_year is None
    assert Resident(id="x", name="X", room="1", birth_year=1938).birth_year == 1938


def test_prompt_context_bulleted_and_limited(clock, ids):
    svc, _ = make(clock, ids)
    lines = svc.prompt_context("r1", k=3).splitlines()
    assert len(lines) == 3 and all(line.startswith("- ") for line in lines)


def test_prompt_context_empty_without_birth_year_or_resident(clock, ids):
    svc, _ = make(clock, ids)
    assert svc.prompt_context("r2") == ""
    assert svc.prompt_context("nobody") == ""


def test_ingest_stores_tagged_facts(clock, ids):
    svc, memory = make(clock, ids)
    facts = svc.ingest("r1")
    assert facts and all("reminiscence" in f.tags for f in facts)
    assert all(f.resident_id == "r1" for f in facts)
    assert memory.recall("r1", facts[0].text.split()[0], k=10)


def test_ingest_without_birth_year_is_noop(clock, ids):
    svc, _ = make(clock, ids)
    assert svc.ingest("r2") == []
