import httpx
import pytest

from bellhop.fetchai.client import BellhopApi

pytest.importorskip("uagents")

from bellhop.fetchai.agent import UNREACHABLE, build_agent, reply_for  # noqa: E402


def make_api(handler):
    return BellhopApi("http://t", transport=httpx.MockTransport(handler))


def test_reply_for_backend_down_is_friendly():
    def boom(req):
        raise httpx.ConnectError("down")

    assert reply_for("any emergencies", make_api(boom)) == UNREACHABLE


def test_reply_for_answers():
    def ok(req):
        return httpx.Response(200, json={} if req.url.path == "/metrics" else [])

    assert "room" in reply_for("hello", make_api(ok)).lower()


def test_build_agent_requires_seed(monkeypatch):
    monkeypatch.delenv("BELLHOP_AGENT_SEED", raising=False)
    with pytest.raises(RuntimeError):
        build_agent()
