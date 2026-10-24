#!/usr/bin/env bash
# One-command live demo launcher. It syncs the Pi, starts the laptop backend/dashboard, then
# runs the complete rover stack over SSH. Ctrl-C stops the local processes and the remote rover.
#
# BELLHOP_PI_HOST=pi@100.73.9.29 BELLHOP_PI_IP=100.73.9.29 bash scripts/live-demo.sh
set -euo pipefail

: "${BELLHOP_PI_HOST:?set BELLHOP_PI_HOST, e.g. pi@100.73.9.29}"
: "${BELLHOP_PI_IP:?set BELLHOP_PI_IP, e.g. 100.73.9.29}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
api="http://127.0.0.1:8000"
pids=()

stop() {
  trap - INT TERM EXIT
  echo
  echo "live-demo: stopping laptop services"
  for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap stop INT TERM EXIT

rsync -az --delete \
  --exclude '/.venv' --exclude '/.env' --exclude '/.python-version' \
  --exclude '/models' --exclude '/runs' --exclude '__pycache__' --exclude '*.pyc' \
  "$root/ml/pi/" "$BELLHOP_PI_HOST:~/ml/"

# This script owns the demo backend. Stop only the exact prior Bellhop uvicorn command, not an
# arbitrary process on port 8000.
pkill -f '[u]vicorn bellhop.api.main:app' 2>/dev/null || true
(cd "$root/backend" && BELLHOP_SEED_DEMO=1 BELLHOP_ROBOT_URL="http://$BELLHOP_PI_IP:8080" \
  exec .venv/bin/uvicorn bellhop.api.main:app --host 0.0.0.0 --port 8000) &
pids+=("$!")

for _ in $(seq 1 30); do
  curl -fsS "$api/health" >/dev/null 2>&1 && break
  sleep 0.25
done
curl -fsS "$api/health" >/dev/null || { echo "live-demo: backend did not start" >&2; exit 1; }

if [ -x "$root/dashboard/node_modules/.bin/vite" ]; then
  (cd "$root/dashboard" && VITE_BELLHOP_API_URL="$api" exec npm run dev -- --host 0.0.0.0) &
  pids+=("$!")
  echo "live-demo: dashboard on http://127.0.0.1:5173"
else
  echo "live-demo: dashboard dependencies absent; robot path remains available"
fi

echo "live-demo: backend ready; starting Pi rover over SSH"
ssh -tt "$BELLHOP_PI_HOST" 'cd ~/ml && bash scripts/run_rover.sh'
