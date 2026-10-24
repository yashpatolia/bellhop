#!/usr/bin/env bash
# Pre-demo smoke test, run on the Pi:  bash scripts/smoke.sh
# Env: BELLHOP_API (backend url), BELLHOP_API_KEY, PI_SERVER_URL (drive url). Never prints the key.
set -u
cd "$(dirname "$0")/.." || exit 1
PY="${PYTHON:-.venv/bin/python}"
[ -x "$PY" ] || PY=python3
export BELLHOP_API="${BELLHOP_API:-http://127.0.0.1:8000}"
export PI_SERVER_URL="${PI_SERVER_URL:-http://127.0.0.1:8080}"
FAILS=0

http() { # method url [json body] [send key 0/1] -> exit 0 when 2xx
  "$PY" - "$@" <<'PYEOF'
import os, sys, urllib.request
method, url = sys.argv[1], sys.argv[2]
body = sys.argv[3] if len(sys.argv) > 3 else None
headers = {"Content-Type": "application/json"}
if len(sys.argv) > 4 and sys.argv[4] == "1" and os.environ.get("BELLHOP_API_KEY"):
    headers["X-API-Key"] = os.environ["BELLHOP_API_KEY"]
req = urllib.request.Request(url, data=body.encode() if body else None, method=method, headers=headers)
try:
    with urllib.request.urlopen(req, timeout=3) as r:
        sys.exit(0 if 200 <= r.status < 300 else 1)
except Exception:
    sys.exit(1)
PYEOF
}

check() { # label, command...
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "PASS  $label"; else echo "FAIL  $label"; FAILS=$((FAILS + 1)); fi
}

check "drive GET /snapshot" http GET "$PI_SERVER_URL/snapshot"
check "drive POST /led idle" http POST "$PI_SERVER_URL/led" '{"state":"idle"}'
check "drive POST /stop returns 2xx" http POST "$PI_SERVER_URL/stop" '{}'
if [ -z "${BELLHOP_API_KEY:-}" ]; then
  echo "FAIL  BELLHOP_API_KEY is not set"; FAILS=$((FAILS + 1))
else
  check "backend GET /robots (with key)" http GET "$BELLHOP_API/robots" "" 1
fi

health=$(PYTHONPATH=src "$PY" -c 'from rover import power; print(power.power_health(power.read_power()))' 2>/dev/null)
if [ "$health" = "fault" ] || [ -z "$health" ]; then
  echo "FAIL  power_health is '${health:-unknown}' (undervoltage now, or probe broken)"; FAILS=$((FAILS + 1))
else
  echo "PASS  power_health is $health"
fi

echo "NOTE  SIGTERM test is manual: sudo systemctl stop bellhop-drive while the car is lifted, wheels must stop"
if [ "$FAILS" -eq 0 ]; then echo "ALL PASS"; else echo "$FAILS FAILED"; exit 1; fi
