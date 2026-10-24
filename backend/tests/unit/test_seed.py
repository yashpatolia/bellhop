from bellhop.adapters.local_memory import LocalMemoryIndex
from bellhop.domain import Nurse, Resident, Robot
from bellhop.seed import seed_demo
from bellhop.services.memory_service import MemoryService


class FakeStore:
    """Facade like InMemoryStore: one repository per aggregate."""

    def __init__(self) -> None:
        self.saved: list[object] = []
        self.residents = self.nurses = self.robots = self

    def save(self, item: object) -> None:
        self.saved.append(item)

    def of(self, kind: type) -> list:
        return [s for s in self.saved if isinstance(s, kind)]


def run(clock, ids):
    store, memory = FakeStore(), MemoryService(LocalMemoryIndex(), clock, ids)
    seed_demo(store, memory)
    return store, memory


def test_seeds_residents_nurses_and_one_robot(clock, ids):
    store, _ = run(clock, ids)
    assert len(store.of(Resident)) >= 2
    assert len(store.of(Nurse)) >= 2
    assert len(store.of(Robot)) == 1


def test_demo_scenes_recall_the_right_facts(clock, ids):
    store, memory = run(clock, ids)
    margaret = store.of(Resident)[0]
    tea = memory.recall(margaret.id, "can I get a cup of tea and a chat")
    assert "two sugars" in tea[0].text
    assert "grandson" in memory.recall(margaret.id, "how is your grandson")[0].text
    assert "hip" in memory.recall(margaret.id, "my hip has been aching")[0].text


def test_residents_do_not_see_each_others_facts(clock, ids):
    store, memory = run(clock, ids)
    first, second = store.of(Resident)[:2]
    theirs = {f.id for f in memory.recall(second.id, "tea hip grandson", k=10)}
    mine = {f.id for f in memory.recall(first.id, "tea hip grandson", k=10)}
    assert not theirs & mine
