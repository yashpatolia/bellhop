import httpx
import pytest

from bellhop.fetchai.client import BellhopApi, BellhopApiError


def api(handler):
    return BellhopApi("http://bellhop.test", transport=httpx.MockTransport(handler))


def test_reads_three_endpoints():
    seen = []

    def handler(req):
        seen.append(req.url.path)
        body = {
            "/calls": [{"id": "c1"}],
            "/alerts": [{"id": "a1"}],
            "/metrics": {"minutes_saved": 3},
        }
        return httpx.Response(200, json=body[req.url.path])

    a = api(handler)
    assert a.calls() == [{"id": "c1"}]
    assert a.alerts() == [{"id": "a1"}]
    assert a.metrics() == {"minutes_saved": 3}
    assert seen == ["/calls", "/alerts", "/metrics"]


def test_http_error_raises_typed():
    with pytest.raises(BellhopApiError):
        api(lambda r: httpx.Response(500)).calls()


def test_connection_error_raises_typed():
    def boom(req):
        raise httpx.ConnectError("down")

    with pytest.raises(BellhopApiError):
        api(boom).metrics()


def test_timeout_raises_typed():
    def slow(req):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(BellhopApiError):
        api(slow).alerts()


def test_bad_json_or_shape_raises_typed():
    with pytest.raises(BellhopApiError):
        api(lambda r: httpx.Response(200, text="<html>")).calls()
    with pytest.raises(BellhopApiError):
        api(lambda r: httpx.Response(200, json={"x": 1})).calls()
