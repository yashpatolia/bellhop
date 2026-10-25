#!/usr/bin/env bash
# Run the entire Pi side in one terminal: camera/markers, marker-guided drive, and speech.
# Ctrl-C stops all three; rover.drive's signal handler stops wheel motors before it exits.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python="$root/.venv/bin/python"
log_dir="$root/runs"
pids=()

stop() {
  trap - INT TERM EXIT
  echo "rover: stopping"
  curl -fsS -X POST http://127.0.0.1:8080/stop >/dev/null 2>&1 || true
  for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap stop INT TERM EXIT

test -x "$python" || { echo "rover: missing $python" >&2; exit 1; }
mkdir -p "$log_dir"
# The laptop launcher waits for this run-specific marker before declaring the full stack ready.
# Remove an earlier run's marker before any component starts.
rm -f "$log_dir/rover.ready"

# Keep the optional Jev key out of source control and shell history. config.load_dotenv() preserves
# this inherited value over an empty TYPESAFE_API_KEY= line in .env.
if ! grep -q '^TYPESAFE_API_KEY=.\+' "$root/.env" 2>/dev/null; then
  read -r -s -p "TypeSafe Jev key (Enter to disable Jev): " TYPESAFE_API_KEY
  echo
  if [ -n "$TYPESAFE_API_KEY" ]; then export TYPESAFE_API_KEY; fi
fi

# A previously foreground-run component owns the camera or drive port. Stop known Bellhop
# processes only; do not kill unrelated system processes.
pkill -f '[r]over.vision' 2>/dev/null || true
pkill -f '[r]over.drive' 2>/dev/null || true
pkill -f '[r]over.speech' 2>/dev/null || true
sleep 1

cd "$root"
"$python" -m rover.vision >"$log_dir/vision.log" 2>&1 &
vision_pid="$!"
pids+=("$vision_pid")
"$python" -m rover.drive --controller >"$log_dir/drive.log" 2>&1 &
pids+=("$!")

for _ in $(seq 1 20); do
  curl -fsS http://127.0.0.1:8080/snapshot >/dev/null 2>&1 && break
  sleep 0.25
done
curl -fsS http://127.0.0.1:8080/snapshot >/dev/null || {
  echo "rover: drive server did not start; see $log_dir/drive.log" >&2
  exit 1
}

# A healthy drive HTTP process alone is not enough: it can otherwise navigate using an old
# JPEG/absent UDP stream after camera or optional-model startup failed.  Do not claim the Pi is
# ready until this run has produced a fresh frame.  The stale file check deliberately rejects a
# frame left by any previous process.
vision_ready=false
for _ in $(seq 1 40); do
  if ! kill -0 "$vision_pid" 2>/dev/null; then
    echo "rover: vision stopped during startup; see $log_dir/vision.log" >&2
    tail -n 40 "$log_dir/vision.log" >&2 || true
    exit 1
  fi
  if [ -f "$log_dir/latest.jpg" ]; then
    frame_mtime="$(stat -c %Y "$log_dir/latest.jpg" 2>/dev/null || true)"
    now="$(date +%s)"
    if [ -n "$frame_mtime" ] && [ $((now - frame_mtime)) -le 3 ]; then
      vision_ready=true
      break
    fi
  fi
  sleep 0.25
done
if [ "$vision_ready" != true ]; then
  echo "rover: vision did not produce a fresh frame; see $log_dir/vision.log" >&2
  tail -n 40 "$log_dir/vision.log" >&2 || true
  exit 1
fi

touch "$log_dir/rover.ready"
echo "rover: vision + marker-guided drive ready; speech is waiting for an assigned call"
echo "rover: Ctrl-C stops camera, speech and motors"
"$python" -m rover.speech
