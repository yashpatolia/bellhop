import json
from pathlib import Path

import pytest

from bellhop.adapters.care_store import InMemoryCareStore
from bellhop.adapters.local_memory import LocalMemoryIndex
from bellhop.adapters.memory_store import InMemoryStore
from bellhop.container import Settings, build_container
from bellhop.domain import CallStatus, Urgency
from bellhop.scenarios import Scenario, ScenarioError, apply_scenario, load_scenario
from bellhop.seed import seed_demo
from bellhop.services.memory_service import MemoryService

SCENARIOS = Path(__file__).resolve().parents[2] / "scenarios"


def build(clock, ids, source):
    store, care = InMemoryStore(), InMemoryCareStore()
    memory = MemoryService(LocalMemoryIndex(), clock, ids)
    apply_scenario(load_scenario(source), store, memory, care)
    return store, memory, care


def test_demo_json_matches_old_seed(clock, ids):
    store, memory, _ = build(clock, ids, SCENARIOS / "demo.json")
    margaret = store.residents.get("res_margaret")
    assert (margaret.room, margaret.risk_flags, margaret.birth_year) == ("12", {"falls"}, 1938)
    assert store.residents.get("res_arthur").room == "14"
    assert {n.id for n in store.nurses.list_all()} == {"nurse_priya", "nurse_sam"}
    (robot,) = store.robots.list_all()
    assert (robot.id, robot.room) == ("robot_1", "lobby")
    assert "two sugars" in memory.recall("res_margaret", "can I get a cup of tea")[0].text
    assert "hip" in memory.recall("res_margaret", "my hip has been aching")[0].text
    assert "Wednesdays" in memory.recall("res_arthur", "daughter phones")[0].text


def test_seed_demo_wrapper_equals_scenario(clock, ids):
    store, memory = InMemoryStore(), MemoryService(LocalMemoryIndex(), clock, ids)
    seed_demo(store, memory)
    via_scenario, _, _ = build(clock, ids, SCENARIOS / "demo.json")
    for repo in ("residents", "nurses", "robots"):
        mine = sorted(getattr(store, repo).list_all(), key=lambda x: x.id)
        theirs = sorted(getattr(via_scenario, repo).list_all(), key=lambda x: x.id)
        assert mine == theirs


def test_preferences_applied(clock, ids):
    source = {
        "residents": [
            {"id": "r1", "name": "Ada", "room": "1", "preferences": {"hard_of_hearing": True}}
        ]
    }
    _, _, care = build(clock, ids, source)
    assert care.preferences.get("r1").hard_of_hearing is True


def test_embedded_facts_are_remembered(clock, ids):
    source = {
        "residents": [
            {
                "id": "r1",
                "name": "Ada",
                "room": "1",
                "facts": [{"text": "Loves marmalade toast", "tags": ["food"]}],
            }
        ]
    }
    _, memory, _ = build(clock, ids, source)
    assert "marmalade" in memory.recall("r1", "marmalade toast")[0].text


def test_empty_scenario_file_yields_empty_system():
    app = build_container(Settings(seed_file=str(SCENARIOS / "empty.json")))
    assert app.store.residents.list_all() == []
    assert app.store.nurses.list_all() == []
    assert app.store.robots.list_all() == []
    call = app.call_service.raise_call("12")
    app.call_service.score(call.id, Urgency.NURSE_SOON, "pain")
    stored = app.store.calls.get(call.id)
    assert stored.resident_id is None
    assert stored.status is CallStatus.ESCALATED


def test_scenario_model_and_dict_input():
    assert isinstance(load_scenario({}), Scenario)
    assert load_scenario({"nurses": [{"id": "n", "name": "N"}]}).nurses[0].on_shift is True


def write(tmp_path, data, raw=None):
    p = tmp_path / "s.json"
    p.write_text(raw if raw is not None else json.dumps(data))
    return p


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"residentz": []}, "residentz"),
        ({"residents": [{"id": "a", "name": "A", "room": "1", "colour": "x"}]}, "colour"),
        (
            {
                "residents": [
                    {"id": "a", "name": "A", "room": "1"},
                    {"id": "a", "name": "B", "room": "2"},
                ]
            },
            "duplicate resident id",
        ),
        (
            {
                "residents": [
                    {"id": "a", "name": "A", "room": "1"},
                    {"id": "b", "name": "B", "room": "1"},
                ]
            },
            "room 1",
        ),
        ({"nurses": [{"id": "n", "name": "N"}, {"id": "n", "name": "M"}]}, "duplicate nurse id"),
        ({"robots": [{"id": "r"}, {"id": "r"}]}, "duplicate robot id"),
        ({"residents": [{"id": "a", "name": "", "room": "1"}]}, "name"),
        ({"robots": [{"id": "r", "battery": 2}]}, "battery"),
        (
            {"residents": [{"id": "a", "name": "A", "room": "1", "preferences": {"x": 1}}]},
            "preferences",
        ),
    ],
)
def test_invalid_scenarios_rejected(data, message):
    with pytest.raises(ScenarioError, match=message):
        load_scenario(data)


def test_missing_and_malformed_files(tmp_path):
    with pytest.raises(ScenarioError, match="not found"):
        load_scenario(tmp_path / "nope.json")
    with pytest.raises(ScenarioError, match="not valid JSON"):
        load_scenario(write(tmp_path, None, raw="{oops"))
    with pytest.raises(ScenarioError, match="object"):
        load_scenario(write(tmp_path, [1]))


def test_scenario_error_is_value_error():
    assert issubclass(ScenarioError, ValueError)


def test_container_seed_file_beats_seed_demo(tmp_path):
    p = write(tmp_path, {"residents": [{"id": "x", "name": "X", "room": "9"}]})
    app = build_container(Settings(seed_demo=True, seed_file=str(p)))
    assert [r.id for r in app.store.residents.list_all()] == ["x"]


def test_container_bad_seed_file_fails_loudly(tmp_path):
    with pytest.raises(ScenarioError):
        build_container(Settings(seed_file=str(tmp_path / "missing.json")))


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("BELLHOP_SEED_FILE", "/x/y.json")
    assert Settings.from_env().seed_file == "/x/y.json"
    monkeypatch.delenv("BELLHOP_SEED_FILE")
    assert Settings.from_env().seed_file is None


def test_container_exposes_admin():
    app = build_container(Settings())
    r = app.admin.create_resident(None, "Ada", "5")
    assert app.call_service.raise_call("5").resident_id == r.id
