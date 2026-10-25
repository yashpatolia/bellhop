import httpx
import pytest

from bellhop.adapters.http_robot_gateway import HttpRobotGateway


def make(handler):
    return HttpRobotGateway(
        "http://pi.local:8080/",
        timeout=2.0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_go_to_posts_room():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url), request.read()))
        return httpx.Response(200)

    make(handler).go_to("robot_1", "12")
    assert seen == [("POST", "http://pi.local:8080/go_to", b'{"room":"12"}')]


def test_follow_marker_posts_marker_target():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url), request.read()))
        return httpx.Response(202)

    make(handler).follow_marker("robot_1", "208")
    assert seen == [("POST", "http://pi.local:8080/follow_marker", b'{"room":"208"}')]


def test_default_client_bypasses_proxy_environment(monkeypatch):
    seen = {}

    def client(**kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr("bellhop.adapters.http_robot_gateway.httpx.Client", client)
    HttpRobotGateway("http://100.73.9.29:8080")

    assert seen == {"timeout": 5.0, "trust_env": False}


def test_set_led_posts_state():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.read()))
        return httpx.Response(204)

    make(handler).set_led("robot_1", "emergency")
    assert seen == [("http://pi.local:8080/led", b'{"state":"emergency"}')]


def test_non_2xx_raises():
    gw = make(lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        gw.go_to("robot_1", "12")


def test_transport_error_raises():
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(httpx.ConnectError):
        make(handler).set_led("robot_1", "idle")


def test_stop_posts_empty_body_to_stop():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url), request.read()))
        return httpx.Response(200)

    make(handler).stop("robot_1")
    assert seen == [("POST", "http://pi.local:8080/stop", b"{}")]


def test_stop_non_2xx_raises():
    with pytest.raises(httpx.HTTPStatusError):
        make(lambda r: httpx.Response(500)).stop("robot_1")
