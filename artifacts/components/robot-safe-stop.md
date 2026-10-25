# Safe-stop checklist (before every demo)

Do all of this with the car lifted on a box, wheels free, unless stated. Tick each line.

- [ ] Watchdog: start a move (`POST /go_to`), then stop sending commands. Wheels stop by themselves
      within the watchdog time.
- [ ] /stop under load: during a move, `POST /stop` (or `scripts/motors_off.py`). Wheels stop at once,
      mode goes idle.
- [ ] SIGTERM: during a move, `sudo systemctl stop bellhop-drive`. Wheels stop, service exits within 5 s.
      Also `sudo systemctl restart bellhop-drive` and confirm the wheels never twitch on start.
- [ ] Exception: force an exception in the drive loop (for example unplug the I2C battery board or raise
      from a test hook). Motors are zeroed, process restarts via systemd.
- [ ] Sensor errors: cover or unplug the ultrasonic sensor. The car fails safe (stops, does not drive
      blind). Repeat for a camera failure with `bellhop-vision` stopped.
- [ ] Low battery: with a low battery reading the robot refuses to start a move.
- [ ] Power: `scripts/smoke.sh` shows `power_health` not fault; no undervoltage flag under motor load.
- [ ] Wi-Fi: walk to the far end of the route. Check RSSI, and that a dropped link leads to a stop
      (watchdog), not a runaway.
- [ ] Physical kill switch: it cuts motor power. Test it while moving. Named person holding it during
      the demo: ______________________ (a person, not "the team").
