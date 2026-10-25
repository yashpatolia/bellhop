import json
import threading
import urllib.error
import urllib.request

import pytest

from rover import config
from rover.drive import DRIVE_TIMEOUT_S, WATCHDOG_S
from rover.drive.car import FakeCar
from rover.drive.control import Controller, UnknownRoom
from rover.drive.navigator import SimNavigator
from rover.drive.server import make_server


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class RecordingCar(FakeCar):
    def __init__(self, distance: float = 300.0) -> None:
        super().__init__()
        self.calls: list[tuple] = []
        self.distance = distance

    def drive(self, left: int, right: int) -> None:
        self.calls.append(("drive", left, right))

    def led(self, state: str) -> None:
        self.calls.append(("led", state))

    def distance_cm(self) -> float | None:
        return self.distance


def make(distance: float = 300.0, travel_s: float = SimNavigator.TRAVEL_S):
    clock, car = Clock(), RecordingCar(distance)
    ctl = Controller(car, SimNavigator(clock, travel_s), clock=clock)
    car.calls.clear()  # startup stop and led idle are not under test
    return ctl, car, clock


def test_numeric_marker_targets_do_not_need_a_site_specific_map():
    assert config.marker_for_room("210") == 210
    assert config.marker_for_room("999") is None


def test_startup_stops_motors_and_sets_led_idle():
    car = RecordingCar()
    Controller(car, SimNavigator(Clock()), clock=Clock())
    assert car.calls == [("drive", 0, 0), ("led", "idle")]


def test_starts_stopped_at_home_with_led_idle():
    ctl, _, _ = make()
    snap = ctl.snapshot()
    assert (snap["room"], snap["moving"], snap["led"]) == (config.HOME_ROOM, False, "idle")
    assert snap["last_command_age_s"] is None


def test_unknown_room_rejected_and_nothing_moves():
    ctl, car, _ = make()
    with pytest.raises(UnknownRoom):
        ctl.go_to("999")
    assert car.calls == []
    assert ctl.snapshot()["moving"] is False


def test_go_to_drives_then_arrives_and_updates_room():
    ctl, car, clock = make()
    ctl.go_to("12")
    ctl.tick()
    assert ctl.snapshot()["moving"] is True
    assert any(c[0] == "drive" and c[1] > 0 for c in car.calls)
    clock.now += SimNavigator.TRAVEL_S + 0.1
    ctl.tick()
    snap = ctl.snapshot()
    assert (snap["room"], snap["moving"]) == ("12", False)
    assert car.calls[-1] == ("drive", 0, 0)


def test_drive_longer_than_the_watchdog_keeps_going_and_arrives():
    """Nothing re-sends go_to (the backend sends it once), so a real drive of 8 s must not be
    cut off by the 5 s command watchdog."""
    ctl, car, clock = make(travel_s=8)
    ctl.go_to("12")
    for _ in range(90):  # a little over 8 s of 10 Hz ticks
        clock.now += 0.1
        ctl.tick()
        if ctl.snapshot()["room"] == "12":
            break
        assert ctl.snapshot()["moving"] is True, f"stopped at {clock.now - 100:.1f} s"
    snap = ctl.snapshot()
    assert (snap["room"], snap["moving"]) == ("12", False)


def test_silent_caller_stops_a_drive_after_the_drive_timeout():
    ctl, car, clock = make(travel_s=600)
    ctl.go_to("12")
    ctl.tick()
    clock.now += DRIVE_TIMEOUT_S - 0.1
    ctl.tick()
    assert ctl.snapshot()["moving"] is True
    clock.now += 0.2
    ctl.tick()
    snap = ctl.snapshot()
    assert (snap["moving"], snap["led"], snap["room"]) == (False, "idle", config.HOME_ROOM)
    assert ("drive", 0, 0) in car.calls
    assert car.calls[-1] == ("led", "idle")


