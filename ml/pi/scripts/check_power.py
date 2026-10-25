"""Watch power and memory while the robot talks: does the screen go dark from power or from RAM?

Usage (Pi): uv run python scripts/check_power.py [--seconds 60]   # then talk to the robot
Prints a line every 0.5 s: under-voltage now, the 5 V input (Pi 5 PMIC) and memory available.
Success: "undervoltage no" and 5 V at 4.9 V or more on every line, while the screen stays lit.
"undervoltage YES" or a dip below 4.8 V as the screen goes dark: it is power. Power the screen
from its own supply (not a Pi USB port); see the README troubleshooting row.
Memory available near 0 with power fine: it is RAM (check free -m and swap).
"""

import argparse
import re
import time

from rover.power import parse_throttled, run_command

EVERY_S = 0.5
_VOLTS = re.compile(r"=\s*([0-9.]+)V")


def five_volts() -> float | None:
    found = _VOLTS.search(run_command(["vcgencmd", "pmic_read_adc", "EXT5V_V"]) or "")
    return float(found.group(1)) if found else None


def available_mb() -> int | None:
    with open("/proc/meminfo") as meminfo:
        for line in meminfo:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Power and memory while the robot talks")
    parser.add_argument("--seconds", type=float, default=60.0)
    args = parser.parse_args()
    if not parse_throttled(run_command(["vcgencmd", "get_throttled"])):
        print("FAIL: vcgencmd get_throttled gave nothing (run this on the Pi)")
        raise SystemExit(1)
    lowest, ever_under = None, False
    end = time.monotonic() + args.seconds
    while time.monotonic() < end:
        flags = parse_throttled(run_command(["vcgencmd", "get_throttled"]))
        volts = five_volts()
        under = flags.get("undervoltage_now", False)
        ever_under = ever_under or under
        if volts is not None:
            lowest = volts if lowest is None else min(lowest, volts)
        shown = "?" if volts is None else f"{volts:.2f} V"
        print(
            f"undervoltage {'YES' if under else 'no '}  5V {shown}  "
            f"since boot: {'YES' if flags.get('undervoltage_since_boot') else 'no'}  "
            f"memory available {available_mb()} MB"
        )
        time.sleep(EVERY_S)
    low = "?" if lowest is None else f"{lowest:.2f} V"
    verdict = "power is the problem" if ever_under or (lowest or 5.0) < 4.8 else "power looks fine"
    print(f"lowest 5V {low}, under-voltage seen: {ever_under}: {verdict}")


if __name__ == "__main__":
    main()
