"""Run the robot server: python -m rover.drive [--fake] [--port N]"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from collections.abc import Callable

from rover import config, obslog, safety
from rover.drive import DRIVE_TIMEOUT_S, WATCHDOG_S
from rover.drive.car import FakeCar, RealCar, open_car
from rover.drive.control import Controller, run_loop
from rover.drive.manual import ManualJoystick
from rover.drive.navigator import MarkerNavigator, SimNavigator
from rover.drive.server import make_server
from rover.drive.vision import VisionReceiver


def motors_off(ctl: Controller) -> None:
    """Wheels stopped and the LED back to idle: what every exit path leaves behind."""
    ctl.stop()
    ctl.set_led("idle")
    print("drive: motors off", flush=True)


def head_test(car: FakeCar | RealCar, sleep: Callable[[float], None] = time.sleep) -> None:
    """Exercise only camera-head servos. Wheels are stopped before, during and after the sweep."""
    # Keep this test separate from Controller so it cannot activate any navigation or HTTP path.
    car.stop()
    print("head-test: wheels stopped; sweeping configured camera positions", flush=True)
    for tilt in config.HEAD_SCAN_TILTS:
        for pan in config.HEAD_SCAN_PANS:
            car.look_at(pan, tilt)
            print(f"head-test: pan={pan} tilt={tilt}", flush=True)
            sleep(config.HEAD_SCAN_DWELL_S)
    car.look_ahead()
    car.stop()
    print("head-test: complete; wheels stopped", flush=True)


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
    parser.add_argument(
        "--controller",
        action="store_true",
        help="enable the optional deadman-gated /dev/input/js* manual backup controller",
    )
    parser.add_argument(
        "--head-test",
        action="store_true",
        help="sweep only the camera head, with wheel motors stopped throughout",
    )
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # logs piped to a file survive a kill
    obslog.configure("drive")

    car = open_car(args.fake)
    if args.head_test:
        try:
            head_test(car)
        finally:
            car.stop()
            car.close()
        return
    vision = VisionReceiver()
    vision.start()
    manual: ManualJoystick | None = None
    try:
        navigator = SimNavigator(travel_s=args.travel_s) if args.fake else MarkerNavigator(vision)
        ctl = Controller(
            car,
            navigator,
            watchdog_s=args.watchdog_s,
            drive_timeout_s=args.drive_timeout_s,
        )
        if args.controller:
            manual = ManualJoystick(ctl)
            manual.start()
        httpd = make_server(ctl, args.host, args.port)
        kind = "simulated" if args.fake else "marker-guided"
        print(
            f"drive: serving on {args.host}:{args.port} ({type(car).__name__}, {kind})",
            flush=True,
        )
        serve(ctl, car, httpd)
    finally:
        if manual is not None:
            manual.close()
        vision.close()


if __name__ == "__main__":
    main()
