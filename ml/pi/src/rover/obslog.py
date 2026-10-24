"""Structured logs: one JSON object per line, flushed on every event, written to ROVER_LOG.

    obslog.configure("speech")                       # once per process; no ROVER_LOG = no output
    obslog.event("backend.request", call_id="c1", status=200, latency_ms=12.3)

Each line carries t (epoch seconds), component, pid and event, plus the fields given. Fields that
look like secrets (key, token, secret, password, authorization) are masked, and so is any value
equal to a secret in the environment. ROVER_LOG may hold "{component}" so every process gets its
own file; dev/tail.py merges the files by time. Logging never raises into the robot.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

LOGGER_NAME = "rover.obs"
SECRET_ENV = (
    "DEEPGRAM_API_KEY",
    "ANTHROPIC_API_KEY",
    "TYPESAFE_API_KEY",
    "BELLHOP_API_KEY",
)
SECRET_FIELD = re.compile(r"key|token|secret|password|authorization", re.IGNORECASE)
MASK = "***"
MIN_SECRET_LEN = 6  # shorter values would mask ordinary text

_logger = logging.getLogger(LOGGER_NAME)
_logger.addHandler(logging.NullHandler())
_logger.propagate = False
_component = "rover"


def _secret_values() -> list[str]:
    values = (os.environ.get(name, "").strip() for name in SECRET_ENV)
    return [value for value in values if len(value) >= MIN_SECRET_LEN]


def _clean(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, MASK)
        return value
    if isinstance(value, dict):
        return {
            str(k): MASK if SECRET_FIELD.search(str(k)) else _clean(v, secrets)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_clean(v, secrets) for v in value]
    return value


class JsonLinesFormatter(logging.Formatter):
    """Formats a record made by event(): the fields travel in record.obs."""

    def format(self, record: logging.LogRecord) -> str:
        fields = getattr(record, "obs", None)
        if fields is None:
            fields = {"event": "log", "message": record.getMessage()}
        line = {
            "t": round(record.created, 6),
            "component": getattr(record, "component", _component),
            "pid": record.process,
            **fields,
        }
        return json.dumps(line, default=str, separators=(",", ":"))


class _FlushingFileHandler(logging.FileHandler):
    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()  # a killed process must not lose its last lines


def configure(component: str, path: str | os.PathLike | None = None) -> bool:
    """Send events to path (default: env ROVER_LOG). Returns False when logging stays off."""
    global _component
    _component = component
    for handler in list(_logger.handlers):
        if not isinstance(handler, logging.NullHandler):
            _logger.removeHandler(handler)
            handler.close()
    target = str(path) if path is not None else os.environ.get("ROVER_LOG", "").strip()
    if not target:
        _logger.setLevel(logging.CRITICAL + 1)
        return False
    target = target.replace("{component}", component)
    try:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        handler = _FlushingFileHandler(target, mode="a", encoding="utf-8")
    except OSError as exc:
        print(f"obslog: cannot open {target}: {exc}; logging is off")
        _logger.setLevel(logging.CRITICAL + 1)
        return False
    handler.setFormatter(JsonLinesFormatter())
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)
    return True


def event(name: str, **fields: Any) -> None:
    """Record one event. Fields with None values are dropped to keep lines short."""
    if not _logger.isEnabledFor(logging.INFO):
        return
    try:
        secrets = _secret_values()
        obs = {"event": name}
        for key, value in fields.items():
            if value is None:
                continue
            obs[key] = MASK if SECRET_FIELD.search(key) else _clean(value, secrets)
        record = _logger.makeRecord(
            LOGGER_NAME,
            logging.INFO,
            "",
            0,
            "",
            (),
            None,
            extra={"obs": obs, "component": _component},
        )
        _logger.handle(record)
    except Exception as exc:  # observability must never take the robot down
        print(f"obslog: dropped {name}: {exc!r}")


class Timer:
    """with Timer() as t: ...; t.ms is the elapsed milliseconds (rounded)."""

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        self.ms = 0.0
        return self

    def __exit__(self, *exc: object) -> None:
        self.ms = round((time.perf_counter() - self._start) * 1000, 2)
