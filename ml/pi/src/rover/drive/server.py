"""The robot's HTTP server: POST /go_to /led /stop /follow /face, GET /snapshot.

Commands answer at once (202 for those that start work) and never wait for the drive.
Any problem with the request is a 4xx so the backend treats it as a failure.
"""

from __future__ import annotations

import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from rover import obslog
from rover.drive.control import Controller, UnknownRoom

MAX_BODY = 4096


class _TooBig:
    pass


TOO_BIG = _TooBig()


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, format: str, *args: Any) -> None:
        print(f"drive http: {self.address_string()} {format % args}")

    def parse_request(self) -> bool:
        self._started = time.perf_counter()
        return super().parse_request()

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        started = getattr(self, "_started", None)
        obslog.event(
            "drive.request",
            method=self.command,
            path=self.path,
            status=int(code) if str(code).isdigit() else None,
            latency_ms=None
            if started is None
            else round((time.perf_counter() - started) * 1000, 2),
        )
        super().log_request(code, size)

    def _send(self, status: int, body: dict, headers: dict[str, str] | None = None) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: HTTPStatus, message: str) -> None:
        headers = {"Allow": self._allowed()} if status == HTTPStatus.METHOD_NOT_ALLOWED else None
        self._send(status, {"error": message}, headers)

    def _allowed(self) -> str:
        return "GET" if self.path == "/snapshot" else "POST"

    def _body(self) -> dict | None | _TooBig:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return TOO_BIG
            if length < 0:
                return None
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return None
        return body if isinstance(body, dict) else None

    def do_GET(self) -> None:
        if self.path == "/snapshot":
            self._send(HTTPStatus.OK, self.server.ctl.snapshot())
        elif self.path in self.server.POST_PATHS:
            self._error(HTTPStatus.METHOD_NOT_ALLOWED, "use POST")
        else:
            self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        ctl = self.server.ctl
        if self.path == "/snapshot":
            return self._error(HTTPStatus.METHOD_NOT_ALLOWED, "use GET")
        if self.path not in self.server.POST_PATHS:
            return self._error(HTTPStatus.NOT_FOUND, "not found")
        body = self._body()
        if body is TOO_BIG:
            return self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"body over {MAX_BODY} bytes")
        if body is None:
            return self._error(HTTPStatus.BAD_REQUEST, "body must be a JSON object")
        if self.path == "/stop":
            ctl.stop()
            return self._send(HTTPStatus.OK, {"ok": True})
        if self.path in ("/follow", "/face"):
            (ctl.follow if self.path == "/follow" else ctl.face)()
            return self._send(HTTPStatus.ACCEPTED, {"ok": True})
        if self.path == "/led":
            state = body.get("state")
            try:
                ctl.set_led(state)  # type: ignore[arg-type]
            except ValueError:
                return self._error(HTTPStatus.BAD_REQUEST, f"unknown led state {state!r}")
            return self._send(HTTPStatus.OK, {"ok": True})
        room = body.get("room")
        if not isinstance(room, str) or not room:
            return self._error(HTTPStatus.BAD_REQUEST, "room must be a non-empty string")
        try:
            ctl.go_to(room)
        except UnknownRoom:
            return self._error(HTTPStatus.NOT_FOUND, f"unknown room {room!r}")
        self._send(HTTPStatus.ACCEPTED, {"ok": True, "room": room})


def _unsupported(self: _Handler) -> None:
    """Methods the server does not do: 405 (known path) or 404, never the library's HTML 501."""
    known = self.path == "/snapshot" or self.path in self.server.POST_PATHS
    status = HTTPStatus.METHOD_NOT_ALLOWED if known else HTTPStatus.NOT_FOUND
    if self.command == "HEAD":
        self.send_response(status)
        if known:
            self.send_header("Allow", self._allowed())
        self.send_header("Content-Length", "0")
        self.end_headers()
        return
    self._error(status, "method not allowed" if known else "not found")


def _any_other_method(self: _Handler, name: str):
    """BaseHTTPRequestHandler looks up do_<METHOD> and answers an HTML 501 when it is missing;
    any method we do not implement (QUERY, PROPFIND, ...) gets the JSON 405/404 instead."""
    if name.startswith("do_"):
        return lambda: _unsupported(self)
    raise AttributeError(name)


_Handler.__getattr__ = _any_other_method  # type: ignore[method-assign]


class _Server(ThreadingHTTPServer):
    POST_PATHS = ("/go_to", "/led", "/stop", "/follow", "/face")
    daemon_threads = True

    def __init__(self, address: tuple[str, int], ctl: Controller) -> None:
        super().__init__(address, _Handler)
        self.ctl = ctl


def make_server(ctl: Controller, host: str, port: int) -> ThreadingHTTPServer:
    return _Server((host, port), ctl)
