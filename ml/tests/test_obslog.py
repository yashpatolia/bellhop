import json

import httpx
import pytest

from rover import obslog
from rover.backend import Backend


@pytest.fixture
def log_path(tmp_path):
    path = tmp_path / "x" / "{component}.jsonl"
    yield path
    obslog.configure("rover", path="")  # back to off


def lines(tmp_path, name):
    text = (tmp_path / "x" / f"{name}.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def test_off_without_path(monkeypatch):
    monkeypatch.delenv("ROVER_LOG", raising=False)
    assert obslog.configure("speech") is False
    obslog.event("anything", call_id="c1")  # must not raise


def test_writes_one_json_line_per_event_and_flushes(tmp_path, log_path):
    assert obslog.configure("speech", path=log_path)
    obslog.event("visit.start", call_id="c1", room="12", skipped=None)
    # read while the handler is still open: the line must already be on disk
    (row,) = lines(tmp_path, "speech")
    assert row["event"] == "visit.start"
    assert row["component"] == "speech"
    assert row["call_id"] == "c1" and row["room"] == "12"
    assert "skipped" not in row
    assert isinstance(row["t"], float) and isinstance(row["pid"], int)


def test_env_path_is_used(tmp_path, monkeypatch, log_path):
    monkeypatch.setenv("ROVER_LOG", str(log_path))
    assert obslog.configure("drive")
    obslog.event("drive.go_to", room="12")
    assert lines(tmp_path, "drive")[0]["room"] == "12"


def test_secrets_never_reach_the_log(tmp_path, monkeypatch, log_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-supersecretvalue")
    obslog.configure("speech", path=log_path)
    obslog.event(
        "x",
        api_key="whatever",
        headers={"X-API-Key": "abc", "ok": "fine"},
        note="calling with sk-ant-supersecretvalue now",
    )
    raw = (tmp_path / "x" / "speech.jsonl").read_text(encoding="utf-8")
    assert "supersecret" not in raw and "whatever" not in raw and '"abc"' not in raw
    row = json.loads(raw)
    assert row["headers"]["ok"] == "fine"
    assert row["api_key"] == obslog.MASK


def test_unwritable_path_turns_logging_off(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert obslog.configure("speech", path=blocker / "sub" / "a.jsonl") is False
    obslog.event("still fine")


def test_backend_calls_are_logged_with_call_id_status_latency(tmp_path, log_path):
    obslog.configure("speech", path=log_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/in-visit"):
            return httpx.Response(200, json={"id": "call_7", "status": "in_visit"})
        return httpx.Response(503, text="down")

    backend = Backend("http://b", api_key="topsecret-key", transport=httpx.MockTransport(handler))
    assert backend.in_visit("call_7")
    backend.add_turn("call_7", "resident", "hello")
    rows = lines(tmp_path, "speech")
    first, second = rows
    assert first["event"] == "backend.request"
    assert first["call_id"] == "call_7" and first["status"] == 200
    assert first["method"] == "POST" and first["path"] == "/calls/call_7/in-visit"
    assert first["latency_ms"] >= 0
    assert second["status"] == 503
    assert "topsecret-key" not in json.dumps(rows)


def test_backend_transport_error_is_logged(tmp_path, log_path):
    obslog.configure("speech", path=log_path)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    backend = Backend("http://b", api_key="", transport=httpx.MockTransport(handler))
    assert backend.calls() == []
    (row,) = lines(tmp_path, "speech")
    assert row["event"] == "backend.request"
    assert row["error"] == "ConnectError" and "status" not in row


def test_score_logs_urgency_and_confidence(tmp_path, log_path):
    obslog.configure("speech", path=log_path)
    backend = Backend(
        "http://b",
        api_key="",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
    )
    backend.score("call_1", 3, "pain", "hurts", 0.8)
    rows = lines(tmp_path, "speech")
    score = next(r for r in rows if r["event"] == "backend.score")
    assert (score["call_id"], score["urgency"], score["confidence"]) == ("call_1", 3, 0.8)
