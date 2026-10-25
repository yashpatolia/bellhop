#!/usr/bin/env bash
# Run the whole stack on this machine.
#
#   scripts/dev.sh mock    backend + simulator (example residents and live bell presses) + frontend
#   scripts/dev.sh empty   backend + frontend, nothing in the home (the real robot and staff fill it)
#
# Extra arguments go to `bellhop-sim run` in mock mode, for example:
#   scripts/dev.sh mock --scene busy --rate 3 --speed 2
#
# Ports: BACKEND_PORT (8000) and FRONTEND_PORT (5173). Ctrl+C stops everything.
set -euo pipefail

mode="${1:-}"
case "$mode" in mock | empty) shift ;; *)
  echo "usage: scripts/dev.sh mock|empty [bellhop-sim run options]" >&2
  exit 2
  ;;
esac

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend_port="${BACKEND_PORT:-8000}"
frontend_port="${FRONTEND_PORT:-5173}"
api="http://127.0.0.1:${backend_port}"
pids=()

stop() {
  trap - INT TERM EXIT
  echo
  echo "stopping..."
  for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap stop INT TERM EXIT

echo "backend on ${api} (no data of its own)"
(cd "$root/backend" && BELLHOP_SEED_FILE=scenarios/empty.json exec uv run uvicorn bellhop.api.main:app --host 127.0.0.1 --port "$backend_port" --log-level warning) &
pids+=($!)

for _ in $(seq 1 60); do
  curl -fs "${api}/health" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fs "${api}/health" >/dev/null || { echo "backend did not start" >&2; exit 1; }

if [ "$mode" = mock ]; then
  echo "simulator: seeding the example home, then ringing bells"
  (cd "$root/simulator" && exec uv run bellhop-sim --base-url "$api" run --seed-home "$@") &
  pids+=($!)
else
  echo "empty home: nothing is simulated"
fi

echo "frontend on http://localhost:${frontend_port}"
(cd "$root/frontend" && VITE_BELLHOP_API_URL="$api" exec npm run dev -- --port "$frontend_port" --strictPort) &
pids+=($!)

wait
