#!/usr/bin/env bash
# Pi only. Sets up the robot's Python environment, car drivers, models and smoke test.
# Safe to re-run.
#   (Pi) cd ~/ml && bash scripts/setup_pi.sh
set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf '\n== %s\n' "$1"; }

step "1/7 Check: Raspberry Pi OS Bookworm 64-bit (Python 3.11)"
if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "This script is for the Pi (64-bit Raspberry Pi OS). On the Mac run: uv sync"
  exit 1
fi
system_python=$(/usr/bin/python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
if [[ "$system_python" != "3.11" ]]; then
  echo "Found /usr/bin/python3 $system_python. This project pins Python 3.11 and apt's picamera2"
  echo "is built for the system Python, so it needs Raspberry Pi OS Bookworm (Python 3.11)."
  exit 1
fi
echo "ok: aarch64, system Python $system_python"

step "2/7 apt: picamera2 (camera), PortAudio (mic and speaker), libGL + GLib (opencv's cv2), car I/O"
sudo apt-get update
# smbus: motor board and battery (I2C); gpiozero + lgpio: ultrasonic on a Pi 5; spidev: LEDs
sudo apt-get install -y --no-install-recommends python3-picamera2 libportaudio2 libgl1 libglib2.0-0 \
  python3-smbus python3-lgpio python3-gpiozero python3-spidev git
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
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # shellcheck disable=SC1091
  source "$HOME/.local/bin/env"
else
  # an old uv can't read this uv.lock
  uv self update || echo "could not self-update uv (installed another way); update it if uv sync rejects uv.lock"
fi
echo "success: $(uv --version)"

step "5/7 .venv that can also see apt's picamera2, smbus, gpiozero and spidev"
# A missing venv, or one copied from the Mac, is rebuilt with access to the system packages.
if ! grep -qs "include-system-site-packages = true" .venv/pyvenv.cfg \
  || ! .venv/bin/python -c "" >/dev/null 2>&1; then
  rm -rf .venv
  uv venv --system-site-packages --python /usr/bin/python3 .venv
fi
echo "success: .venv/pyvenv.cfg says include-system-site-packages = true"

step "6/7 uv sync --frozen (exact versions from uv.lock, CPU-only torch; torch takes a while)"
uv sync --frozen
echo "success: no errors above; nothing is downloaded on a re-run"

step "7/7 Models, then the smoke test"
if [[ ! -f models/yolo26n_ncnn_model/model.ncnn.param ]]; then
  echo "WARNING: models/yolo26n_ncnn_model is missing. Copy it from the Mac:"
  echo "  (Mac) scp -r models/yolo26n_ncnn_model pi@<pi>:~/ml/models/"
fi
[[ -f .env ]] || { cp .env.example .env; echo "made .env from .env.example: fill in keys and BELLHOP_API"; }
uv run python scripts/download_models.py --skip-yolo
uv run python scripts/smoke.py
echo
echo "Done. Success looks like 'models OK' and 'SMOKE OK' above, and throttled=0x0."
echo "Next (Pi): in .env set BELLHOP_API=http://<laptop-tailscale-ip>:8000 and the API keys,"
echo "then check the car with: uv run python scripts/check_car.py (--wheels only with the car lifted)."
