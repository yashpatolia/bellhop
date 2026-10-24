"""One command that checks the robot's whole setup and says what is wrong.

    uv run python scripts/doctor.py [--no-hardware] [--json]

Every check ends OK, FAIL or SKIPPED with a reason, and a check that cannot run on this machine
(no camera on a Mac, no Freenove board off the Pi) is SKIPPED, never a crash. Exit 1 on any FAIL.
Devices reuse what the check_* scripts use (open_camera, Mic, the car's ADC and ultrasonic);
nothing here drives the motors or plays a sound. Key values are never printed, only their presence.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import json
import math
import os
import platform
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from rover import config

OK, FAIL, SKIPPED = "OK", "FAIL", "SKIPPED"
KEYS = {  # name -> (required, what is lost without it)
    "DEEPGRAM_API_KEY": (True, "Flux is off, every turn goes to Moonshine"),
    "ANTHROPIC_API_KEY": (True, "replies use the fallback line and Claude triage is skipped"),
    "BELLHOP_API_KEY": (False, "fine while the backend is open; the backend check says if not"),
}
SKEW_FAIL_S = 5.0  # the Date header only has whole seconds
DEVICE_TIMEOUT_S = 8.0
ON_LINUX = sys.platform == "linux"
SCRIPTS = Path(__file__).resolve().parent


@dataclass
class Result:
    name: str
    status: str
    detail: str = ""


def run_check(name: str, check: Callable[[], Result | tuple[str, str]]) -> Result:
    """Run one check; any exception is a FAIL, a hang is a FAIL after DEVICE_TIMEOUT_S."""
    box: list[Result] = []

    def work() -> None:
        try:
            value = check()
            box.append(value if isinstance(value, Result) else Result(name, *value))
        except Exception as exc:
            box.append(Result(name, FAIL, f"{type(exc).__name__}: {exc}"))

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(DEVICE_TIMEOUT_S)
    if not box:
        return Result(name, FAIL, f"no answer in {DEVICE_TIMEOUT_S:g} s")
    box[0].name = name
    return box[0]


# ---- software


def smoke_module():
    """scripts/smoke.py has the list of packages and how to read their versions: reuse it."""
    spec = importlib.util.spec_from_file_location("rover_smoke", SCRIPTS / "smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_python(version: tuple[int, int, int] | None = None) -> tuple[str, str]:
    major, minor, micro = version or sys.version_info[:3]
    text = f"python {major}.{minor}.{micro}"
    if (major, minor) not in ((3, 11), (3, 13)):
        return FAIL, f"{text}: supported are 3.11 (Bookworm) and 3.13 (Trixie)"
    return OK, text


def check_packages(
    dists: Mapping[str, str] | None = None,
    version_of: Callable[[str], str] = importlib.metadata.version,
) -> tuple[str, str]:
    if dists is None:
        dists = {name: dist for name, dist in smoke_module().IMPORTS.items()}
    missing, found = [], []
    for dist in dict.fromkeys(dists.values()):
        try:
            found.append(f"{dist} {version_of(dist)}")
        except importlib.metadata.PackageNotFoundError:
            missing.append(dist)
    if missing:
        return FAIL, f"not installed: {', '.join(missing)} (uv sync)"
    return OK, ", ".join(found)


# ---- keys and clock


def check_keys(env: Mapping[str, str]) -> list[Result]:
    results = []
    for name, (required, lost) in KEYS.items():
        if env.get(name, "").strip():
            results.append(Result(f"key {name}", OK, "set"))
        else:
            status = FAIL if required else SKIPPED
            results.append(Result(f"key {name}", status, f"not set: {lost}"))
    return results


def clock_skew_s(date_header: str | None, local_now: datetime, rtt_s: float = 0.0) -> float:
    """Local clock minus the backend's, from its Date header (whole seconds, so +/- 1 s)."""
    if not date_header:
        raise ValueError("no Date header")
    remote = parsedate_to_datetime(date_header)
    if remote.tzinfo is None:
        remote = remote.replace(tzinfo=UTC)
    return (local_now - timedelta(seconds=rtt_s / 2) - remote).total_seconds()


def skew_result(skew_s: float) -> tuple[str, str]:
    text = f"local clock is {skew_s:+.1f} s from the backend's (Date header has 1 s resolution)"
    return (FAIL, text) if abs(skew_s) > SKEW_FAIL_S else (OK, text)


