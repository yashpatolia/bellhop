"""Run the robot server: python -m rover.drive [--fake] [--port N]"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from collections.abc import Callable

from rover import config, obslog, safety
from rover.drive import DRIVE_TIMEOUT_S, WATCHDOG_S
from rover.drive.car import open_car
from rover.drive.control import Controller, run_loop
from rover.drive.navigator import SimNavigator
from rover.drive.server import make_server


def motors_off(ctl: Controller) -> None:
    """Wheels stopped and the LED back to idle: what every exit path leaves behind."""
    ctl.stop()
    ctl.set_led("idle")
    print("drive: motors off", flush=True)


def serve(
    ctl: Controller,
    car: object,
    httpd: object,
    registrar: Callable[..., object] = signal.signal,
) -> None:
    """Serve until stopped. SIGTERM, SIGINT and SIGHUP stop the motors and exit 0; so does any
    other way out (a crash, Ctrl-C). Signal handlers can only be installed from the main thread."""
    motors_stop = safety.install_motors_off(lambda: motors_off(ctl), registrar=registrar)
    stop = threading.Event()
    threading.Thread(target=run_loop, args=(ctl, stop), daemon=True).start()
    try:
        httpd.serve_forever()  # type: ignore[attr-defined]
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        motors_stop()
        httpd.server_close()  # type: ignore[attr-defined]
        car.close()  # type: ignore[attr-defined]


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m rover.drive")
    parser.add_argument("--fake", action="store_true", help="use FakeCar, no hardware")
    parser.add_argument("--port", type=int, default=config.DRIVE_PORT)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument(
        "--travel-s",
        type=float,
        default=SimNavigator.TRAVEL_S,
        help="simulated drive time to a room (testing slow drives)",
    )
    parser.add_argument("--watchdog-s", type=float, default=WATCHDOG_S)
    parser.add_argument("--drive-timeout-s", type=float, default=DRIVE_TIMEOUT_S)
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # logs piped to a file survive a kill
    obslog.configure("drive")

    car = open_car(args.fake)
    ctl = Controller(
        car,
        SimNavigator(travel_s=args.travel_s),
        watchdog_s=args.watchdog_s,
        drive_timeout_s=args.drive_timeout_s,
    )
    httpd = make_server(ctl, args.host, args.port)
    print(f"drive: serving on {args.host}:{args.port} ({type(car).__name__})", flush=True)
    serve(ctl, car, httpd)


if __name__ == "__main__":
    main()
