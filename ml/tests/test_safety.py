import signal
import subprocess
import sys
import textwrap
import time

import pytest

from rover import safety


class Registrar:
    def __init__(self):
        self.handlers = {}

    def __call__(self, sig, handler):
        self.handlers[sig] = handler


def test_registers_default_signals():
    reg = Registrar()
    safety.install_motors_off(lambda: None, registrar=reg)
    assert set(reg.handlers) == {signal.SIGTERM, signal.SIGINT, signal.SIGHUP}


def test_handler_stops_once_then_exits():
    calls = []
    reg = Registrar()
    safety.install_motors_off(lambda: calls.append(1), registrar=reg)
    for sig in (signal.SIGTERM, signal.SIGINT):
        with pytest.raises(SystemExit) as e:
            reg.handlers[sig](sig, None)
        assert e.value.code == 0
    assert calls == [1]


def test_handler_survives_stop_exception():
    def boom():
        raise RuntimeError("i2c")

    reg = Registrar()
    safety.install_motors_off(boom, registrar=reg)
    with pytest.raises(SystemExit) as e:
        reg.handlers[signal.SIGTERM](signal.SIGTERM, None)
    assert e.value.code == 0


def test_context_manager_runs_on_normal_exit_and_exception():
    calls = []
    with safety.motors_off_on_exit(lambda: calls.append(1)):
        pass
    assert calls == [1]
    with pytest.raises(ValueError):
        with safety.motors_off_on_exit(lambda: calls.append(2)):
            raise ValueError
    assert calls == [1, 2]


def test_context_manager_swallows_stop_error_keeps_original():
    def boom():
        raise RuntimeError("stop failed")

    with pytest.raises(ValueError):
        with safety.motors_off_on_exit(boom):
            raise ValueError


def test_real_sigterm_runs_stop(tmp_path):
    marker = tmp_path / "stopped"
    ready = tmp_path / "ready"
    code = textwrap.dedent(
        f"""
        import time
        from pathlib import Path
        from rover import safety
        safety.install_motors_off(lambda: Path({str(marker)!r}).write_text("x"))
        Path({str(ready)!r}).write_text("r")
        time.sleep(30)
        """
    )
    p = subprocess.Popen([sys.executable, "-c", code])
    try:
        deadline = time.time() + 20
        while not ready.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=10) == 0
    finally:
        if p.poll() is None:
            p.kill()
    assert marker.read_text() == "x"


def test_exit_cleanly_on_signals_registers_and_exits_zero():
    reg = Registrar()
    safety.exit_cleanly_on_signals(registrar=reg)
    assert set(reg.handlers) == {signal.SIGTERM, signal.SIGINT, signal.SIGHUP}
    with pytest.raises(SystemExit) as e:
        reg.handlers[signal.SIGTERM](signal.SIGTERM, None)
    assert e.value.code == 0


def test_real_sigterm_unwinds_finally_blocks(tmp_path):
    marker = tmp_path / "closed"
    ready = tmp_path / "ready"
    code = textwrap.dedent(
        f"""
        import time
        from pathlib import Path
        from rover import safety
        safety.exit_cleanly_on_signals()
        Path({str(ready)!r}).write_text("r")
        try:
            time.sleep(30)
        finally:
            Path({str(marker)!r}).write_text("camera closed")
        """
    )
    p = subprocess.Popen([sys.executable, "-c", code])
    try:
        deadline = time.time() + 20
        while not ready.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=10) == 0
    finally:
        if p.poll() is None:
            p.kill()
    assert marker.read_text() == "camera closed"