# ---- the backend and the Pi server


def check_pi_server(client: httpx.Client, base_url: str) -> tuple[str, str]:
    url = base_url.rstrip("/") + "/snapshot"
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        return FAIL, f"{url} unreachable ({type(exc).__name__}); start `python -m rover.drive`"
    if response.status_code != 200:
        return FAIL, f"{url} answered {response.status_code}"
    try:
        snap = response.json()
    except ValueError:
        return FAIL, f"{url} answered something that is not JSON"
    needed = {"room", "mode", "moving", "battery", "led"}
    if not isinstance(snap, dict) or not needed <= snap.keys():
        return FAIL, f"/snapshot is missing {sorted(needed - set(snap or {}))}"
    note = " (motors failed: driving with FakeCar)" if snap.get("motors_failed") else ""
    return (
        OK,
        f"room {snap['room']}, mode {snap['mode']}, battery {snap['battery']}, "
        f"led {snap['led']}{note}",
    )


def check_backend(
    client: httpx.Client, base_url: str, api_key: str
) -> tuple[Result, Result, Result]:
    """Reachability (GET /health), key validity (cheap authenticated GET /robots) and clock skew."""
    health_url = base_url.rstrip("/") + "/health"
    sent = time.perf_counter()
    try:
        health = client.get(health_url)
    except httpx.HTTPError as exc:
        down = f"{health_url} unreachable ({type(exc).__name__}: {exc})"
        return (
            Result("backend reachable", FAIL, down),
            Result("backend API key", SKIPPED, "backend unreachable"),
            Result("clock skew", SKIPPED, "backend unreachable"),
        )
    rtt = time.perf_counter() - sent
    reach = Result(
        "backend reachable",
        OK if health.status_code == 200 else FAIL,
        f"/health {health.status_code} in {rtt * 1000:.0f} ms",
    )
    try:
        skew = skew_result(clock_skew_s(health.headers.get("date"), datetime.now(UTC), rtt))
        clock = Result("clock skew", *skew)
    except ValueError as exc:
        clock = Result("clock skew", SKIPPED, str(exc))
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        auth = client.get(base_url.rstrip("/") + "/robots", headers=headers)
    except httpx.HTTPError as exc:
        return (
            reach,
            Result("backend API key", FAIL, f"GET /robots failed ({type(exc).__name__})"),
            clock,
        )
    if auth.status_code == 200:
        detail = "accepted" if api_key else "backend is open (no key set, none needed)"
        return reach, Result("backend API key", OK, detail), clock
    if auth.status_code == 401:
        detail = (
            "rejected (401): BELLHOP_API_KEY is wrong"
            if api_key
            else "backend wants a key (401) and BELLHOP_API_KEY is not set"
        )
        return reach, Result("backend API key", FAIL, detail), clock
    return reach, Result("backend API key", FAIL, f"GET /robots answered {auth.status_code}"), clock


# ---- hardware (each one tolerates a machine without it)


def check_camera() -> tuple[str, str]:
    if (
        ON_LINUX
        and not list(Path("/dev").glob("video*"))
        and importlib.util.find_spec("picamera2") is None
    ):
        return SKIPPED, "no /dev/video* and no picamera2 on this machine"
    from rover.vision.camera import open_camera

    camera = open_camera(None)
    try:
        frame = camera.read()
    finally:
        camera.close()
    if frame is None:
        return FAIL, f"{camera.backend} gave no frame (is rover.vision running? it owns the camera)"
    return OK, f"{camera.backend}, frame {frame.shape}, mean brightness {frame.mean():.0f}"


def _sounddevice():
    try:
        import sounddevice
    except Exception as exc:  # OSError when PortAudio is missing
        raise RuntimeError(f"sounddevice unavailable ({exc})") from None
    return sounddevice


def check_mic() -> tuple[str, str]:
    try:
        sd = _sounddevice()
    except RuntimeError as exc:
        return SKIPPED, str(exc)
    if not any(d["max_input_channels"] > 0 for d in sd.query_devices()):
        return SKIPPED, "no input device"
    from rover.speech.gates import block_dbfs
    from rover.speech.mic import Mic

    mic = Mic()
    mic.start()
    try:
        blocks = [b for b in (mic.read(timeout=2.0) for _ in range(8)) if b is not None]
    finally:
        mic.stop()
    if not blocks:
        return FAIL, "opened but no audio arrived"
    level = max(block_dbfs(b) for b in blocks)
    if not math.isfinite(level) or level < -90:
        return FAIL, f"audio is digital silence ({level:.0f} dBFS): muted or wrong device"
    return OK, f"{config.MIC_NAME or 'default'} mic, peak {level:.0f} dBFS over 0.25 s"


