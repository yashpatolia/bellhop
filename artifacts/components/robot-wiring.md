# Wiring status

`rover/power.py` and `rover/safety.py` are wired in and tested. Nothing is left to wire except the
Pi-only checks at the bottom.

- [x] `rover/status.py`: the heartbeat reads `power` and `wifi_rssi_dbm` from the drive server's
      `GET /snapshot` (the controller reads `vcgencmd`/`iw` through `rover.power`, cached for
      `POWER_CACHE_S`, never raising). `power_health == "fault"` (undervoltage now) reports status
      `fault`; `warn` reports normally. Warn and fault are logged as `status.power` (flags and RSSI).
      `PUT /robots/{id}` still sends only `status`, `battery` and `room`: the backend contract
      (`RobotReport`) accepts nothing else, so the extra power data stays in the logs and in
      `/snapshot` (`drive/openapi.yaml` documents both fields).
- [x] `rover/drive/__main__.py`: `serve()` installs `safety.install_motors_off` (SIGTERM, SIGINT,
      SIGHUP: wheels stopped, LED idle, log line `drive: motors off`, exit 0) and runs the same
      stop in a `finally` on any other exit, then closes the car. Tested with an injectable
      registrar and with the real process (`--fake`, SIGTERM, exit 0).
- [x] Speech: SIGTERM/SIGINT/SIGHUP set the LED idle and stop the wheels (`speech/ledguard.py`),
      the mic and Flux are closed in a `finally` even if setup fails after the mic opened.
- [x] Vision: `safety.exit_cleanly_on_signals()` turns SIGTERM into a clean exit so the camera
      and socket are closed in the existing `finally` (Python's default SIGTERM skips it).
- [x] Stuck LED if the backend dies mid-visit (only the backend ever sends `idle`):
      - speech re-sends a lit LED every `LED_KEEPALIVE_S` (`LED_HOLD_S / 4`) for as long as the
        visit lives (`ledguard.visit_guard`), so an emergency is never lowered during a live visit;
      - when the visit ends normally it POSTs `/led idle` only (a `/stop` would cancel the drive
        home); when it ends abnormally (crash, SIGTERM) it also POSTs `/stop`;
      - the drive `Controller` returns any non-idle LED to idle when no `/led` command has arrived
        for `LED_HOLD_S` (default 120 s, env `LED_HOLD_S`), so a SIGKILLed speech process or a
        dead Pi-side visit cannot leave it lit. Injectable clock in tests.
      - e2e: `dev/e2e/scenario_backend_dies.py` (not part of `run.py`; the one-line change to fold
        it in is in its docstring).
- [ ] Optional, not done: refuse moves while `power_health(...) == "fault"`.
- [ ] Not done on purpose: `bellhop-status` stays inside the speech process (no `__main__`).
- [ ] Pi only: re-run `scripts/smoke.sh` and the SIGTERM lines in `SAFE_STOP_CHECKLIST.md`; confirm
      `vcgencmd` and `iw` output on the real board; confirm the LED expires on the real strip.
