from datetime import UTC, datetime, timedelta
from time import perf_counter

from bellhop.adapters.local_memory import LocalMemoryIndex
from bellhop.domain import MemoryFact

T0 = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)


def fact(i: str, text: str, rid: str = "r1", tags: list[str] | None = None, age: int = 0):
    return MemoryFact(
        id=i, resident_id=rid, text=text, tags=tags or [], created_at=T0 + timedelta(minutes=age)
    )


def seeded() -> LocalMemoryIndex:
    idx = LocalMemoryIndex()
    idx.add(fact("f1", "Takes her tea with two sugars", tags=["tea", "preferences"]))
    idx.add(fact("f2", "Her grandson Tom visits on Sundays", tags=["family"]))
    idx.add(fact("f3", "Chronic hip pain after hip replacement in 2023", tags=["health"]))
    idx.add(fact("x1", "Takes his tea black with no sugar", rid="r2"))
    return idx


def top(idx: LocalMemoryIndex, utterance: str, rid: str = "r1", k: int = 3) -> list[str]:
    return [f.id for f in idx.recall(rid, utterance, k)]


def test_tea_request_recalls_the_two_sugars_fact():
    assert top(seeded(), "can I get some tea")[0] == "f1"


def test_grandson_question_recalls_grandson_fact():
    assert top(seeded(), "how is your grandson")[0] == "f2"


def test_hip_pain_recalls_history_fact():
    assert top(seeded(), "my hip has been aching since last night")[0] == "f3"


def test_plural_and_singular_match():
    assert top(seeded(), "any sugar please")[0] == "f1"


def test_never_returns_another_residents_facts():
    ids = top(seeded(), "tea with sugar", rid="r1")
    assert "x1" not in ids
    assert top(seeded(), "tea with sugar", rid="r2") == ["x1"]


def test_unknown_resident_returns_empty():
    assert top(seeded(), "tea", rid="nobody") == []


def test_k_is_respected():
    idx = LocalMemoryIndex()
    for n in range(5):
        idx.add(fact(f"f{n}", "likes tea", age=n))
    assert len(top(idx, "tea", k=2)) == 2


def test_no_overlap_returns_empty():
    assert top(seeded(), "the weather is lovely") == []


def test_stopword_only_utterance_returns_empty():
    assert top(seeded(), "can I get some of the") == []


def test_tag_match_outranks_plain_text_match():
    idx = LocalMemoryIndex()
    idx.add(fact("plain", "mentioned a walk once", age=5))
    idx.add(fact("tagged", "enjoys the garden", tags=["walk"], age=0))
    assert top(idx, "walk") == ["tagged", "plain"]


def test_equal_scores_prefer_most_recent_then_id():
    idx = LocalMemoryIndex()
    idx.add(fact("a", "likes tea", age=1))
    idx.add(fact("b", "likes tea", age=2))
    idx.add(fact("c", "likes tea", age=2))
    assert top(idx, "tea") == ["b", "c", "a"]


def test_more_overlap_ranks_higher():
    idx = LocalMemoryIndex()
    idx.add(fact("one", "likes tea", age=9))
    idx.add(fact("two", "likes tea with sugar", age=0))
    assert top(idx, "tea and sugar") == ["two", "one"]


def test_re_adding_same_id_replaces_fact():
    idx = LocalMemoryIndex()
    idx.add(fact("f", "likes tea"))
    idx.add(fact("f", "likes coffee"))
    assert top(idx, "tea") == []
    assert top(idx, "coffee") == ["f"]


def test_recall_with_a_thousand_facts_is_fast():
    idx = LocalMemoryIndex()
    for n in range(1000):
        idx.add(fact(f"f{n}", f"note {n} about topic{n % 50} and tea", age=n))
    start = perf_counter()
    result = idx.recall("r1", "can I get some tea", 3)
    assert perf_counter() - start < 0.05
    assert len(result) == 3
