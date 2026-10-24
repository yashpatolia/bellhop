"""POST /stop to the local drive server. Stdlib only; always exits 0 (used by systemd ExecStopPost).

python3 scripts/motors_off.py [base_url]     default http://127.0.0.1:8080
"""

import sys
import urllib.request


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
    req = urllib.request.Request(
        base.rstrip("/") + "/stop",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            print(f"motors_off: /stop -> {resp.status}")
    except Exception as exc:  # noqa: BLE001 - server may already be gone; never fail the stop
        print(f"motors_off: no answer ({type(exc).__name__})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
