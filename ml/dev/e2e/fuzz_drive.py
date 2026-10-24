"""Fuzz the drive server with Schemathesis (needs the fuzz group).

    cd ml/pi && uv run --group fuzz python ../dev/e2e/fuzz_drive.py [--max-examples N]

Starts `python -m rover.drive --fake` on a free port, runs every Schemathesis check against
src/rover/drive/openapi.yaml, stops the server and exits with Schemathesis's status.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from procs import Proc, free_port, wait_http  # noqa: E402

PI_DIR = Path(__file__).resolve().parents[2] / "pi"
SPEC = PI_DIR / "src" / "rover" / "drive" / "openapi.yaml"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-examples", type=int, default=200)
    args = parser.parse_args()
    port = free_port()
    drive = Proc(
        "drive",
        [sys.executable, "-m", "rover.drive", "--fake", "--host", "127.0.0.1", "--port", str(port)],
        cwd=PI_DIR,
    )
    with drive:
        wait_http(f"http://127.0.0.1:{port}/snapshot")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "schemathesis.cli",
                "run",
                str(SPEC),
                "--url",
                f"http://127.0.0.1:{port}",
                "--max-examples",
                str(args.max_examples),
                # /stop /follow /face ignore their body, so sending them junk is not an error
                "--exclude-checks",
                "negative_data_rejection",
                "--generation-database",
                "none",
            ],
            cwd=tempfile.mkdtemp(prefix="st-"),  # its .schemathesis cache stays out of pi/
            # Hypothesis would otherwise leave a .hypothesis folder inside pi/ (sent to the Pi)
            env={**os.environ, "HYPOTHESIS_STORAGE_DIRECTORY": tempfile.mkdtemp(prefix="hyp-")},
        )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
