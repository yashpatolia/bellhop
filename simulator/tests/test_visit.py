import random

import httpx

from bellhop_sim import data
from bellhop_sim.client import Backend
from bellhop_sim.fleet import Fleet, SimRobot
from bellhop_sim.visit import Pace, VisitOptions, play_call


class FakeBackend:
    """Answers like the real routes, and records what the robot did."""

    def __init__(self, robot_id="bellhop_1", status_after_score="in_visit"):
        self.log: list[tuple[str, str, dict | None]] = []
        self.robot_id = robot_id
        self.status = "robot_en_route"
        self.status_after_score = status_after_score
        self.alert_acked = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content) if request.content else None
        path, method = request.url.path, request.method
        self.log.append((method, path, body))
        if method == "POST" and path == "/calls":
            return httpx.Response(201, json={"id": "c1", "robot_id": self.robot_id})
        if path == "/calls/c1" and method == "GET":
            return httpx.Response(
                200, json={"status": self.status_after_score if self.alert_acked else "escalated"}
            )
        if path == "/alerts" and method == "GET":
            return httpx.Response(
                200, json=[{"id": "a1", "call_id": "c1", "nurse_id": "n1", "acked_at": None}]
            )
        if path == "/alerts/a1/ack":
            self.alert_acked = True
            self.status_after_score = "nurse_acked"
            return httpx.Response(200, json={})
        return httpx.Response(200, json={})

    def posts(self):
        return [p for m, p, _ in self.log if m == "POST"]


FAST = VisitOptions(nurse_delay_s=1, poll_s=1)


def run(fake, scenario, opts=FAST):
    api = Backend(transport=httpx.MockTransport(fake))
    fleet = Fleet([SimRobot("bellhop_1", 0.8)])
    resident = next(r for r in data.residents() if r["id"] == "r101")
    play_call(api, fleet, Pace(0), random.Random(1), resident, scenario, opts)
    return fleet


def scenario(urgency):
    return next(s for s in data.scenarios() if s.urgency == urgency)


def test_a_chat_is_resolved_by_the_robot_without_waiting():
    fake = FakeBackend()
    fleet = run(fake, scenario(1))
    posts = fake.posts()
    assert posts[0] == "/calls" and posts[1] == "/calls/c1/in-visit"
    assert posts.count("/calls/c1/turns") == 6
    assert "/calls/c1/score" in posts
    resolve = [b for m, p, b in fake.log if m == "POST" and p.endswith("/resolve")]
    assert resolve == [{"by_robot": True}]
    assert fleet.snapshot()[0].status == "idle"


def test_the_visit_is_scored_right_after_the_first_resident_turn():
    fake = FakeBackend()
    run(fake, scenario(1))
    posts = fake.posts()
    assert posts.index("/calls/c1/score") == posts.index("/calls/c1/turns") + 1


def test_a_nurse_call_waits_for_an_ack_then_resolves_not_by_the_robot():
    fake = FakeBackend()
    run(fake, scenario(3))
    assert "/alerts/a1/ack" in fake.posts()
    resolve = [b for m, p, b in fake.log if m == "POST" and p.endswith("/resolve")]
    assert resolve == [{"by_robot": False}]


def test_no_free_robot_means_a_nurse_takes_it_and_closes_it():
    fake = FakeBackend(robot_id=None)
    run(fake, scenario(1))
    assert fake.posts() == ["/calls", "/calls/c1/score", "/calls/c1/resolve"]
    assert [b for m, p, b in fake.log if p.endswith("/resolve")] == [{"by_robot": False}]


def test_with_the_nurse_left_to_the_dashboard_the_call_stays_open():
    fake = FakeBackend(robot_id=None)
    run(fake, scenario(1), VisitOptions(nurse_delay_s=0))
    assert fake.posts() == ["/calls"]


def test_the_robot_is_busy_while_on_a_call_and_battery_goes_down():
    fake = FakeBackend()
    fleet = run(fake, scenario(1))
    r = fleet.snapshot()[0]
    assert r.battery < 0.8 and r.room == "101"
