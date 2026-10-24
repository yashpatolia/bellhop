import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from rover.drive import __main__ as drive_main
from rover.drive.car import FakeCar
from rover.drive.control import Controller
from rover.drive.navigator import SimNavigator

PI_DIR = Path(__file__).resolve().parents[1] / "pi"


class RecordingCar(FakeCar):
    def __init__(self):
        super().__init__()
        self.calls = []

    def stop(self):
        self.calls.append("stop")

    def led(self, state):
        self.calls.append(f"led:{state}")

    def close(self):
        self.calls.append("close")


class FakeHttpd:
    def __init__(self, during=None):
        self.during = during
        self.closed = False

    def serve_forever(self):
        if self.during:
            self.during()

    def server_close(self):
        self.closed = True


class Registrar:
    def __init__(self):
        self.handlers = {}

    def __call__(self, sig, handler):
        self.handlers[sig] = handler


def make():
    car = RecordingCar()
    ctl = Controller(car, SimNavigator(), power_reader=lambda: None)
    car.calls.clear()
    return car, ctl


def test_sigterm_during_serving_stops_motors_leds_idle_and_closes_the_car(capsys):
    car, ctl = make()
    reg = Registrar()
    ctl.set_led("emergency")
    car.calls.clear()
    httpd = FakeHttpd(lambda: reg.handlers[signal.SIGTERM](signal.SIGTERM, None))
    with pytest.raises(SystemExit) as e:
        drive_main.serve(ctl, car, httpd, registrar=reg)
    assert e.value.code == 0
    assert car.calls == ["stop", "led:idle", "close"]
    assert httpd.closed
    assert ctl.snapshot()["led"] == "idle"
    assert "motors off" in capsys.readouterr().out


def test_handlers_cover_term_int_hup():
    car, ctl = make()
    reg = Registrar()
    drive_main.serve(ctl, car, FakeHttpd(), registrar=reg)
    assert set(reg.handlers) == {signal.SIGTERM, signal.SIGINT, signal.SIGHUP}


def test_normal_return_and_crash_also_stop_the_motors():
    car, ctl = make()
    drive_main.serve(ctl, car, FakeHttpd(), registrar=Registrar())
    assert car.calls == ["stop", "led:idle", "close"]

    car, ctl = make()

    def crash():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        drive_main.serve(ctl, car, FakeHttpd(crash), registrar=Registrar())
    assert car.calls == ["stop", "led:idle", "close"]


def test_keyboard_interrupt_is_a_clean_exit():
    car, ctl = make()

    def interrupt():
        raise KeyboardInterrupt

    drive_main.serve(ctl, car, FakeHttpd(interrupt), registrar=Registrar())
    assert car.calls == ["stop", "led:idle", "close"]


def test_real_drive_process_exits_cleanly_on_sigterm_and_logs_motors_off(tmp_path):
    out = tmp_path / "drive.out"
    port = _free_port()
    with out.open("wb") as sink:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "rover.drive",
                "--fake",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=PI_DIR,
            stdout=sink,
            stderr=subprocess.STDOUT,
            env={**os.environ, "ROVER_LOG": ""},
        )
    try:
        _wait_up(f"http://127.0.0.1:{port}/snapshot", proc)
        httpx.post(f"http://127.0.0.1:{port}/led", json={"state": "emergency"}, timeout=3)
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    text = out.read_text()
    assert "motors off" in text
    assert "Traceback" not in text


def _free_port():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_up(url, proc):
    deadline = time.time() + 30
    while time.time() < deadline:
        assert proc.poll() is None, "drive exited early"
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.1)
    raise AssertionError("drive did not come up")