def test_drive_timeout_is_longer_than_the_command_watchdog():
    assert DRIVE_TIMEOUT_S > WATCHDOG_S >= 5.0


def test_repeating_go_to_extends_the_drive_timeout():
    ctl, _, clock = make(travel_s=600)
    ctl.go_to("12")
    clock.now += DRIVE_TIMEOUT_S - 1
    ctl.go_to("12")
    clock.now += DRIVE_TIMEOUT_S - 1
    ctl.tick()
    assert ctl.snapshot()["moving"] is True


def test_repeating_go_to_refreshes_watchdog():
    ctl, _, clock = make(travel_s=60)
    ctl.go_to("12")
    clock.now += 4.0
    ctl.go_to("12")
    clock.now += 4.0
    ctl.tick()
    assert ctl.snapshot()["moving"] is True


def test_stop_cancels_drive():
    ctl, car, clock = make()
    ctl.go_to("14")
    ctl.tick()
    ctl.stop()
    clock.now += 10
    ctl.tick()
    snap = ctl.snapshot()
    assert (snap["moving"], snap["room"]) == (False, config.HOME_ROOM)
    assert ("drive", 0, 0) in car.calls


def test_failed_navigation_stops_without_claiming_the_target_room():
    class FailedNavigator:
        def start(self, room):
            return None

        def step(self, car):
            car.stop()
            return False

        def failed(self):
            return True

        def cancel(self):
            return None

    clock, car = Clock(), RecordingCar()
    ctl = Controller(car, FailedNavigator(), clock=clock)
    car.calls.clear()
    ctl.go_to("12")
    ctl.tick()

    snap = ctl.snapshot()
    assert (snap["room"], snap["target"], snap["mode"], snap["moving"]) == (
        config.HOME_ROOM,
        None,
        "idle",
        False,
    )


def test_obstacle_halts_forward_motion():
    ctl, car, _ = make(distance=config.STOP_DISTANCE_CM - 1)
    ctl.go_to("12")
    ctl.tick()
    assert car.calls[-1] == ("drive", 0, 0)
    assert all(c[1] <= 0 for c in car.calls if c[0] == "drive")


def test_led_validates_state():
    ctl, car, _ = make()
    ctl.set_led("emergency")
    assert ctl.snapshot()["led"] == "emergency"
    assert ("led", "emergency") in car.calls
    with pytest.raises(ValueError):
        ctl.set_led("purple")


def test_follow_and_face_set_mode_without_driving_and_expire():
    ctl, car, clock = make()
    ctl.follow()
    assert ctl.snapshot()["mode"] == "following"
    ctl.face()
    assert ctl.snapshot()["mode"] == "facing"
    assert not [c for c in car.calls if c[0] == "drive" and c != ("drive", 0, 0)]
    clock.now += 5.1
    ctl.tick()
    assert ctl.snapshot()["mode"] == "idle"


