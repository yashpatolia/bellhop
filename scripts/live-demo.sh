#!/usr/bin/env bash
# One-command live demo launcher. It syncs the Pi, starts the laptop backend/frontend, then
# runs the complete rover stack over SSH. Ctrl-C stops the local processes and the remote rover.
#
# BELLHOP_PI_HOST=pi@100.73.9.29 BELLHOP_PI_IP=100.73.9.29 bash scripts/live-demo.sh
set -euo pipefail

: "${BELLHOP_PI_HOST:?set BELLHOP_PI_HOST, e.g. pi@100.73.9.29}"
: "${BELLHOP_PI_IP:?set BELLHOP_PI_IP, e.g. 100.73.9.29}"
# Optional ed25519 private key. It avoids password prompts without placing a password in source,
# shell history or the process list. See ml/README.md for one-time setup.
pi_ssh_key="${BELLHOP_PI_SSH_KEY:-}"
ssh_cmd=(ssh)
if [ -n "$pi_ssh_key" ]; then
  [ -r "$pi_ssh_key" ] || { echo "live-demo: cannot read BELLHOP_PI_SSH_KEY" >&2; exit 1; }
  ssh_cmd+=(-i "$pi_ssh_key" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=10)
fi
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
api="http://127.0.0.1:8000"
# WSL can reach the Pi by SSH while direct TCP to its tailnet port is filtered or intermittently
# unavailable. The backend therefore commands the Pi through a loopback SSH tunnel by default.
pi_tunnel_port="${BELLHOP_PI_TUNNEL_PORT:-18080}"
# `auto` keeps a local browser on loopback while a touchscreen loaded over Tailscale uses the
# laptop's tailnet host. Override only for a separately hosted backend.
dashboard_api="${BELLHOP_DASHBOARD_API_URL:-auto}"
pids=()

stop() {
  trap - INT TERM EXIT
  echo
  echo "live-demo: stopping laptop services"
  for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap stop INT TERM EXIT

echo "live-demo: checking Pi SSH..."
"${ssh_cmd[@]}" "$BELLHOP_PI_HOST" true
if [ "${BELLHOP_SKIP_SYNC:-0}" = "1" ]; then
  echo "live-demo: Pi source sync skipped; using the last deployed rover code"
else
  echo "live-demo: Pi SSH ready; syncing source..."
  rsync -az --info=progress2 --timeout=30 --delete \
    --exclude '/.venv' --exclude '/.env' --exclude '/.python-version' \
    --exclude '/models' --exclude '/runs' --exclude '__pycache__' --exclude '*.pyc' \
    -e "${ssh_cmd[*]}" "$root/ml/pi/" "$BELLHOP_PI_HOST:~/ml/"
  echo "live-demo: Pi source synced"
fi

# Keep the Pi drive server private to a dedicated tunnel.  Do not multiplex it with the remote
# rover session: a ControlMaster can leave a locally listening but non-forwarding socket after a
# session drops.  This process is in ``pids`` so the trap reliably closes it on exit.
"${ssh_cmd[@]}" -o ExitOnForwardFailure=yes -N \
  -L "127.0.0.1:${pi_tunnel_port}:127.0.0.1:8080" "$BELLHOP_PI_HOST" </dev/null &
tunnel_pid="$!"
pids+=("$tunnel_pid")
sleep 0.25
if ! kill -0 "$tunnel_pid" 2>/dev/null; then
  echo "live-demo: SSH tunnel could not start" >&2
  wait "$tunnel_pid" || true
  exit 1
fi

# This script owns the demo backend. Stop only the exact prior Bellhop uvicorn command, not an
# arbitrary process on port 8000.
pkill -f '[u]vicorn bellhop.api.main:app' 2>/dev/null || true
(cd "$root/backend" && BELLHOP_SEED_DEMO=1 \
  BELLHOP_ROBOT_URL="http://127.0.0.1:${pi_tunnel_port}" \
  BELLHOP_GATEWAY_TIMEOUT=5 \
  exec .venv/bin/uvicorn bellhop.api.main:app --host 0.0.0.0 --port 8000) &
pids+=("$!")

for _ in $(seq 1 30); do
  curl -fsS "$api/health" >/dev/null 2>&1 && break
  sleep 0.25
done
curl -fsS "$api/health" >/dev/null || { echo "live-demo: backend did not start" >&2; exit 1; }

echo "live-demo: backend ready; starting Pi rover over SSH"
"${ssh_cmd[@]}" "$BELLHOP_PI_HOST" 'rm -f ~/ml/runs/rover.ready'
"${ssh_cmd[@]}" -tt "$BELLHOP_PI_HOST" 'cd ~/ml && bash scripts/run_rover.sh' &
rover_pid="$!"
pids+=("$rover_pid")

# Do not make the dashboard operational until it can traverse the same private tunnel that the
# backend will use and the Pi has confirmed a fresh-frame rover startup.  A listening SSH socket
# or a drive port alone is insufficient: either can survive a failed vision process.
rover_ready=false
for _ in $(seq 1 80); do
  if ! kill -0 "$rover_pid" 2>/dev/null; then
    echo "live-demo: Pi rover exited during startup" >&2
    wait "$rover_pid" || true
    exit 1
  fi
  if curl --max-time 1 -fsS "http://127.0.0.1:${pi_tunnel_port}/snapshot" >/dev/null 2>&1 && \
    "${ssh_cmd[@]}" "$BELLHOP_PI_HOST" 'test -f ~/ml/runs/rover.ready' >/dev/null 2>&1; then
    rover_ready=true
    break
  fi
  sleep 0.25
done
if [ "$rover_ready" != true ]; then
  echo "live-demo: Pi rover/tunnel did not become ready within 20 seconds" >&2
  exit 1
fi
echo "live-demo: Pi rover and tunnel ready"

if [ -x "$root/frontend/node_modules/.bin/vite" ]; then
  (cd "$root/frontend" && VITE_BELLHOP_API_URL="$dashboard_api" exec npm run dev -- --host 0.0.0.0) &
  pids+=("$!")
  echo "live-demo: dashboard on http://127.0.0.1:5173 (API mode: $dashboard_api)"
else
  echo "live-demo: dashboard dependencies absent; robot path remains available"
fi

wait "$rover_pid"
