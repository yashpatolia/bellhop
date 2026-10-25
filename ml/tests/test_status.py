import json
import threading

from rover import obslog
from rover.status import FAULT_AFTER_FAILURES, StatusReporter


class FakeBackend:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def report_robot(self, robot_id, status, battery, room, target):
        if self.fail:
            raise RuntimeError("backend bug")
        self.calls.append((robot_id, status, battery, room, target))
        return {"id": robot_id}


def make(snapshots, backend=None):
    feed = iter(snapshots)
    backend = backend or FakeBackend()
    reporter = StatusReporter(backend, lambda: next(feed), robot_id="robot_1")
    return reporter, backend


def test_idle_snapshot_is_reported():
    reporter, backend = make(
        [{"room": "12", "target": None, "moving": False, "battery": 0.8, "led": "idle"}]
    )
    reporter.report_once()
    assert backend.calls == [("robot_1", "idle", 0.8, "12", None)]


def test_moving_is_busy():
    reporter, backend = make([{"room": "lobby", "target": "210", "moving": True, "battery": 0.5}])
    reporter.report_once()
    assert backend.calls == [("robot_1", "busy", 0.5, "lobby", "210")]


def test_charging_flag_is_charging():
    reporter, backend = make([{"room": "lobby", "moving": False, "battery": 0.2, "charging": True}])
    reporter.report_once()
    assert backend.calls[0][1] == "charging"


def test_missing_keys_are_tolerated():
    reporter, backend = make([{}, {"battery": "junk", "room": 5}])
    reporter.report_once()
    reporter.report_once()
    assert backend.calls == [
        ("robot_1", "idle", None, None, None),
        ("robot_1", "idle", None, None, None),
    ]


def test_server_down_reports_last_known_then_fault():
    good = {"room": "14", "moving": False, "battery": 0.6}
    reporter, backend = make([good] + [None] * FAULT_AFTER_FAILURES)
    reporter.report_once()
    for _ in range(FAULT_AFTER_FAILURES):
        reporter.report_once()
    statuses = [call[1] for call in backend.calls]
    assert statuses == ["idle"] + ["idle"] * (FAULT_AFTER_FAILURES - 1) + ["fault"]
    assert all(call[2:] == (0.6, "14", None) for call in backend.calls)


def test_server_down_from_the_start_is_fault_without_battery():
    reporter, backend = make([None] * FAULT_AFTER_FAILURES)
    for _ in range(FAULT_AFTER_FAILURES):
        reporter.report_once()
    assert backend.calls[-1] == ("robot_1", "fault", None, None, None)


def test_fetcher_or_backend_crash_never_escapes():
    def boom():
        raise OSError("down")

    reporter = StatusReporter(FakeBackend(), boom, robot_id="robot_1")
    reporter.report_once()
    reporter = StatusReporter(FakeBackend(fail=True), lambda: {}, robot_id="robot_1")
    reporter.report_once()


def test_loop_reports_every_interval_until_stopped():
    stop = threading.Event()
    waits = []

    def wait(seconds):
        waits.append(seconds)
        if len(waits) == 3:
            stop.set()
        return stop.is_set()

    backend = FakeBackend()
    reporter = StatusReporter(
        backend, lambda: {"battery": 1.0}, robot_id="robot_1", interval_s=5.0, wait=wait
    )
    reporter.run(stop)
    assert waits == [5.0, 5.0, 5.0]
    assert len(backend.calls) == 3


def test_start_returns_a_daemon_thread():
    stop = threading.Event()
    reporter = StatusReporter(
        FakeBackend(), lambda: {}, robot_id="robot_1", wait=lambda seconds: stop.wait(0.01)
    )
    thread = reporter.start(stop)
    try:
        assert thread.daemon and thread.is_alive()
    finally:
        stop.set()
        thread.join(2)


def test_speech_entry_point_can_disable_the_reporter(monkeypatch):
    from rover.speech import __main__ as entry

    started = []
    monkeypatch.setattr(
        "rover.status.StatusReporter.start", lambda self, stop: started.append(self) or None
    )
    assert entry.start_status(FakeBackend(), disabled=True) is None
    assert started == []
    entry.start_status(FakeBackend(), disabled=False)
    assert len(started) == 1


# --- power wiring ---------------------------------------------------------------------------

UNDERVOLT = {"undervoltage_now": True, "undervoltage_since_boot": True}
SINCE_BOOT = {"undervoltage_now": False, "undervoltage_since_boot": True}


def snap(power, **extra):
    return {"room": "12", "moving": False, "battery": 0.7, "power": power, **extra}


def test_undervoltage_now_reports_fault_even_when_busy_or_charging():
    reporter, backend = make(
        [snap(UNDERVOLT), snap(UNDERVOLT, moving=True), snap(UNDERVOLT, charging=True)]
    )
    for _ in range(3):
        reporter.report_once()
    assert [call[1] for call in backend.calls] == ["fault"] * 3
    assert backend.calls[0][2:] == (0.7, "12", None)


def test_warn_still_reports_normally():
    reporter, backend = make([snap(SINCE_BOOT), snap(SINCE_BOOT, moving=True)])
    reporter.report_once()
    reporter.report_once()
    assert [call[1] for call in backend.calls] == ["idle", "busy"]


def test_fault_clears_when_power_recovers():
    reporter, backend = make([snap(UNDERVOLT), snap({"undervoltage_now": False})])
    reporter.report_once()
    reporter.report_once()
    assert [call[1] for call in backend.calls] == ["fault", "idle"]


def test_missing_or_junk_power_is_ok():
    reporter, backend = make([snap(None), snap("junk"), {"room": "12", "battery": 0.5}])
    for _ in range(3):
        reporter.report_once()
    assert [call[1] for call in backend.calls] == ["idle"] * 3


def test_backend_only_gets_the_fields_the_api_accepts():
    # RobotReport in the backend contract is status, battery, room and target only.
    reporter, backend = make([snap(UNDERVOLT, wifi_rssi_dbm=-60)])
    reporter.report_once()
    assert len(backend.calls[0]) == 5  # (robot_id, status, battery, room, target)


def test_warn_and_fault_are_logged_with_the_power_info(tmp_path):
    path = tmp_path / "{component}.jsonl"
    obslog.configure("speech", path=path)
    try:
        reporter, _ = make([snap(SINCE_BOOT, wifi_rssi_dbm=-71), snap(UNDERVOLT)])
        reporter.report_once()
        reporter.report_once()
    finally:
        obslog.configure("rover", path="")
    rows = [json.loads(x) for x in (tmp_path / "speech.jsonl").read_text().splitlines()]
    power_rows = [r for r in rows if r["event"] == "status.power"]
    assert [r["health"] for r in power_rows] == ["warn", "fault"]
    assert power_rows[0]["wifi_rssi_dbm"] == -71
    assert power_rows[0]["flags"] == ["undervoltage_since_boot"]
    assert power_rows[1]["flags"] == ["undervoltage_now", "undervoltage_since_boot"]


def test_ok_power_logs_nothing():
    reporter, _ = make([snap({"undervoltage_now": False})])
    reporter.report_once()  # no obslog file configured; just must not raise
