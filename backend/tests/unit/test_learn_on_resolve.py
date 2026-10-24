from bellhop.adapters.event_bus import InMemoryEventBus
from bellhop.adapters.memory_store import InMemoryStore
from bellhop.domain import Call, Resident
from bellhop.domain.events import CallResolved
from bellhop.services.learn_on_resolve import LearnOnResolve


class FakeLearner:
    def __init__(self, fail=False):
        self.runs = []
        self.fail = fail

    def learn(self, resident_id, transcript, resident_name=None, known_facts=(), call_id=None):
        if self.fail:
            raise RuntimeError("model down")
        self.runs.append((resident_id, [t.text for t in transcript], resident_name))


class FakeMemory:
    def recall(self, resident_id, utterance, k=3):
        return []


def env(clock, resident_id="res1", turns=(("resident", "I love gardening"),), fail=False):
    store, bus, learner = InMemoryStore(), InMemoryEventBus(), FakeLearner(fail)
    store.residents.save(Resident(id="res1", name="Ada Lovelace", room="12"))
    call = Call(id="c1", room="12", resident_id=resident_id, created_at=clock.now())
    for speaker, text in turns:
        call.add_turn(speaker, text, clock.now())
    store.calls.save(call)
    LearnOnResolve(store.calls, store.residents, FakeMemory(), learner, bus, background=False)
    return bus, learner


def test_a_resolved_call_is_learned_from(clock):
    bus, learner = env(clock)
    bus.publish(CallResolved(call_id="c1", by_robot=True))
    assert learner.runs == [("res1", ["I love gardening"], "Ada Lovelace")]


def test_a_call_with_no_known_resident_is_skipped(clock):
    bus, learner = env(clock, resident_id=None)
    bus.publish(CallResolved(call_id="c1", by_robot=True))
    assert learner.runs == []


def test_a_call_where_the_resident_never_spoke_is_skipped(clock):
    bus, learner = env(clock, turns=(("robot", "Hello, how can I help?"),))
    bus.publish(CallResolved(call_id="c1", by_robot=True))
    assert learner.runs == []


def test_an_unknown_call_is_ignored(clock):
    bus, learner = env(clock)
    bus.publish(CallResolved(call_id="nope", by_robot=True))
    assert learner.runs == []


def test_a_learner_failure_never_propagates(clock):
    bus, _ = env(clock, fail=True)
    bus.publish(CallResolved(call_id="c1", by_robot=True))  # must not raise
