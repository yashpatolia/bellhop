import pytest
from fastapi.testclient import TestClient

from bellhop.api.app import create_app
from bellhop.container import Settings, build_container

R = "/residents/res_margaret/memory"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(build_container(Settings())))


def test_accepted_fact_is_201_and_recalled(client):
    r = client.post(R, json={"text": "Loves jasmine tea in the afternoon"})
    assert r.status_code == 201
    assert r.json()["text"] == "Loves jasmine tea in the afternoon"
    assert client.get(R, params={"q": "jasmine tea"}).json()[0]["id"] == r.json()["id"]


def test_clinical_claim_rejected_422_with_reason(client):
    r = client.post(R, json={"text": "She was diagnosed with dementia last year"})
    assert r.status_code == 422
    assert "clinical_claim" in r.json()["detail"]
    assert client.get(R, params={"q": "dementia"}).json() == []


def test_duplicate_rejected(client):
    client.post(R, json={"text": "Loves jasmine tea in the afternoon"})
    r = client.post(R, json={"text": "Loves jasmine tea in the afternoon"})
    assert r.status_code == 422 and "duplicate" in r.json()["detail"]


def test_low_confidence_queued_202_then_approved(client):
    r = client.post(R, json={"text": "Has a grandson named Theo", "confidence": 0.3})
    assert r.status_code == 202
    assert "pending_review" in str(r.json())
    assert client.get(R, params={"q": "grandson Theo"}).json() == []
    pending = client.get(f"{R}/pending").json()
    assert len(pending) == 1 and pending[0]["text"] == "Has a grandson named Theo"
    ok = client.post(f"{R}/pending/{pending[0]['id']}/approve")
    assert ok.status_code == 200
    assert client.get(R, params={"q": "grandson Theo"}).json()[0]["text"].startswith("Has a")
    assert client.get(f"{R}/pending").json() == []


def test_pending_reject(client):
    client.post(R, json={"text": "Has a grandson named Theo", "confidence": 0.3})
    pid = client.get(f"{R}/pending").json()[0]["id"]
    assert client.post(f"{R}/pending/{pid}/reject").status_code == 200
    assert client.get(f"{R}/pending").json() == []
    assert client.get(R, params={"q": "grandson Theo"}).json() == []


def test_unknown_pending_is_404(client):
    assert client.post(f"{R}/pending/nope/approve").status_code == 404
    assert client.post(f"{R}/pending/nope/reject").status_code == 404


def test_forgotten_fact_no_longer_recalled(client):
    fid = client.post(R, json={"text": "Loves jasmine tea in the afternoon"}).json()["id"]
    assert client.delete(f"{R}/{fid}").status_code == 204
    assert client.get(R, params={"q": "jasmine tea"}).json() == []
    assert client.delete(f"{R}/{fid}").status_code == 404


def test_forget_all(client):
    client.post(R, json={"text": "Loves jasmine tea in the afternoon"})
    client.post(R, json={"text": "Enjoys crossword puzzles after lunch"})
    r = client.delete(R)
    assert r.status_code == 200 and r.json() == {"removed": 2}
    assert client.get(R, params={"q": "tea crossword"}).json() == []


def test_pending_of_another_resident_is_404(client):
    client.post(R, json={"text": "Has a grandson named Theo", "confidence": 0.3})
    pid = client.get(f"{R}/pending").json()[0]["id"]
    other = "/residents/res_other/memory"
    assert client.post(f"{other}/pending/{pid}/approve").status_code == 404
