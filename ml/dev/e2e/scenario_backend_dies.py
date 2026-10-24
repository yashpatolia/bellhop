"""The backend dies mid-visit: the Pi must not leave its LED on `emergency`.

    cd ml/pi && uv run python ../dev/e2e/scenario_backend_dies.py

Only the backend ever sends `idle`, so before the Pi-side fix a dead backend left the LED lit for
good. Two runs, LED_HOLD_S shortened to 4 s so it takes under a minute:

  a. the speech process is SIGKILLed (no cleanup runs): the drive server's own hold must return
     the LED to idle once nothing refreshes it;
  b. the speech process is SIGTERMed (a restart): it sets the LED idle and stops the wheels at
     once, with the backend still dead. While the visit was alive the LED stayed `emergency`.

To fold it into run.py (not done, that file is not ours): add "backend_dies" to `names` in main()
and one branch `elif name == "backend_dies": scenario_backend_dies.scenario(workdir, rep)`, with
`import scenario_backend_dies` next to the other e2e imports.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import tempfile
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stack import Stack, wait_for  # noqa: E402

HOLD_S = 4.0
LINES = [
    {"greeting": "Good morning Margaret."},
    {"say": "Help, I fell and I can't get up", "reply": "Stay still, help is coming."},
]


def _start(workdir: Path) -> Stack:
    os.environ["LED_HOLD_S"] = str(HOLD_S)  # inherited by the drive and speech children
    stack = Stack(workdir)
    script = workdir / "script.jsonl"
    script.write_text("\n".join(json.dumps(x) for x in LINES) + "\n", encoding="utf-8")
    stack.start_backend()
    stack.start_drive()
    stack.start_speech(script)
    status, call = stack.api("POST", "/calls", {"room": "12"})
    if status != 201:
        raise RuntimeError(f"POST /calls -> {status}")
    return stack


def _emergency_then_backend_dies(stack: Stack, rep) -> bool:
    lit = wait_for(lambda: stack.snapshot().get("led") == "emergency", 60)
    rep.check("emergency LED is lit by the backend", bool(lit))
    stack.kill_backend()
    time.sleep(3 * HOLD_S)
    snap = stack.snapshot()
    rep.check(
        "backend dead, visit still live: LED is kept on emergency past LED_HOLD_S",
        snap["led"] == "emergency" and stack.speech_alive(),
        f"led={snap['led']} speech_alive={stack.speech_alive()}",
    )
    return bool(lit)


def scenario_killed(workdir: Path, rep) -> None:
    stack = _start(workdir)
    try:
        if not _emergency_then_backend_dies(stack, rep):
            return
        speech = stack.procs["speech"]
        os.killpg(speech.popen.pid, signal.SIGKILL)  # a crash: no finally block runs
        idle = wait_for(lambda: stack.snapshot().get("led") == "idle", 3 * HOLD_S)
        rep.check(
            "speech SIGKILLed: the drive server returns the LED to idle on its own",
            bool(idle) and bool(stack.events("drive", "drive.led_expired", state="emergency")),
        )
    finally:
        stack.stop()


def scenario_terminated(workdir: Path, rep) -> None:
    stack = _start(workdir)
    try:
        if not _emergency_then_backend_dies(stack, rep):
            return
        stops_before = len(stack.events("drive", "drive.stop"))
        speech = stack.procs["speech"]
        os.killpg(speech.popen.pid, signal.SIGTERM)
        code = speech.popen.wait(10)
        rep.check("speech SIGTERM exits 0", code == 0, f"exit code {code}")
        snap = stack.snapshot()
        rep.check(
            "speech SIGTERM: LED idle at once and the wheels stopped",
            snap["led"] == "idle"
            and snap["mode"] == "idle"
            and len(stack.events("drive", "drive.stop")) > stops_before,
            f"{snap}",
        )
        rep.check("speech logs the release", bool(stack.events("speech", "visit.release")))
    finally:
        stack.stop()


class _Report:
    def __init__(self, name: str) -> None:
        self.name, self.failed = name, 0

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        print(f"  {'PASS' if ok else 'FAIL'}  {self.name}: {name}  {'' if ok else detail}")
        self.failed += not ok
        return ok


def scenario(workdir: Path, rep) -> None:
    """Both runs, for run.py's `scenario(workdir, rep)` shape."""
    scenario_killed(workdir / "killed", rep)
    scenario_terminated(workdir / "terminated", rep)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="rover-e2e-dies-"))
    rep = _Report("backend_dies")
    try:
        scenario(root, rep)
    except Exception:
        traceback.print_exc()
        rep.check("scenario ran to the end", False)
    print(f"{'FAIL' if rep.failed else 'PASS'} (logs: {root})")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
