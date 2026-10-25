# Deploying the robot to the Pi

Layout on the Pi: `ml/pi` is synced to `/home/pi/ml` (user `pi`), with its venv at `/home/pi/ml/.venv`
(created by `scripts/setup_pi.sh`). If you use another path or user, edit `User=`,
`WorkingDirectory=`, `ExecStart=` and `ExecStopPost=` in the unit files.

The venv uses the Pi's system Python (3.13 on Trixie, 3.11 on Bookworm) with `--system-site-packages`, so
rsync must not overwrite `.python-version` (see `artifacts/components/ml.md`). On a 2 GB Pi do not run vision and speech
at the same time unless `free -m` shows headroom; `setup_pi.sh` warns about this.

## Units

| Unit | Command |
|------|---------|
| `bellhop-drive.service` | `python -m rover.drive` (motors, server on :8080; SIGTERM stops the wheels and sets the LED idle; ExecStopPost forces /stop) |
| `bellhop-speech.service` | `python -m rover.speech` (starts after drive; SIGTERM sets the LED idle and stops the wheels) |
| `bellhop-vision.service` | `python -m rover.vision` (starts after drive; SIGTERM closes the camera) |

All: `Restart=always`, `RestartSec=2`, `KillSignal=SIGTERM`, `TimeoutStopSec=5`,
`EnvironmentFile=/etc/bellhop/env`.

## Install

1. Secrets file (never committed). Put `BELLHOP_API`, `BELLHOP_API_KEY`, `ROBOT_ID`, Deepgram and
   Anthropic keys, etc. in it as `KEY=value` lines (no `export`, no quotes needed):

       sudo install -d -m 755 /etc/bellhop
       sudo install -m 600 -o root -g root /dev/null /etc/bellhop/env
       sudo nano /etc/bellhop/env

   systemd reads it as root, so mode 600 root is fine.
2. Install and enable the units:

       sudo cp ~/ml/deploy/bellhop-*.service /etc/systemd/system/
       sudo systemctl daemon-reload
       sudo systemctl enable --now bellhop-drive bellhop-speech bellhop-vision

3. Watch logs: `journalctl -fu bellhop-drive -o cat` (same for the other units).
4. Run `bash ~/ml/scripts/smoke.sh`, then work through `SAFE_STOP_CHECKLIST.md` with the car lifted.

Update from the Mac: `PI_HOST=pi@<host> bash deploy/push.sh` (refuses to run without `PI_HOST`).

Note on ExecStopPost: `scripts/motors_off.py` POSTs /stop to the drive server. If the drive process
is already dead the post cannot reach anything, so the real guarantee is the SIGTERM handler
(`rover.safety`, wired in `rover/drive/__main__.py`, see `WIRING.md`) plus the drive watchdog.

Optional in `/etc/bellhop/env`: `LED_HOLD_S` (default 120). A lit LED that nothing has refreshed for
that long goes back to idle, so a dead backend cannot leave `emergency` on. The units themselves
are unchanged: same entry points, `KillSignal=SIGTERM`, `TimeoutStopSec=5` (the speech release
makes two HTTP calls of at most 2 s each).

## Wi-Fi power save (avoids latency spikes on the demo network)

Per connection, persistent across reboots (`2` = disable):

    nmcli connection modify "<connection name>" 802-11-wireless.powersave 2
    sudo nmcli connection up "<connection name>"

List names with `nmcli connection show`. Verify:

    iw dev wlan0 get power_save      # expect: Power save: off

`iw` documents the form `iw dev <devname> get power_save`; `iw dev wlan0 get power_save` is the
spelling to use. The alternative `iw dev wlan0 get power-save` is not documented, do not use it.
UNVERIFIED: neither nmcli nor iw exists on the build machine, so none of these commands were run.

## Validation status

`systemd-analyze verify` was run on the build machine: no syntax or key errors, only the expected
"not executable" for `/home/pi/ml/.venv/bin/python`, which exists only on the Pi. Not run on the Pi.
