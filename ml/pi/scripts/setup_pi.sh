#!/usr/bin/env bash
# Pi only. Sets up the robot's Python environment, car drivers, models and smoke test.
# Safe to re-run.
#   (Pi) cd ~/ml && bash scripts/setup_pi.sh
set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf '\n== %s\n' "$1"; }

step "1/7 Check: 64-bit Raspberry Pi OS, Python 3.11 (Bookworm) or 3.13 (Trixie), memory"
if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "This script is for the Pi (64-bit Raspberry Pi OS). On the Mac run: uv sync"
  exit 1
fi
system_python=$(/usr/bin/python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
case "$system_python" in
  3.11 | 3.13) ;;
  *)
    echo "Found /usr/bin/python3 $system_python. This project supports Python 3.11 (Raspberry Pi OS"
    echo "Bookworm) and 3.13 (Trixie). apt's picamera2 is built for the system Python, so the venv"
    echo "must use it: flash a current 64-bit Raspberry Pi OS."
    exit 1
    ;;
esac
echo "ok: aarch64, system Python $system_python"
# uv reads .python-version; the Mac's 3.11 would make a bare 'uv run' rebuild a venv that
# cannot see apt's picamera2. Pin it to the system Python (re-run this script after any rsync).
echo "$system_python" >.python-version
mem_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
if ((mem_kb < 3000000)); then
  echo "WARNING: only $((mem_kb / 1024)) MB RAM (under 3 GB). Run the processes one at a time:"
  echo "  vision (YOLO + camera) and speech (Moonshine + Piper + fastembed) together can run out"
  echo "  of memory. Start rover.vision and rover.speech in separate terminals, check 'free -m'"
  echo "  between them, and keep rover.drive (small) always on. See artifacts/components/robot-deploy.md."
  [[ -n "$(swapon --noheadings 2>/dev/null)" ]] || echo "  No swap is active; a few GB of swap avoids OOM kills during uv sync."
fi

step "2/7 apt: picamera2 (camera), PortAudio (mic and speaker), libGL + GLib (opencv's cv2), car I/O"
sudo apt-get update
# Pick the first name in a list that apt can actually install (package names differ between
# Bookworm and Trixie, e.g. libglib2.0-0 became libglib2.0-0t64).
pick_pkg() {
  local name cand
  for name in "$@"; do
    cand=$(apt-cache policy "$name" 2>/dev/null | awk '/Candidate:/ {print $2}')
    if [[ -n "$cand" && "$cand" != "(none)" ]]; then
      echo "$name"
      return 0
    fi
  done
  return 1
}
# smbus: motor board and battery (I2C); gpiozero + lgpio: ultrasonic on a Pi 5; spidev: LEDs
# python3-venv: needed by 'python3 -m venv' (the uv fallback install below)
packages=(git python3-venv)
for want in "python3-picamera2" "libportaudio2" "libgl1" "libglib2.0-0t64 libglib2.0-0" \
  "python3-smbus" "python3-lgpio" "python3-gpiozero" "python3-spidev"; do
  # shellcheck disable=SC2086
  if pkg=$(pick_pkg $want); then
    packages+=("$pkg")
  else
    echo "WARNING: no apt package found for: $want (skipped; see the Pi section of the README)"
  fi
done
sudo apt-get install -y --no-install-recommends "${packages[@]}"
echo "success: every package shows as 'already the newest version' on a re-run"

step "3/7 I2C + SPI on, Freenove's car drivers (imported from their repo, never copied)"
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0
[[ -e /dev/i2c-1 ]] || echo "WARNING: /dev/i2c-1 missing: reboot (sudo reboot), then re-run this script"
[[ -e /dev/spidev0.0 ]] || echo "WARNING: /dev/spidev0.0 missing: reboot for the SPI LEDs"
freenove="$HOME/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi"
if [[ ! -f "$freenove/Code/Server/motor.py" ]]; then
  git clone --depth 1 https://github.com/Freenove/Freenove_4WD_Smart_Car_Kit_for_Raspberry_Pi "$freenove"
fi
echo "success: $freenove/Code/Server has motor.py (FREENOVE_DIR in .env if it lives elsewhere)"
if pgrep -af "python[0-9.]* .*main\.py"; then
  echo "WARNING: a 'main.py' is running (above). If it is Freenove's server, stop it and its autostart."
fi
echo "Freenove's own server must not run: it fights rover.vision for the camera and"
echo "rover.drive for the motor board."

