import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[2] / "backend"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def backend_url():
    """The real backend, empty, on a free port. Skipped when uv or the backend is missing."""
    if not (BACKEND / "pyproject.toml").exists():
        pytest.skip("backend folder not found")
    port = _free_port()
    env = {**os.environ, "BELLHOP_SEED_FILE": "scenarios/empty.json", "BELLHOP_GUARDS": "0"}
    env.pop("BELLHOP_API_KEY", None)
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "bellhop.api.main:app",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=BACKEND,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                if httpx.get(url + "/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.25)
        else:
            pytest.skip("backend did not start", allow_module_level=False)
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


assert sys.version_info >= (3, 12)
