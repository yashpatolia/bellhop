"""A small HTTP proxy for fault injection between the backend and the Pi's drive server.

    proxy = FaultProxy(target_port=drive_port).start()       # listens on proxy.port
    proxy.add_rule(Rule(path="/go_to", latency_ms=3000))     # slow go_to (backend guard is 2 s)
    proxy.add_rule(Rule(path="/go_to", status=503, times=1)) # one 503, then back to normal
    proxy.add_rule(Rule(drop="before"))                      # connection closed, nothing forwarded
    proxy.requests                                           # everything seen, with outcomes

It forwards each request to the target, so with no rules it is a transparent recorder: the e2e
harness reads proxy.requests to prove what the backend sent and what the Pi answered. Rules are
checked in order; the first that matches (path, and `times` not used up) decides the fault.
Faults: latency_ms (wait, then forward), response_delay_ms (forward, then wait before replying),
status (answer with that code, forward nothing), drop "before" (hang up, forward nothing) or
"after" (forward, then hang up without answering: the Pi acted but the caller never knows).

CLI: python faultproxy.py --listen 9000 --target 127.0.0.1:8080 --latency-ms 3000 [--path /go_to]
"""

from __future__ import annotations

import argparse
import http.client
import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "proxy-connection"}


@dataclass
class Rule:
    path: str | None = None  # exact path to match; None = every path
    latency_ms: float = 0.0
    response_delay_ms: float = 0.0
    status: int | None = None
    drop: str | None = None  # "before" or "after"
    times: int | None = None  # None = every matching request
    used: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.drop not in (None, "before", "after"):
            raise ValueError("drop must be 'before' or 'after'")

    def matches(self, path: str) -> bool:
        if self.path is not None and self.path != path:
            return False
        return self.times is None or self.used < self.times

    def describe(self) -> str:
        parts = [
            f"latency={self.latency_ms:g}ms" if self.latency_ms else "",
            f"response_delay={self.response_delay_ms:g}ms" if self.response_delay_ms else "",
            f"status={self.status}" if self.status else "",
            f"drop={self.drop}" if self.drop else "",
        ]
        return " ".join(p for p in parts if p) or "none"


@dataclass
class Seen:
    t: float
    method: str
    path: str
    body: Any
    fault: str
    upstream_status: int | None
    status: int | None  # what the caller got; None = connection dropped
    duration_ms: float


class FaultProxy:
    def __init__(self, target_port: int, target_host: str = "127.0.0.1", port: int = 0) -> None:
        self.target = (target_host, target_port)
        self.rules: list[Rule] = []
        self.requests: list[Seen] = []
        self._lock = threading.Lock()
        self._server = _ProxyServer(("127.0.0.1", port), _Handler, self)
        self.port: int = self._server.server_address[1]
        self._thread: threading.Thread | None = None

    # ---- control

    def start(self) -> FaultProxy:
        self._thread = threading.Thread(
            target=self._server.serve_forever, args=(0.05,), daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> FaultProxy:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def add_rule(self, rule: Rule) -> Rule:
        with self._lock:
            self.rules.append(rule)
        return rule

    def clear_rules(self) -> None:
        with self._lock:
            self.rules.clear()

    def reset(self) -> None:
        with self._lock:
            self.rules.clear()
            self.requests.clear()

    def seen(self, path: str | None = None, method: str | None = None) -> list[Seen]:
        with self._lock:
            return [
                s
                for s in self.requests
                if (path is None or s.path == path) and (method is None or s.method == method)
            ]

    # ---- used by the handler

    def pick_rule(self, path: str) -> Rule | None:
        with self._lock:
            for rule in self.rules:
                if rule.matches(path):
                    rule.used += 1
                    return rule
        return None

    def record(self, seen: Seen) -> None:
        with self._lock:
            self.requests.append(seen)


class _ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], handler: type, proxy: FaultProxy) -> None:
        super().__init__(address, handler)
        self.proxy = proxy


class _Handler(BaseHTTPRequestHandler):
    server: _ProxyServer
    protocol_version = "HTTP/1.0"  # one request per connection keeps drops and delays simple

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _handle(self) -> None:
        proxy = self.server.proxy
        started = time.perf_counter()
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body: Any = json.loads(raw) if raw else None
        except ValueError:
            body = raw.decode("utf-8", "replace")
        rule = proxy.pick_rule(self.path)
        fault = rule.describe() if rule else "none"
        upstream_status: int | None = None
        status: int | None = None

        def finish() -> None:
            proxy.record(
                Seen(
                    t=time.time(),
                    method=self.command,
                    path=self.path,
                    body=body,
                    fault=fault,
                    upstream_status=upstream_status,
                    status=status,
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )
            )

        if rule and rule.latency_ms:
            time.sleep(rule.latency_ms / 1000)
        if rule and rule.drop == "before":
            self.close_connection = True
            finish()
            self.connection.close()
            return
        if rule and rule.status:
            status = rule.status
            finish()  # recorded before the caller can see the answer
            self._reply(status, b'{"error":"injected fault"}', {"Content-Type": "application/json"})
            return
        try:
            upstream_status, data, headers = self._forward(raw)
        except OSError as exc:
            status = 502
            finish()
            self._reply(502, json.dumps({"error": f"proxy: {exc}"}).encode(), {})
            return
        if rule and rule.response_delay_ms:
            time.sleep(rule.response_delay_ms / 1000)
        if rule and rule.drop == "after":
            finish()
            self.connection.close()
            return
        status = upstream_status
        finish()
        self._reply(upstream_status, data, headers)

    def _forward(self, raw: bytes) -> tuple[int, bytes, dict[str, str]]:
        conn = http.client.HTTPConnection(*self.server.proxy.target, timeout=30)
        try:
            headers = {
                k: v
                for k, v in self.headers.items()
                if k.lower() not in HOP_BY_HOP | {"host", "content-length"}
            }
            conn.request(self.command, self.path, body=raw or None, headers=headers)
            response = conn.getresponse()
            data = response.read()
            keep = {
                k: v
                for k, v in response.getheaders()
                if k.lower() not in HOP_BY_HOP | {"content-length", "date", "server"}
            }
            return response.status, data, keep
        finally:
            conn.close()

    def _reply(self, status: int, data: bytes, headers: dict[str, str]) -> None:
        try:
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass  # the caller gave up (for example its own timeout)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _handle


def main() -> None:
    parser = argparse.ArgumentParser(description="Fault-injecting HTTP proxy")
    parser.add_argument("--listen", type=int, required=True)
    parser.add_argument("--target", required=True, help="host:port of the real server")
    parser.add_argument("--path", help="only apply the fault to this exact path")
    parser.add_argument("--latency-ms", type=float, default=0.0)
    parser.add_argument("--status", type=int)
    parser.add_argument("--drop", choices=["before", "after"])
    args = parser.parse_args()
    host, _, port = args.target.rpartition(":")
    proxy = FaultProxy(int(port), host or "127.0.0.1", args.listen)
    if args.latency_ms or args.status or args.drop:
        proxy.add_rule(
            Rule(path=args.path, latency_ms=args.latency_ms, status=args.status, drop=args.drop)
        )
    print(f"faultproxy: :{proxy.port} -> {args.target}", flush=True)
    try:
        proxy._server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