step "4/7 uv (Python package manager)"
# Prefer the official installer when curl exists. Otherwise install uv from PyPI into its own
# venv (~/.uvtool) and link it into ~/.local/bin. No sudo, nothing system-wide.
export PATH="$HOME/.local/bin:$PATH"
uvtool="$HOME/.uvtool"
if command -v uv >/dev/null 2>&1; then
  if [[ -x "$uvtool/bin/pip" && "$(readlink -f "$(command -v uv)")" == "$uvtool/bin/uv" ]]; then
    "$uvtool/bin/pip" install --quiet --upgrade uv || echo "could not upgrade uv in $uvtool"
  else
    # an old uv can't read this uv.lock
    uv self update || echo "could not self-update uv (installed another way); update it if uv sync rejects uv.lock"
  fi
elif command -v curl >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # newer installers write no ~/.local/bin/env, so put the install dir on PATH directly
  export PATH="$HOME/.local/bin:$PATH"
else
  echo "curl not found: installing uv from PyPI into $uvtool"
  [[ -x "$uvtool/bin/pip" ]] || { rm -rf "$uvtool"; /usr/bin/python3 -m venv "$uvtool"; }
  "$uvtool/bin/pip" install --quiet --upgrade uv
  mkdir -p "$HOME/.local/bin"
  ln -sf "$uvtool/bin/uv" "$HOME/.local/bin/uv"
  ln -sf "$uvtool/bin/uvx" "$HOME/.local/bin/uvx"
fi
hash -r
echo "success: $(uv --version)  (open a new shell, or: export PATH=\"\$HOME/.local/bin:\$PATH\")"

step "5/7 .venv that can also see apt's picamera2, smbus, gpiozero and spidev"
# A missing venv, one copied from the Mac, or one on another Python is rebuilt with access to the
# system packages.
if ! grep -qs "include-system-site-packages = true" .venv/pyvenv.cfg \
  || [[ "$(.venv/bin/python -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null)" != "$system_python" ]]; then
  rm -rf .venv
  uv venv --system-site-packages --python /usr/bin/python3 .venv
fi
echo "success: .venv/pyvenv.cfg says include-system-site-packages = true"

step "6/7 uv sync --frozen (exact versions from uv.lock, CPU-only torch; torch takes a while)"
# --python keeps uv on the system Python (no download of another one) and on this venv.
# On Python 3.13 numpy 2.x is installed into .venv; it shadows apt's numpy (venv wins on sys.path).
# A weak venue Wi-Fi times out when uv pulls many big wheels at once (it did: numpy after 30 s).
# Fewer parallel downloads and a long timeout; downloads are cached, so a re-run resumes.
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-600}"
export UV_CONCURRENT_DOWNLOADS="${UV_CONCURRENT_DOWNLOADS:-2}"
for attempt in 1 2 3 4; do
  uv sync --frozen --python .venv/bin/python && break
  [[ $attempt -lt 4 ]] || { echo "FAIL: uv sync failed 4 times; check the Wi-Fi and re-run this script"; exit 1; }
  echo "uv sync failed (attempt $attempt of 4), retrying in 10 s; finished downloads are cached"
  sleep 10
done
echo "success: no errors above; nothing is downloaded on a re-run"

step "7/7 Models, then the smoke test"
if [[ ! -f models/yolo26n_ncnn_model/model.ncnn.param ]]; then
  echo "WARNING: models/yolo26n_ncnn_model is missing. Copy it from the Mac:"
  echo "  (Mac) scp -r models/yolo26n_ncnn_model pi@<pi>:~/ml/models/"
fi
[[ -f .env ]] || { cp .env.example .env; echo "made .env from .env.example: fill in keys and BELLHOP_API"; }
# gpiozero must use lgpio on a Pi 5 (RPi.GPIO does not work there)
grep -qs '^GPIOZERO_PIN_FACTORY=' .env || echo "GPIOZERO_PIN_FACTORY=lgpio" >>.env
grep -qs '^GPIOZERO_PIN_FACTORY=' /etc/bellhop/env 2>/dev/null \
  || echo "systemd units read /etc/bellhop/env: add the line GPIOZERO_PIN_FACTORY=lgpio there too"
uv run --python .venv/bin/python python scripts/download_models.py --skip-yolo
uv run --python .venv/bin/python python scripts/smoke.py
echo
echo "Done. Success looks like 'models OK' and 'SMOKE OK' above, and throttled=0x0."
echo "Next (Pi): in .env set BELLHOP_API=http://<laptop-tailscale-ip>:8000 and the API keys,"
echo "then check the car with: uv run python scripts/check_car.py (--wheels only with the car lifted)."
