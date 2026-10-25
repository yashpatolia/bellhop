"""HTTP client for the Bellhop backend (contract: calhacks-13-backend/contracts/openapi.json).

Every failure prints "backend: <method> <path> failed: <reason>" and returns None, False or [],
so a backend outage never crashes the visit loop.
"""

from __future__ import annotations

import math
import re
import time
from typing import Any

import httpx

from rover import config, obslog

ACTIVE_STATUSES = {"assigned", "robot_en_route"}
TURN_MAX_CHARS = 2000  # TurnIn.text limit in the backend
CATEGORY_MAX_CHARS = 64  # ScoreIn.category limit in the backend
MEMORY_QUERY_MAX_CHARS = 500  # GET /memory q limit in the backend
CALL_PATH = re.compile(r"^/calls/([^/]+)")


def _clamp(value: float, low: float, high: float, if_not_finite: float) -> float:
    if not math.isfinite(value):
        return if_not_finite
    return min(high, max(low, value))


class Backend:
    def __init__(
        self,
        base_url: str = config.BELLHOP_API,
        api_key: str = config.BELLHOP_API_KEY,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"X-API-Key": api_key} if api_key else {}
        self._http = httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=config.BACKEND_HTTP_TIMEOUT_S,
            transport=transport,
        )

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response | None:
        match = CALL_PATH.match(path)
        call_id = match.group(1) if match else None
        response: httpx.Response | None = None
        error: str | None = None
        # GETs are safe to replay: a transient Tailscale/WSL stall should not make the rover
        # forget an assigned call. Writes are deliberately never retried, because a timeout can
        # mean the backend applied a non-idempotent update just before the response was lost.
        attempts = 2 if method.upper() == "GET" else 1
        with obslog.Timer() as timer:
            for attempt in range(attempts):
                try:
                    response = self._http.request(method, path, **kwargs)
                    error = None
                    break
                except httpx.HTTPError as exc:
                    error = type(exc).__name__
                    if attempt + 1 < attempts:
                        time.sleep(0.1)
                        continue
                    print(f"backend: {method} {path} failed: {error}: {exc}")
        obslog.event(
            "backend.request",
            method=method,
            path=path,
            call_id=call_id,
            latency_ms=timer.ms,
            status=response.status_code if response is not None else None,
            error=error,
        )
        return response

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._send(method, path, **kwargs)
        if response is None:
            return None
        if response.is_error:
            print(f"backend: {method} {path} failed: {response.status_code} {response.text[:200]}")
            return None
        try:
            return response.json()
        except ValueError as exc:
            print(f"backend: {method} {path} failed: bad JSON: {exc}")
            return None

    def _dict(self, method: str, path: str, **kwargs: Any) -> dict | None:
        data = self._json(method, path, **kwargs)
        if data is not None and not isinstance(data, dict):
            print(f"backend: {method} {path} failed: expected an object, got {type(data).__name__}")
            return None
        return data

    def _list(self, method: str, path: str, **kwargs: Any) -> list[dict]:
        data = self._json(method, path, **kwargs)
        if data is None:
            return []
        if not isinstance(data, list):
            print(f"backend: {method} {path} failed: expected a list, got {type(data).__name__}")
            return []
        return data

    def calls(self) -> list[dict]:
        return self._list("GET", "/calls")

    def get_call(self, call_id: str) -> dict | None:
        return self._dict("GET", f"/calls/{call_id}")

    def find_assigned_call(self, robot_id: str) -> dict | None:
        mine = [
            call
            for call in self.calls()
            if call.get("robot_id") == robot_id and call.get("status") in ACTIVE_STATUSES
        ]
        if not mine:
            return None
        return max(mine, key=lambda call: call.get("created_at") or "")

    def in_visit(self, call_id: str) -> bool:
        path = f"/calls/{call_id}/in-visit"
        response = self._send("POST", path)
        if response is None:
            return False
        if response.is_success:
            return True
        if response.status_code == 409:
            # The 409 body names both states only loosely, so ask for the call's real status.
            call = self.get_call(call_id)
            if call is not None and call.get("status") == "in_visit":
                return True
        print(f"backend: POST {path} failed: {response.status_code} {response.text[:200]}")
        return False

    def add_turn(self, call_id: str, speaker: str, text: str) -> dict | None:
        body = {"speaker": speaker, "text": text[:TURN_MAX_CHARS]}
        return self._dict("POST", f"/calls/{call_id}/turns", json=body)

    def score(
        self, call_id: str, urgency: int, category: str, summary: str, confidence: float
    ) -> dict | None:
        body = {
            # A broken urgency or confidence must escalate, never hide a call.
            "urgency": int(_clamp(urgency, 1, 4, if_not_finite=4)),
            "category": category[:CATEGORY_MAX_CHARS],
            "summary": summary[: config.SUMMARY_MAX_CHARS],
            "confidence": _clamp(confidence, 0.0, 1.0, if_not_finite=0.0),
        }
        obslog.event(
            "backend.score",
            call_id=call_id,
            urgency=body["urgency"],
            category=body["category"],
            confidence=body["confidence"],
        )
        return self._dict("POST", f"/calls/{call_id}/score", json=body)

    def triage_failed(self, call_id: str) -> dict | None:
        return self._dict("POST", f"/calls/{call_id}/triage-failed")

    def resolve(self, call_id: str, by_robot: bool) -> dict | None:
        return self._dict("POST", f"/calls/{call_id}/resolve", json={"by_robot": by_robot})

    def report_robot(
        self,
        robot_id: str,
        status: str,
        battery: float | None,
        room: str | None,
        target: str | None = None,
    ) -> dict | None:
        """PUT /robots/{id}. The backend requires a battery, so an unknown one is sent as full:
        an unreadable gauge must not take the robot out of dispatch (the caller prints why)."""
        body = {
            "status": status,
            "battery": _clamp(battery if battery is not None else 1.0, 0.0, 1.0, if_not_finite=1.0),
            "room": room,
            # Include null on arrival/stop, so the dashboard stops showing a stale destination.
            "target": target,
        }
        return self._dict("PUT", f"/robots/{robot_id}", json=body)

    def resident(self, resident_id: str) -> dict | None:
        return self._dict("GET", f"/residents/{resident_id}")

    def preferences(self, resident_id: str) -> dict | None:
        return self._dict("GET", f"/residents/{resident_id}/preferences")

    def speech_settings(self, resident_id: str) -> dict | None:
        return self._dict("GET", f"/residents/{resident_id}/speech-settings")

    def remember(self, resident_id: str, text: str, tags: list[str]) -> dict | None:
        """Save a fact about the resident (the backend may hold it for a nurse to approve)."""
        body = {"text": text, "tags": tags, "source": "robot", "confidence": 1.0}
        return self._dict("POST", f"/residents/{resident_id}/memory", json=body)

    def memory(self, resident_id: str, q: str = "", k: int = 3) -> list[dict]:
        params = {"q": q[:MEMORY_QUERY_MAX_CHARS], "k": k}
        return self._list("GET", f"/residents/{resident_id}/memory", params=params)