def check_speaker() -> tuple[str, str]:
    try:
        sd = _sounddevice()
    except RuntimeError as exc:
        return SKIPPED, str(exc)
    from rover.speech.mic import find_device

    outputs = [d for d in sd.query_devices() if d["max_output_channels"] > 0]
    if not outputs:
        return SKIPPED, "no output device"
    index = find_device(config.SPEAKER_NAME, "output")
    info = (
        sd.query_devices(index, "output") if index is not None else sd.query_devices(kind="output")
    )
    return OK, f"{info['name']} at {int(info['default_samplerate'])} Hz (nothing played)"


def _car_part(label: str, module: str, action: Callable) -> tuple[str, str]:
    if not ON_LINUX:
        return SKIPPED, "car I/O is Pi only"
    if not (config.FREENOVE_DIR / f"{module}.py").exists():
        return SKIPPED, f"{config.FREENOVE_DIR}/{module}.py not found (Freenove repo is not cloned)"
    return action()


def check_adc() -> tuple[str, str]:
    def read() -> tuple[str, str]:
        from rover.drive.car import _BatteryAdc, battery_share

        adc = _BatteryAdc()
        try:
            volts = adc.volts()
        finally:
            adc.close()
        if volts is None:
            return FAIL, "ADC answered but two reads never agreed"
        share = battery_share(volts)
        return OK, f"battery {volts:.2f} V ({'?' if share is None else f'{share * 100:.0f}%'})"

    return _car_part("adc", "motor", read)


def check_ultrasonic() -> tuple[str, str]:
    def read() -> tuple[str, str]:
        from rover.drive.car import _freenove

        sonar = _freenove("ultrasonic").Ultrasonic()
        try:
            distance = sonar.get_distance()
        finally:
            sonar.close()
        if distance is None or distance <= 0:
            return FAIL, f"read {distance!r}: sensor not wired or nothing in range"
        return OK, f"{distance:.0f} cm ahead"

    return _car_part("ultrasonic", "ultrasonic", read)


# ---- the run


def run_all(hardware: bool = True, env: Mapping[str, str] | None = None) -> list[Result]:
    env = os.environ if env is None else env
    results = [
        run_check("python", check_python),
        run_check("packages", check_packages),
    ]
    if hardware:
        for name, check in (
            ("camera", check_camera),
            ("microphone", check_mic),
            ("speaker", check_speaker),
            ("battery ADC", check_adc),
            ("ultrasonic", check_ultrasonic),
        ):
            results.append(run_check(name, check))
    else:
        results.append(Result("hardware", SKIPPED, "--no-hardware"))
    with httpx.Client(timeout=config.HTTP_TIMEOUT_S) as client:
        results.append(
            run_check("Pi server", lambda: check_pi_server(client, config.PI_SERVER_URL))
        )
        try:
            results.extend(check_backend(client, config.BELLHOP_API, config.BELLHOP_API_KEY))
        except Exception as exc:
            results.append(Result("backend", FAIL, f"{type(exc).__name__}: {exc}"))
    results.extend(check_keys(env))
    return results


def print_results(results: list[Result]) -> None:
    width = max(len(r.name) for r in results)
    for result in results:
        print(f"  {result.status:<7} {result.name:<{width}}  {result.detail}")
    counts = {s: sum(r.status == s for r in results) for s in (OK, FAIL, SKIPPED)}
    print(f"\n{counts[OK]} OK, {counts[FAIL]} FAIL, {counts[SKIPPED]} SKIPPED")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--no-hardware", action="store_true", help="skip camera, mic, speaker, ADC, ultrasonic"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    print(
        f"doctor: {platform.platform()}, backend {config.BELLHOP_API}, "
        f"Pi server {config.PI_SERVER_URL}",
        flush=True,
    )
    results = run_all(hardware=not args.no_hardware)
    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        print_results(results)
    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
