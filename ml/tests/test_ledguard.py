import threading

import pytest

from rover.speech import ledguard


class Pi:
    """Records POSTs to the drive server and serves a /snapshot with a settable LED."""

    def __init__(self, led="listening"):
        self.led = led
        self.posts = []

    def post(self, path, body):
        self.posts.append((path, body))
        if path == "/led":
            self.led = body["state"]
        return None

    def fetch(self):
        return {"led": self.led}


def test_release_led_posts_idle_only():
    pi = Pi()
    ledguard.release_led(pi.post)
    assert pi.posts == [("/led", {"state": "idle"})]


def test_release_robot_posts_led_idle_then_stop():
    pi = Pi()
    ledguard.release_robot(pi.post)
    assert pi.posts == [("/led", {"state": "idle"}), ("/stop", {})]


def test_release_survives_an_unreachable_drive_server():
    def down(path, body):
        raise OSError("drive server down")

    ledguard.release_robot(down)  # must not raise


@pytest.mark.parametrize("led", ["listening", "emergency", "nurse_on_way"])
def test_keepalive_resends_a_lit_led(led):
    pi = Pi(led)
    ledguard.LedKeepalive(pi.post, pi.fetch).tick()
    assert pi.posts == [("/led", {"state": led})]


def test_keepalive_never_lights_an_idle_robot_or_acts_on_junk():
    pi = Pi("idle")
    keep = ledguard.LedKeepalive(pi.post, pi.fetch)
    keep.tick()
    for junk in (None, {}, {"led": 3}, {"led": "purple"}):
        ledguard.LedKeepalive(pi.post, lambda junk=junk: junk).tick()
    assert pi.posts == []


def test_keepalive_never_raises():
    def boom():
        raise RuntimeError("x")

    ledguard.LedKeepalive(lambda p, b: None, boom).tick()


def test_keepalive_thread_ticks_until_stopped():
    pi = Pi("emergency")
    ticked = threading.Event()
    real_post = pi.post

    def post(path, body):
        ticked.set()
        return real_post(path, body)

    keep = ledguard.LedKeepalive(post, pi.fetch, period_s=0.01)
    keep.start()
    assert ticked.wait(5)
    keep.stop()
    count = len(pi.posts)
    threading.Event().wait(0.1)
    assert len(pi.posts) == count


def test_guard_normal_end_sets_led_idle_but_does_not_stop_the_drive_home():
    pi = Pi()
    abnormal = []
    with ledguard.visit_guard(lambda: abnormal.append(1), pi.post, pi.fetch, period_s=60):
        pass
    assert pi.posts == [("/led", {"state": "idle"})]  # /stop would cancel the go_to home
    assert abnormal == []


def test_guard_on_exception_runs_the_abnormal_release_and_reraises():
    pi = Pi()
    with pytest.raises(RuntimeError):
        with ledguard.visit_guard(lambda: ledguard.release_robot(pi.post), pi.post, pi.fetch, 60):
            raise RuntimeError("backend died")
    assert pi.posts == [("/led", {"state": "idle"}), ("/stop", {})]


def test_guard_on_sigterm_systemexit_runs_the_abnormal_release():
    pi = Pi()
    with pytest.raises(SystemExit):
        with ledguard.visit_guard(lambda: ledguard.release_robot(pi.post), pi.post, pi.fetch, 60):
            raise SystemExit(0)
    assert ("/stop", {}) in pi.posts and pi.led == "idle"


def test_guard_keeps_the_led_alive_during_the_visit():
    pi = Pi("emergency")
    seen = threading.Event()

    def post(path, body):
        if body == {"state": "emergency"}:
            seen.set()
        return pi.post(path, body)

    with ledguard.visit_guard(lambda: None, post, pi.fetch, period_s=0.01):
        assert seen.wait(5)
    assert pi.led == "idle"  # released at the end, and the keepalive did not undo it
