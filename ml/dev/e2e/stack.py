"""The processes an end-to-end run needs, wired together on spare ports.

    backend (real, from calhacks-13)  --robot gateway-->  FaultProxy  -->  rover.drive --fake
    rover.speech --script (text mode) --BELLHOP_API-->  [optional FaultProxy] --> backend
    rover.speech's status thread  --PI_SERVER_URL-->  rover.drive

Everything logs under one work directory: <component>.jsonl (rover.obslog), <name>.out (stdout).
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from faultproxy import FaultProxy
from procs import Proc, free_port, wait_http

PI_DIR = Path(__file__).resolve().parents[2] / "pi"
BACKEND_DIR = Path(
    os.environ.get("BELLHOP_BACKEND_DIR", "/home/aditya/CalHacks/calhacks-13/backend")
)
SECRET_ENV = ("DEEPGRAM_API_KEY", "ANTHROPIC_API_KEY", "TYPESAFE_API_KEY")


def wait_for(pred: Callable[[], Any], timeout_s: float, every_s: float = 0.1) -> Any:
    """Poll pred until it returns something truthy (returned), or None at the deadline."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            value = pred()
        except (httpx.HTTPError, OSError, KeyError, IndexError, ValueError):
            value = None
        if value:
            return value
        if time.monotonic() >= deadline:
            return None
        time.sleep(every_s)


class StatusTracker:
    """Polls a call and records each distinct status in the order it was first seen."""

    def __init__(self, stack: Stack, call_id: str) -> None:
        self.seen: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(stack, call_id), daemon=True)
        self._thread.start()

    def _run(self, stack: Stack, call_id: str) -> None:
        while not self._stop.is_set():
            try:
                status = stack.api("GET", f"/calls/{call_id}")[1].get("status")
                if status and (not self.seen or self.seen[-1] != status):
                    self.seen.append(status)
            except (httpx.HTTPError, AttributeError):
                pass
            self._stop.wait(0.05)

    def stop(self) -> list[str]:
        self._stop.set()
        self._thread.join(2)
        return self.seen


class Stack:
    def __init__(self, workdir: Path, live_claude: bool = False) -> None:
        self.workdir = workdir
        workdir.mkdir(parents=True, exist_ok=True)
        self.live_claude = live_claude
        self.api_key = secrets.token_hex(8)  # shared secret for this run only; never printed
        self.backend_port, self.drive_port = free_port(), free_port()
        self.drive_proxy = FaultProxy(self.drive_port).start()  # backend -> Pi
        self.backend_proxy: FaultProxy | None = None  # Pi -> backend, only when asked for
        self.procs: dict[str, Proc] = {}
        self.http = httpx.Client(timeout=10.0)

    # ---- addresses

    @property
    def backend_url(self) -> str:
        return f"http://127.0.0.1:{self.backend_port}"

    @property
    def drive_url(self) -> str:
        return f"http://127.0.0.1:{self.drive_port}"

    def pi_backend_url(self) -> str:
        """What the Pi processes use as BELLHOP_API."""
        if self.backend_proxy is not None:
            return f"http://127.0.0.1:{self.backend_proxy.port}"
        return self.backend_url

    def add_backend_proxy(self) -> FaultProxy:
        self.backend_proxy = FaultProxy(self.backend_port).start()
        return self.backend_proxy

    # ---- processes

    def _spawn(self, name: str, argv: list[str], cwd: Path, env: dict[str, str]) -> Proc:
        proc = Proc(name, argv, cwd=cwd, env=env, log=self.workdir / f"{name}.out").start()
        self.procs[name] = proc
        return proc

    def start_backend(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")
        }
        env.update(
            BELLHOP_SEED_DEMO="1",
            BELLHOP_ROBOT_URL=f"http://127.0.0.1:{self.drive_proxy.port}",
            BELLHOP_API_KEY=self.api_key,
        )
        proc = Proc(
            "backend",
            [
                "uv",
                "run",
                "uvicorn",
                "bellhop.api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.backend_port),
            ],  # fmt: skip
            cwd=BACKEND_DIR,
            env=env,
            log=self.workdir / "backend.out",
        ).start()
        self.procs["backend"] = proc
        wait_http(f"{self.backend_url}/health", timeout_s=60)

    def kill_backend(self) -> None:
        proc = self.procs.pop("backend", None)
        if proc:
            proc.stop(grace_s=2.0)

    def start_drive(self, *extra: str) -> None:
        self._spawn(
            "drive",
            [sys.executable, "-m", "rover.drive", "--fake", "--host", "127.0.0.1",
             "--port", str(self.drive_port), *extra],
            PI_DIR,
            self._pi_env(),
        )  # fmt: skip
        wait_http(f"{self.drive_url}/snapshot", timeout_s=30)

    def start_speech(self, script: Path) -> None:
        argv = [sys.executable, "-m", "rover.speech", "--script", str(script)]
        if self.live_claude:
            argv.append("--live-claude")
        self._spawn("speech", argv, PI_DIR, self._pi_env())

    def _pi_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            BELLHOP_API=self.pi_backend_url(),
            BELLHOP_API_KEY=self.api_key,
            PI_SERVER_URL=self.drive_url,
            ROBOT_ID="robot_1",
            ROVER_LOG=str(self.workdir / "{component}.jsonl"),
            ROVER_TEXT_RUNS=str(self.workdir / "runs"),
            LOCAL_TRIAGE="0",
        )
        if not self.live_claude:
            for name in SECRET_ENV:
                env[name] = ""  # the mock path must not need (or use) any key
        return env

    def speech_alive(self) -> bool:
        proc = self.procs.get("speech")
        return bool(proc and proc.running)

    def output(self, name: str) -> str:
        proc = self.procs.get(name)
        return proc.output() if proc else (self.workdir / f"{name}.out").read_text(errors="replace")

    def stop(self) -> None:
        for proc in list(self.procs.values()):
            proc.stop(grace_s=3.0)
        self.procs.clear()
        self.drive_proxy.stop()
        if self.backend_proxy is not None:
            self.backend_proxy.stop()
        self.http.close()

    # ---- the backend API (as the dashboard or a nurse would use it)

    def api(self, method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
        response = self.http.request(
            method,
            self.backend_url + path,
            json=body,
            headers={"X-API-Key": self.api_key},
        )
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, response.text

    def call(self, call_id: str) -> dict:
        return self.api("GET", f"/calls/{call_id}")[1]

    def robot(self, robot_id: str = "robot_1") -> dict | None:
        _, robots = self.api("GET", "/robots")
        return next((r for r in robots if r["id"] == robot_id), None)

    def snapshot(self) -> dict:
        return self.http.get(self.drive_url + "/snapshot").json()

    # ---- the logs

    def events(self, component: str, name: str | None = None, **match: Any) -> list[dict]:
        path = self.workdir / f"{component}.jsonl"
        rows: list[dict] = []
        if not path.exists():
            return rows
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if name is not None and row.get("event") != name:
                continue
            if all(row.get(k) == v for k, v in match.items()):
                rows.append(row)
        return rows
