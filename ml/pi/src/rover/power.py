"""Pi power and Wi-Fi health: undervoltage flags from vcgencmd, RSSI from iw. Never raises."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable

Runner = Callable[[list[str]], str | None]

FLAG_BITS = {
    "undervoltage_now": 0,
    "freq_capped_now": 1,
    "throttled_now": 2,
    "soft_temp_limit_now": 3,
    "undervoltage_since_boot": 16,
    "freq_capped_since_boot": 17,
    "throttled_since_boot": 18,
    "soft_temp_limit_since_boot": 19,
}
_THROTTLED = re.compile(r"throttled\s*=\s*(0x[0-9a-fA-F]+)")
_SIGNAL = re.compile(r"signal:\s*(-?\d+)\s*dBm")


def parse_throttled(raw: str | None) -> dict:
    """Decode `vcgencmd get_throttled` output; {} when it cannot be parsed."""
    match = _THROTTLED.search(raw or "")
    if not match:
        return {}
    value = int(match.group(1), 16)
    return {name: bool(value >> bit & 1) for name, bit in FLAG_BITS.items()}


def parse_rssi(raw: str | None) -> int | None:
    match = _SIGNAL.search(raw or "")
    return int(match.group(1)) if match else None


def run_command(cmd: list[str]) -> str | None:
    """Default runner: stdout, or None when the command is missing or fails."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def read_power(runner: Runner = run_command, wifi_runner: Runner = run_command) -> dict | None:
    """Throttle flags plus wifi_rssi_dbm, or None where vcgencmd does not exist (the Mac)."""
    try:
        flags = parse_throttled(runner(["vcgencmd", "get_throttled"]))
    except Exception:  # noqa: BLE001 - a status probe must never take the robot down
        return None
    if not flags:
        return None
    try:
        rssi = parse_rssi(wifi_runner(["iw", "dev", "wlan0", "link"]))
    except Exception:  # noqa: BLE001
        rssi = None
    return {**flags, "wifi_rssi_dbm": rssi}


def power_health(power: dict | None) -> str:
    """ok / warn / fault. Undervoltage right now is a fault; any earlier flag is a warning."""
    if not power:
        return "ok"
    if power.get("undervoltage_now"):
        return "fault"
    if any(power.get(name) for name in FLAG_BITS):
        return "warn"
    return "ok"
