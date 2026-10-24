"""Thin HTTP client for the Bellhop backend. Mirrors the routes in contracts/openapi.json."""

from __future__ import annotations

import time
from typing import Any

import httpx


class BackendError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, detail: str) -> None:
        super().__init__(f"{method} {path} -> {status}: {detail}")
        self.status = status


class Backend:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"X-API-Key": api_key} if api_key else {}
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), headers=headers, timeout=10.0, transport=transport
        )

    def wait_ready(self, timeout_s: float = 30.0) -> None:
        """Block until GET /health answers, so `seed` can start with the backend."""
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                if self._http.get("/health").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise TimeoutError(f"backend not ready at {self._http.base_url}")
            time.sleep(0.5)

    def request(
        self, method: str, path: str, *, ok: tuple[int, ...] = (200, 201), **kwargs: Any
    ) -> Any:
        r = self._http.request(method, path, **kwargs)
        if r.status_code not in ok:
            raise BackendError(method, path, r.status_code, r.text[:200])
        return r.json() if r.content else None

    def get(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, json: Any = None, **kw: Any) -> Any:
        return self.request("POST", path, json=json, **kw)

    def put(self, path: str, json: Any = None, **kw: Any) -> Any:
        return self.request("PUT", path, json=json, **kw)
