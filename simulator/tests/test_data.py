from bellhop_sim import data
from bellhop_sim.live import SCENES, pick_scenario
from bellhop_sim.seeding import pain_scale


def test_residents_have_unique_ids_and_rooms():
    people = data.residents()
    assert len({r["id"] for r in people}) == len(people)
    assert len({r["room"] for r in people}) == len(people)


def test_facts_use_the_kinds_and_sources_the_dashboard_knows():
    kinds = {"like", "dislike", "person", "routine", "health", "style", "event"}
    sources = {"resident", "staff", "family", "inferred"}
    for r in data.residents():
        for f in r["facts"]:
            assert f["kind"] in kinds and f["source"] in sources
            assert 0 <= f["confidence"] <= 1 and f["times_seen"] >= 1


def test_every_scenario_opens_with_the_resident_and_alternates():
    for s in data.scenarios():
        assert [who for who, _ in s.turns] == ["resident", "robot"] * 3
        assert 1 <= s.urgency <= 4


def test_the_busy_scene_only_names_real_residents_and_categories():
    ids = {r["id"] for r in data.residents()}
    cats = {s.category for s in data.scenarios()}
    for scene in SCENES.values():
        for category, resident_id, _ in scene:
            assert category in cats and resident_id in ids


def test_flags_map_to_backend_risk_flags_and_hearing_is_separate():
    margaret = next(r for r in data.residents() if r["id"] == "r101")
    assert data.risk_flags(margaret) == ["falls"]
    harold = next(r for r in data.residents() if r["id"] == "r102")
    assert data.risk_flags(harold) == [] and data.hard_of_hearing(harold)


def test_pain_is_converted_to_the_backend_one_to_five_scale():
    assert [pain_scale(v) for v in (0, 1, 2, 5, 10)] == [1, 1, 1, 2, 5]


def test_random_calls_follow_the_level_mix():
    import random

    rng = random.Random(1)
    levels = [pick_scenario(rng).urgency for _ in range(2000)]
    assert levels.count(1) > levels.count(2) > 0
    assert levels.count(4) < levels.count(3)
