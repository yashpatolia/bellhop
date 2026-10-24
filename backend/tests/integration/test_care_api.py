from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from bellhop.api.app import create_app
from bellhop.container import Settings, build_container
from bellhop.domain.care import CareEntry, EntryKind

RES = "/residents/res_margaret"


@pytest.fixture
def container():
    return build_container(Settings(seed_demo=True))


@pytest.fixture
def client(container) -> TestClient:
    return TestClient(create_app(container))


def _care(client, kind, **kw):
    return client.post(f"{RES}/care", json={"kind": kind, **kw})


def test_record_and_summary(client):
    assert _care(client, "mood", value=4).status_code == 201
    assert _care(client, "drink", note="tea").status_code == 201
    _care(client, "drink")
    _care(client, "repeat_question")
    s = client.get(f"{RES}/care/summary").json()
    assert s == {
        "pain_streak_days": 0,
        "mood_lower_than_usual": False,
        "drinks_today": 2,
        "repeat_questions_today": 1,
    }


def test_mood_and_pain_need_a_value(client):
    assert _care(client, "mood").status_code == 422
    assert _care(client, "pain").status_code == 422
    assert _care(client, "mood", value=9).status_code == 422
    assert _care(client, "nonsense").status_code == 422


def test_unknown_resident_404(client):
    assert client.post("/residents/nobody/care", json={"kind": "drink"}).status_code == 404
    assert client.get("/residents/nobody/care/summary").status_code == 404
    assert client.get("/residents/nobody/preferences").status_code == 404
    assert client.get("/residents/nobody/postcard").status_code == 404


def test_three_days_of_pain_raises_open_flag_with_reason(client, container):
    now = container.clock.now()
    for back in (2, 1):
        container.care_store.entries.add(
            CareEntry(
                id=f"old{back}",
                resident_id="res_margaret",
                kind=EntryKind.PAIN,
                value=3,
                at=now - timedelta(days=back),
            )
        )
    assert _care(client, "pain", value=3).status_code == 201
    assert client.get(f"{RES}/care/summary").json()["pain_streak_days"] == 3
    flags = client.get("/flags", params={"resident_id": "res_margaret"}).json()
    assert len(flags) == 1
    assert flags[0]["type"] == "pain" and "3 days" in flags[0]["reason"]


def test_resolve_flag_and_filter(client, container):
    flag = container.care_signals.raise_flag("res_margaret", "distress", "seemed upset")
    assert len(client.get("/flags").json()) == 1
    r = client.post(f"/flags/{flag.id}/resolve")
    assert r.status_code == 200 and r.json()["resolved_at"] is not None
    assert client.get("/flags").json() == []
    assert len(client.get("/flags", params={"open_only": "false"}).json()) == 1
    assert client.post("/flags/nope/resolve").status_code == 404


def test_preferences_roundtrip_and_speech_settings(client):
    assert client.get(f"{RES}/preferences").json()["hard_of_hearing"] is False
    r = client.put(f"{RES}/preferences", json={"hard_of_hearing": True, "night_mode": True})
    assert r.status_code == 200
    assert client.get(f"{RES}/preferences").json()["night_mode"] is True
    assert client.get(f"{RES}/speech-settings").json() == {
        "rate": "slow",
        "volume": "loud",
        "captions": True,
        "tone": "calm",
    }
    assert client.put(f"{RES}/preferences", json={"quiet_mode": "maybe"}).status_code == 422


def test_family_messages_and_replies(client):
    assert client.post(f"{RES}/family/messages", json={"text": "Love you gran"}).status_code == 201
    assert client.post(f"{RES}/family/replies", json={"text": "Love you too"}).status_code == 201
    msgs = client.get(f"{RES}/family/messages").json()
    assert [m["direction"] for m in msgs] == ["to_resident", "from_resident"]
    assert client.post(f"{RES}/family/messages", json={"text": ""}).status_code == 422
    assert client.post("/residents/nobody/family/messages", json={"text": "hi"}).status_code == 404


def test_postcard_is_positive_and_never_mentions_pain(client):
    _care(client, "pain", value=4, note="pain in my knee")
    _care(client, "mood", value=5, note="enjoyed bingo")
    _care(client, "drink", note="tea")
    lines = client.get(f"{RES}/postcard").json()["lines"]
    assert "Enjoyed some tea" in lines
    assert "Was in good spirits" in lines
    assert not any("bingo" in line.lower() for line in lines)  # notes are never echoed
    assert not any("pain" in line.lower() or "knee" in line.lower() for line in lines)


def test_visit_note(client):
    call_id = client.post("/calls", json={"room": "12"}).json()["id"]
    _care(client, "mood", value=4, call_id=call_id)
    note = client.get(f"/calls/{call_id}/note").json()
    assert note["room"] == "12" and "mood good" in note["text"]
    assert client.get("/calls/nope/note").status_code == 404
