"""Optional TypeSafe Jev decisions, isolated from the voice and navigation paths.

No key means no request. Network or API failures return ``None``; callers always retain their
local/Claude fallback. The module uses the existing HTTP client so enabling Jev needs no extra
runtime process or code-path dependency.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import httpx

API_URL = "https://api.typesafe.ai/v1/systemone"


def _number_env(name: str, default: float) -> float:
    """Read a bounded positive timeout without making a bad local .env fatal."""
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        return default
    return value if value > 0 else default


def enabled() -> bool:
    return bool(os.environ.get("TYPESAFE_API_KEY", "").strip())


def decide(state: str, questions: Mapping[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Ask Jev once, or return None without raising into the rover's primary path."""
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        return None
    try:
        response = httpx.post(
            API_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": os.environ.get("JEV_MODEL", "jev-latest"),
                "state": state,
                "questions": dict(questions),
            },
            # This is deliberately independent of all visit and navigation budgets.  A request
            # can be abandoned, but no caller is allowed to wait longer than its own tiny budget.
            timeout=_number_env("JEV_TIMEOUT_S", 1.5),
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        print(f"jev: unavailable ({type(exc).__name__})")
        return None
    answers = payload.get("answers") if isinstance(payload, dict) else None
    return answers if isinstance(answers, dict) else None
