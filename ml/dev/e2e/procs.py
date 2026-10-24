"""Small process helpers for the dev harnesses: spare ports, child processes that always die."""

from __future__ import annotations

import atexit
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

_live: list[Proc] = []


def free_port() -> int:
    """A port nothing listens on right now (never 8000 or 8080, which the real stack uses)."""
    while True:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port not in (8000, 8080):
            return port


def wait_http(url: str, timeout_s: float = 30.0, headers: dict | None = None) -> None:
    """Return once GET url answers with any HTTP status; raise TimeoutError otherwise."""
    deadline = time.monotonic() + timeout_s
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(request, timeout=2):
                return
        except urllib.error.HTTPError:
            return
        except OSError as exc:
            last = exc
            time.sleep(0.1)
    raise TimeoutError(f"{url} did not answer in {timeout_s:g} s ({last!r})")


class Proc:
    """A child process in its own process group, killed (with its children) on exit."""

    def __init__(
        self,
        name: str,
        argv: list[str],
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        log: Path | None = None,
    ) -> None:
        self.name, self.argv, self.cwd, self.log = name, argv, cwd, log
        self.env = {**os.environ, "PYTHONUNBUFFERED": "1", **(env or {})}
        self.popen: subprocess.Popen | None = None
        self._log_file = None

    def start(self) -> Proc:
        stdout = subprocess.DEVNULL
        if self.log is not None:
            self.log.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = self.log.open("ab")
            stdout = self._log_file
        self.popen = subprocess.Popen(
            self.argv,
            cwd=self.cwd,
            env=self.env,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        _live.append(self)
        return self

    @property
    def running(self) -> bool:
        return self.popen is not None and self.popen.poll() is None

    def stop(self, grace_s: float = 5.0) -> None:
        if self.popen is None:
            return
        if self.popen.poll() is None:
            self._signal(signal.SIGTERM)
            try:
                self.popen.wait(grace_s)
            except subprocess.TimeoutExpired:
                self._signal(signal.SIGKILL)
                self.popen.wait(5)
        else:
            self._signal(signal.SIGKILL)  # reap any grandchildren left in the group
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
        if self in _live:
            _live.remove(self)

    def _signal(self, sig: int) -> None:
        try:
            os.killpg(self.popen.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def output(self) -> str:
        if self.log is None or not self.log.exists():
            return ""
        return self.log.read_text(encoding="utf-8", errors="replace")

    def __enter__(self) -> Proc:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


@atexit.register
def _stop_all() -> None:
    for proc in list(_live):
        proc.stop(grace_s=1.0)
