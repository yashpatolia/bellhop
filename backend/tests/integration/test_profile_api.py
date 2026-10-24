"""Provenance on memory, history import, care history, medical history and note refine."""

import pytest
from fastapi.testclient import TestClient

from bellhop.api.app import create_app
from bellhop.container import Settings, build_container

R = "res_margaret"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(build_container(Settings(seed_demo=True))))


def test_memory_keeps_provenance_and_lists_every_fact(client):
    r = client.post(
        f"/residents/{R}/memory",
        json={
            "text": "Dislikes loud television",
            "tags": ["dislike"],
            "source": "conversation",
            "confidence": 0.8,
            "quote": "far too loud",
            "call_id": "call_1",
        },
    )
    assert r.status_code == 201
    fact = r.json()
    assert (fact["quote"], fact["call_id"], fact["times_seen"]) == ("far too loud", "call_1", 1)
    facts = client.get(f"/residents/{R}/memory/all").json()
    assert "Dislikes loud television" in [f["text"] for f in facts]
    assert all("times_seen" in f and "last_confirmed" in f for f in facts)


def test_hearing_a_fact_again_counts_it(client):
    body = {"text": "Likes gardening in spring", "source": "conversation", "confidence": 0.9}
    assert client.post(f"/residents/{R}/memory", json=body).status_code == 201
    assert client.post(f"/residents/{R}/memory", json=body).status_code == 422  # duplicate
    [fact] = [
        f for f in client.get(f"/residents/{R}/memory/all").json() if "gardening" in f["text"]
    ]
    assert fact["times_seen"] == 2


def test_pending_fact_keeps_its_quote_through_review(client):
    client.post(
        f"/residents/{R}/memory",
        json={"text": "Hips ache after lunch", "confidence": 0.4, "quote": "my hips ache"},
    )
    [pending] = client.get(f"/residents/{R}/memory/pending").json()
    assert pending["quote"] == "my hips ache"
    approved = client.post(f"/residents/{R}/memory/pending/{pending['id']}/approve").json()
    assert approved["quote"] == "my hips ache"


def _import(client, **over):
    body = {
        "room": "12",
        "resident_id": R,
        "urgency": 1,
        "category": "chat",
        "summary": "Wanted company.",
        "robot_id": "robot_1",
        "created_at": "2026-10-20T10:00:00Z",
        "first_response_at": "2026-10-20T10:01:00Z",
        "resolved_at": "2026-10-20T10:06:00Z",
        "transcript": [
            {"speaker": "resident", "text": "Could we talk?", "at": "2026-10-20T10:01:30Z"},
            {"speaker": "robot", "text": "Of course.", "at": "2026-10-20T10:01:40Z"},
        ],
    }
    body.update(over)
    return client.post("/calls/import", json=body)


def test_import_stores_a_finished_call_with_its_original_times(client):
    r = _import(client)
    assert r.status_code == 201
    call = r.json()
    assert call["status"] == "resolved"
    assert call["created_at"].startswith("2026-10-20T10:00:00")
    assert call["resolved_by_robot"] is True
    assert [t["speaker"] for t in call["transcript"]] == ["resident", "robot"]
    assert client.get(f"/calls/{call['id']}").json()["resident_id"] == R


def test_import_counts_in_metrics_but_raises_no_alert(client):
    _import(client)
    _import(client, urgency=3, category="pain", by_robot=False)
    m = client.get("/metrics").json()
    assert m["resolved_without_nurse"] == 1
    assert client.get("/alerts").json() == []


def test_import_rejects_a_call_that_ends_before_it_starts(client):
    assert _import(client, resolved_at="2026-10-20T09:00:00Z").status_code == 422


def test_import_rejects_an_unknown_resident(client):
    assert _import(client, resident_id="nobody").status_code == 404


def test_resolving_a_call_records_who_resolved_it(client):
    call = client.post("/calls", json={"room": "12"}).json()
    client.post(f"/calls/{call['id']}/in-visit")
    client.post(f"/calls/{call['id']}/resolve", json={"by_robot": True})
    assert client.get(f"/calls/{call['id']}").json()["resolved_by_robot"] is True


def test_care_entries_can_be_dated_and_listed(client):
    for day, pain in (("2026-10-20T09:00:00Z", 2), ("2026-10-21T09:00:00Z", 3)):
        r = client.post(f"/residents/{R}/care", json={"kind": "pain", "value": pain, "at": day})
        assert r.status_code == 201
    entries = client.get(f"/residents/{R}/care/history", params={"days": 90, "kind": "pain"}).json()
    assert [e["value"] for e in entries] == [2, 3]
    assert entries[0]["at"].startswith("2026-10-20")


def test_medical_history_round_trip(client):
    assert client.get(f"/residents/{R}/medical").json()["conditions"] == []
    put = client.put(
        f"/residents/{R}/medical",
        json={
            "conditions": [{"name": "High blood pressure", "since": "2015"}],
            "allergies": ["Penicillin"],
            "medicines": ["Amlodipine"],
            "mobility": "Walks with a frame",
            "diet": "Regular",
            "reviewed_by": "Nurse Okoro",
        },
    )
    assert put.status_code == 200
    got = client.get(f"/residents/{R}/medical").json()
    assert got["conditions"][0] == {"name": "High blood pressure", "since": "2015", "note": None}
    assert got["reviewed_by"] == "Nurse Okoro"


def test_adding_medical_entries_follows_the_staff_rules(client):
    add = lambda **b: client.post(f"/residents/{R}/medical/entries", json=b)  # noqa: E731
    assert add(category="allergy", text="Penicillin").status_code == 201
    assert add(category="allergy", text="penicillin").json()["allergies"] == ["Penicillin"]
    assert add(category="medicine", text="Metformin").json()["medicines"] == ["Metformin"]
    assert (
        add(category="condition", text="COPD", since="2018").json()["conditions"][0]["since"]
        == "2018"
    )
    done = add(category="diet", text="Soft food")
    assert done.json()["diet"] == "Soft food"
    assert done.json()["last_review"] is not None
    assert add(category="like", text="Likes tea").status_code == 422


def test_refine_tidies_without_saving(client):
    r = client.post(
        f"/residents/{R}/notes/refine", json={"category": "condition", "text": "htn since 2015"}
    )
    assert r.status_code == 200
    out = r.json()
    assert (out["text"], out["since"]) == ("High blood pressure", "2015")
    assert client.get(f"/residents/{R}/medical").json()["conditions"] == []


def test_refine_rejects_an_empty_note(client):
    r = client.post(f"/residents/{R}/notes/refine", json={"category": "like", "text": "   "})
    assert r.status_code == 422


def test_a_dated_fact_keeps_its_dates_and_repeats_move_last_confirmed(client):
    body = {
        "text": "Plays chess, prefers white",
        "source": "resident",
        "at": "2026-10-01T10:00:00Z",
    }
    assert client.post(f"/residents/{R}/memory", json=body).status_code == 201
    client.post(f"/residents/{R}/memory", json={**body, "at": "2026-10-20T10:00:00Z"})
    [fact] = [f for f in client.get(f"/residents/{R}/memory/all").json() if "chess" in f["text"]]
    assert fact["created_at"].startswith("2026-10-01")
    assert fact["last_confirmed"].startswith("2026-10-20")
    assert fact["times_seen"] == 2
