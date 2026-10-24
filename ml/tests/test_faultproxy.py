import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev" / "e2e"))
from faultproxy import FaultProxy, Rule  # noqa: E402


class Upstream(BaseHTTPRequestHandler):
    hits: list = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        Upstream.hits.append((self.path, json.loads(body or b"{}")))
        data = json.dumps({"ok": True}).encode()
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST


@pytest.fixture
def proxy():
    Upstream.hits = []
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=upstream.serve_forever, args=(0.05,), daemon=True).start()
    with FaultProxy(upstream.server_address[1]) as p:
        yield p
    upstream.shutdown()
    upstream.server_close()


def post(proxy, path="/go_to", body=None, timeout=5.0):
    return httpx.post(
        f"http://127.0.0.1:{proxy.port}{path}", json=body or {"room": "12"}, timeout=timeout
    )


def test_transparent_and_recording(proxy):
    response = post(proxy)
    assert response.status_code == 202 and response.json() == {"ok": True}
    assert Upstream.hits == [("/go_to", {"room": "12"})]
    (seen,) = proxy.seen("/go_to")
    assert (seen.method, seen.body, seen.upstream_status, seen.status) == (
        "POST",
        {"room": "12"},
        202,
        202,
    )
    assert seen.fault == "none"


def test_latency_delays_but_forwards(proxy):
    proxy.add_rule(Rule(path="/go_to", latency_ms=300))
    started = time.monotonic()
    assert post(proxy).status_code == 202
    assert time.monotonic() - started >= 0.3
    started = time.monotonic()
    post(proxy, "/led", {"state": "idle"})
    assert time.monotonic() - started < 0.25  # other paths untouched


def test_caller_timeout_during_latency_still_reaches_upstream_later(proxy):
    proxy.add_rule(Rule(latency_ms=600))
    with pytest.raises(httpx.TimeoutException):
        post(proxy, timeout=0.2)
    time.sleep(0.8)
    assert Upstream.hits == [("/go_to", {"room": "12"})]  # the ghost command a slow link makes


def test_status_fault_forwards_nothing(proxy):
    proxy.add_rule(Rule(path="/go_to", status=503))
    assert post(proxy).status_code == 503
    assert Upstream.hits == []
    assert proxy.seen("/go_to")[0].upstream_status is None


def test_drop_before_hangs_up_and_forwards_nothing(proxy):
    proxy.add_rule(Rule(drop="before"))
    with pytest.raises(httpx.TransportError):
        post(proxy)
    assert Upstream.hits == []
    assert proxy.seen("/go_to")[0].status is None


def test_drop_after_forwards_then_hangs_up(proxy):
    proxy.add_rule(Rule(drop="after"))
    with pytest.raises(httpx.TransportError):
        post(proxy)
    assert Upstream.hits == [("/go_to", {"room": "12"})]
    assert proxy.seen("/go_to")[0].upstream_status == 202


def test_times_limits_a_rule(proxy):
    proxy.add_rule(Rule(path="/go_to", status=500, times=1))
    assert post(proxy).status_code == 500
    assert post(proxy).status_code == 202


def test_dead_upstream_is_a_502_not_a_crash():
    with FaultProxy(target_port=1) as p:
        assert httpx.post(f"http://127.0.0.1:{p.port}/go_to", json={}, timeout=5).status_code == 502


def test_bad_drop_value_rejected():
    with pytest.raises(ValueError):
        Rule(drop="sideways")
