import threading
from datetime import UTC, datetime

from bellhop.adapters.deletable_memory import DeletableLocalMemoryIndex
from bellhop.adapters.moss_memory import MossMemoryIndex
from bellhop.domain import MemoryFact
from bellhop.fetchai.answers import answer_question


def fact(i, text, rid="r1"):
    return MemoryFact(id=i, resident_id=rid, text=text, created_at=datetime(2026, 1, 1, tzinfo=UTC))


class StaleMoss(MossMemoryIndex):
    """Moss side still returns every id it ever saw, like the cloud copy would."""

    def __init__(self, local):
        super().__init__(local, project_id="p", project_key="k")
        self.seen: list[str] = []

    def _upsert(self, f):
        self.seen.append(f.id)

    def _search(self, resident_id, utterance, k):
        return list(self.seen)


def test_moss_remove_drops_fact_from_recall_even_if_moss_still_has_it():
    local = DeletableLocalMemoryIndex()
    idx = StaleMoss(local)
    idx.add(fact("f1", "likes tea"))
    idx.add(fact("f2", "likes jam"))
    assert idx.remove("f1") is True
    assert [f.id for f in idx.recall("r1", "tea")] == ["f2"]
    assert "f1" not in idx._facts


def test_moss_remove_all():
    idx = StaleMoss(DeletableLocalMemoryIndex())
    idx.add(fact("f1", "likes tea"))
    assert idx.remove_all("r1") == 1
    assert idx.recall("r1", "tea") == []


def test_removal_through_the_plain_local_index_also_hides_fact():
    # container wires MemoryGuard to the plain local index, not the Moss wrapper
    local = DeletableLocalMemoryIndex()
    idx = StaleMoss(local)
    idx.add(fact("f1", "likes tea"))
    local.remove("f1")
    assert idx.recall("r1", "tea") == []


def test_fallback_path_remove():
    idx = MossMemoryIndex(DeletableLocalMemoryIndex())
    idx.add(fact("f1", "likes tea"))
    assert idx.remove("f1") is True
    assert idx.recall("r1", "tea") == []
    assert idx.remove("f1") is False


def test_answers_never_include_transcript_or_summary_text():
    calls = [
        {
            "id": "c1",
            "room": "12",
            "urgency": 4,
            "status": "escalated",
            "created_at": "2026-10-23T09:00:00Z",
            "summary": "Mrs Smith SECRETSUMMARY fell",
            "transcript": [{"text": "SECRETTURN"}],
        }
    ]
    alerts = [{"id": "a1", "call_id": "c1", "level": 4, "message": "SECRETALERT Mrs Smith"}]
    for q in ("what happened in room 12", "any emergencies"):
        out = answer_question(q, calls, alerts, {})
        assert "SECRET" not in out and "Smith" not in out
        assert "12" in out and "emergency" in out.lower()


def test_is_allowed():
    from bellhop.fetchai.agent import is_allowed

    assert is_allowed("agent1abc", None)
    assert is_allowed("agent1abc", "")
    assert is_allowed("agent1abc", " agent1abc , agent1xyz ")
    assert not is_allowed("agent1evil", "agent1abc,agent1xyz")


def test_concurrent_score_and_resolve_is_consistent():
    from bellhop.adapters.memory_store import InMemoryStore
    from bellhop.domain import CallStatus, Urgency
    from bellhop.services.call_service import CallService

    class Ids:
        def __init__(self):
            self.n = 0

        def new_id(self, prefix):
            self.n += 1
            return f"{prefix}{self.n}"

    class Clock:
        def now(self):
            return datetime(2026, 1, 1, tzinfo=UTC)

    class Bus:
        def publish(self, e):
            pass

        def subscribe(self, *a, **k):
            pass

    store = InMemoryStore()
    svc = CallService(store.calls, store.residents, Bus(), Clock(), Ids(), store.nurses)
    errors: list[Exception] = []
    for _ in range(200):
        call = svc.raise_call("1")

        def a(cid=call.id):
            try:
                svc.score(cid, Urgency.EMERGENCY, "fall", "s")
                svc.add_turn(cid, "resident", "x")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def b(cid=call.id):
            try:
                svc.resolve(cid)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        ts = [threading.Thread(target=a), threading.Thread(target=b)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        final = store.calls.get(call.id)
        assert final.status == CallStatus.RESOLVED
    assert not errors, errors[:3]