@pytest.fixture
def server():
    clock = Clock()
    car = RecordingCar()
    ctl = Controller(car, SimNavigator(clock), clock=clock)
    httpd = make_server(ctl, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", ctl
    httpd.shutdown()
    httpd.server_close()


def call(url: str, method: str = "GET", body=None, raw: bytes | None = None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def test_http_go_to_accepts_with_202_and_moves(server):
    url, ctl = server
    status, _ = call(f"{url}/go_to", "POST", {"room": "12"})
    assert status == 202
    assert ctl.snapshot()["target"] == "12"


def test_http_go_to_bad_requests_are_4xx(server):
    url, _ = server
    assert call(f"{url}/go_to", "POST", {"room": "999"})[0] == 404
    assert call(f"{url}/go_to", "POST", {})[0] == 400
    assert call(f"{url}/go_to", "POST", {"room": 12})[0] == 400
    assert call(f"{url}/go_to", "POST", raw=b"not json")[0] == 400
    assert call(f"{url}/nope", "POST", {})[0] == 404
    assert call(f"{url}/snapshot", "POST", {})[0] == 405


def test_http_led(server):
    url, ctl = server
    assert call(f"{url}/led", "POST", {"state": "listening"})[0] == 200
    assert ctl.snapshot()["led"] == "listening"
    assert call(f"{url}/led", "POST", {"state": "purple"})[0] == 400
    assert call(f"{url}/led", "POST", {})[0] == 400


def test_http_stop_and_snapshot(server):
    url, ctl = server
    call(f"{url}/go_to", "POST", {"room": "14"})
    assert call(f"{url}/stop", "POST", {})[0] == 200
    status, snap = call(f"{url}/snapshot")
    assert status == 200
    assert snap["moving"] is False
    assert {"room", "moving", "battery", "led", "last_command_age_s"} <= snap.keys()


def test_http_follow_and_face(server):
    url, ctl = server
    assert call(f"{url}/follow", "POST", {})[0] == 202
    assert ctl.snapshot()["mode"] == "following"
    assert call(f"{url}/face", "POST", {})[0] == 202
    assert ctl.snapshot()["mode"] == "facing"


def test_http_unsupported_methods_are_never_5xx(server):
    url, ctl = server
    for method in ("PUT", "DELETE", "PATCH", "OPTIONS", "TRACE", "HEAD", "QUERY", "PROPFIND"):
        for path in ("/go_to", "/led", "/stop", "/snapshot", "/nope"):
            req = urllib.request.Request(f"{url}{path}", data=None, method=method)
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    status = resp.status
            except urllib.error.HTTPError as exc:
                status = exc.code
                if status == 405:
                    assert exc.headers.get("Allow"), f"{method} {path}: 405 without Allow"
            assert status in (404, 405), f"{method} {path} -> {status}"
    assert ctl.snapshot()["mode"] == "idle"
    for path, allowed in (("/snapshot", "GET"), ("/go_to", "POST")):
        wrong = "POST" if allowed == "GET" else "GET"
        req = urllib.request.Request(
            f"{url}{path}", data=b"{}" if wrong == "POST" else None, method=wrong
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        assert caught.value.code == 405 and caught.value.headers["Allow"] == allowed


def test_http_oversized_body_is_413(server):
    url, _ = server
    big = b'{"x": "' + b"a" * 5000 + b'"}'
    assert call(f"{url}/follow", "POST", raw=big)[0] == 413


def test_http_garbage_headers_are_4xx(server):
    url, _ = server
    host, port = url.removeprefix("http://").split(":")
    import socket

    for head in (
        b"POST /go_to HTTP/1.1\r\nContent-Length: -5\r\n\r\n",
        b"POST /go_to HTTP/1.1\r\nContent-Length: abc\r\n\r\n",
        b"POST /go_to HTTP/1.1\r\nContent-Length: 99999999999999999999\r\n\r\n",
    ):
        with socket.create_connection((host, int(port)), timeout=5) as sock:
            sock.sendall(head)
            reply = sock.recv(200)
        assert reply.startswith(b"HTTP/1."), reply
        assert reply.split()[1][:1] == b"4", reply


def test_openapi_file_lists_exactly_the_servers_routes():
    from pathlib import Path

    import yaml

    from rover.drive import server as drive_server

    spec = yaml.safe_load(
        (Path(drive_server.__file__).parent / "openapi.yaml").read_text(encoding="utf-8")
    )
    routes = {*drive_server._Server.POST_PATHS, "/snapshot"}
    assert set(spec["paths"]) == routes
    room = spec["paths"]["/go_to"]["post"]["requestBody"]["content"]["application/json"]
    assert room["schema"]["properties"]["room"]["type"] == "string"


# --- power in the snapshot ------------------------------------------------------------------

POWER = {"undervoltage_now": True, "undervoltage_since_boot": True, "throttled_now": False}


def make_with(travel_s=SimNavigator.TRAVEL_S, **kwargs):
    clock, car = Clock(), RecordingCar()
    ctl = Controller(car, SimNavigator(clock, travel_s), clock=clock, **kwargs)
    car.calls.clear()
    return ctl, car, clock


def test_snapshot_carries_power_flags_and_wifi_rssi():
    ctl, _, _ = make_with(power_reader=lambda: {**POWER, "wifi_rssi_dbm": -64})
    snap = ctl.snapshot()
    assert snap["power"] == POWER
    assert snap["wifi_rssi_dbm"] == -64


def test_snapshot_power_is_null_off_the_pi():
    ctl, _, _ = make_with(power_reader=lambda: None)
    snap = ctl.snapshot()
    assert snap["power"] is None and snap["wifi_rssi_dbm"] is None


def test_snapshot_survives_a_crashing_power_reader():
    def boom():
        raise RuntimeError("vcgencmd")

    ctl, _, _ = make_with(power_reader=boom)
    assert ctl.snapshot()["power"] is None


def test_power_is_read_at_most_once_per_cache_window():
    reads = []

    def reader():
        reads.append(1)
        return dict(POWER)

    ctl, _, clock = make_with(power_reader=reader)
    ctl.snapshot()
    ctl.snapshot()
    assert len(reads) == 1
    clock.now += config.POWER_CACHE_S + 0.1
    ctl.snapshot()
    assert len(reads) == 2


# --- LED hold -------------------------------------------------------------------------------


def test_led_hold_default_is_120_seconds():
    assert config.LED_HOLD_S == 120.0
    assert config.LED_KEEPALIVE_S < config.LED_HOLD_S / 2


def test_stale_listening_led_returns_to_idle():
    ctl, car, clock = make_with(led_hold_s=120)
    ctl.set_led("listening")
    clock.now += 119
    ctl.tick()
    assert ctl.snapshot()["led"] == "listening"
    clock.now += 2
    ctl.tick()
    assert ctl.snapshot()["led"] == "idle"
    assert car.calls[-1] == ("led", "idle")


def test_stale_emergency_led_also_returns_to_idle_once_nobody_refreshes_it():
    ctl, _, clock = make_with(led_hold_s=120)
    ctl.set_led("emergency")
    clock.now += 121
    ctl.tick()
    assert ctl.snapshot()["led"] == "idle"


def test_live_visit_refreshing_led_keeps_emergency_up():
    ctl, _, clock = make_with(led_hold_s=120)
    ctl.set_led("emergency")
    for _ in range(10):  # 10 minutes, the visit re-sends the state every 60 s
        clock.now += 60
        ctl.set_led("emergency")
        ctl.tick()
    assert ctl.snapshot()["led"] == "emergency"


def test_idle_led_is_not_rewritten_by_the_hold():
    ctl, car, clock = make_with(led_hold_s=120)
    clock.now += 500
    ctl.tick()
    assert car.calls == []


def test_led_hold_is_configurable_and_does_not_touch_a_drive_in_progress():
    ctl, _, clock = make_with(travel_s=600, led_hold_s=10, drive_timeout_s=600)
    ctl.set_led("nurse_on_way")
    ctl.go_to("12")
    clock.now += 11
    ctl.tick()
    snap = ctl.snapshot()
    assert snap["led"] == "idle" and snap["target"] == "12"


def test_snapshot_keys_match_the_openapi_schema():
    from pathlib import Path

    import yaml

    from rover.drive import server as drive_server

    spec = yaml.safe_load(
        (Path(drive_server.__file__).parent / "openapi.yaml").read_text(encoding="utf-8")
    )
    schema = spec["components"]["schemas"]["Snapshot"]
    ctl, _, _ = make_with(power_reader=lambda: {**POWER, "wifi_rssi_dbm": -50})
    assert set(ctl.snapshot()) == set(schema["properties"]) == set(schema["required"])
