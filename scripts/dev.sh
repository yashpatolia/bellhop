#!/usr/bin/env bash
# Run the whole stack on this machine.
#
#   scripts/dev.sh mock    backend + simulator (example residents and live bell presses) + frontend
#   scripts/dev.sh empty   backend + frontend, nothing in the home (the real robot and staff fill it)
#   scripts/dev.sh demo    the real backend (empty) plus a second, in-memory demo backend that the
#                          simulator fills, calm enough to follow (about 1 bell a minute, nurses
#                          answer after a minute). The dashboard's Demo button switches between the two.
#
# Extra arguments go to `bellhop-sim run` in mock mode, for example:
#   scripts/dev.sh mock --scene busy --rate 3 --speed 2
#
# Ports: BACKEND_PORT (8000), DEMO_PORT (8001, demo mode only) and FRONTEND_PORT (5173). Ctrl+C stops everything.
set -euo pipefail

mode="${1:-}"
case "$mode" in mock | empty | demo) shift ;; *)
  echo "usage: scripts/dev.sh mock|empty|demo [bellhop-sim run options]" >&2
  exit 2
  ;;
esac

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend_port="${BACKEND_PORT:-8000}"
frontend_port="${FRONTEND_PORT:-5173}"
demo_port="${DEMO_PORT:-8001}"
demo_api="http://127.0.0.1:${demo_port}"
api="http://127.0.0.1:${backend_port}"
pids=()

# The real home is stored in SpacetimeDB (it falls back to memory, with a warning, if the server is not
# running). mock mode fills the home with made-up residents, so it stays in memory.
real_store="${BELLHOP_STORE:-spacetimedb}"
[ "$mode" = mock ] && real_store=memory
if [ "$real_store" = spacetimedb ] && ! curl -fs "${BELLHOP_STDB_URL:-http://127.0.0.1:3000}/v1/ping" >/dev/null 2>&1; then
  echo "WARNING: SpacetimeDB is not running (start it with: spacetime start). Using memory: data is lost on restart." >&2
fi

stop() {
  trap - INT TERM EXIT
  echo
  echo "stopping..."
  for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap stop INT TERM EXIT

echo "backend on ${api} (no data of its own)"
(cd "$root/backend" && BELLHOP_STORE="$real_store" BELLHOP_SEED_FILE=scenarios/empty.json exec uv run uvicorn bellhop.api.main:app --host 127.0.0.1 --port "$backend_port" --log-level warning) &
pids+=($!)

for _ in $(seq 1 60); do
  curl -fs "${api}/health" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fs "${api}/health" >/dev/null || { echo "backend did not start" >&2; exit 1; }

if [ "$mode" = demo ]; then
  echo "demo backend on ${demo_api} (in memory, never touches the real home)"
  (cd "$root/backend" && BELLHOP_STORE=memory BELLHOP_SEED_FILE=scenarios/empty.json exec uv run uvicorn bellhop.api.main:app --host 127.0.0.1 --port "$demo_port" --log-level warning) &
  pids+=($!)
  for _ in $(seq 1 60); do
    curl -fs "${demo_api}/health" >/dev/null 2>&1 && break
    sleep 0.5
  done
  curl -fs "${demo_api}/health" >/dev/null || { echo "demo backend did not start" >&2; exit 1; }
  echo "simulator: filling the demo backend with the example home"
  (cd "$root/simulator" && exec uv run bellhop-sim --base-url "$demo_api" run --seed-home --rate 1 --speed 1.5 --nurse-delay 60 "$@") &
  pids+=($!)
elif [ "$mode" = mock ]; then
  echo "simulator: seeding the example home, then ringing bells"
  (cd "$root/simulator" && exec uv run bellhop-sim --base-url "$api" run --seed-home "$@") &
  pids+=($!)
else
  echo "empty home: nothing is simulated"
fi

echo "frontend on http://localhost:${frontend_port}"
(cd "$root/frontend" && VITE_BELLHOP_API_URL="$api" VITE_BELLHOP_DEMO_URL="$demo_api" exec npm run dev -- --port "$frontend_port" --strictPort) &
pids+=($!)

wait
