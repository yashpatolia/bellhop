"""End-to-end check of the robot software with no hardware, against the REAL backend.

    cd ml/pi && uv run python ../dev/e2e/run.py [--only a,b] [--live-claude] [--strict]

For each scenario it starts the backend (from calhacks-13, read only), `python -m rover.drive
--fake`, and `python -m rover.speech --script` (text mode, offline triage mock; its StatusReporter
runs too), rings the bell through POST /calls and then checks the whole chain through the
backend API, the fault proxy that sits on the backend -> Pi link, and the JSON-lines logs.
Prints a PASS/FAIL table and exits 1 on any FAIL. KNOWN rows are real backend-side bugs this run
reproduces (they are not ml's to fix); they only fail the run with --strict.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenario_backend_dies  # noqa: E402
from faultproxy import Rule  # noqa: E402
from stack import Stack, StatusTracker, wait_for  # noqa: E402

GUARD_S = 2.0  # the backend's go_to timeout (GuardedRobotGateway)
NURSES = ("nurse_priya", "nurse_sam")


@dataclass
class Row:
    scenario: str
    check: str
    status: str  # PASS, FAIL, KNOWN, SKIP
    detail: str = ""


class Report:
    def __init__(self, scenario: str, rows: list[Row]) -> None:
        self.scenario, self.rows = scenario, rows

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.rows.append(Row(self.scenario, name, "PASS" if ok else "FAIL", detail))
        return ok

    def known(self, name: str, ok: bool, detail: str) -> None:
        """A check that reproduces a backend bug: PASS if the backend is right, else KNOWN."""
        self.rows.append(Row(self.scenario, name, "PASS" if ok else "KNOWN", detail))

    def skip(self, name: str, why: str) -> None:
        self.rows.append(Row(self.scenario, name, "SKIP", why))


def write_script(path: Path, lines: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return path


def start_normal(stack: Stack, script: Path, *drive_args: str) -> None:
    stack.start_backend()
    stack.start_drive(*drive_args)
    stack.start_speech(script)


def wait_status_reporting(stack: Stack, rep: Report) -> None:
    ok = wait_for(lambda: stack.events("speech", "backend.request", method="PUT", status=200), 20)
    rep.check("status reporter registers the robot (PUT /robots/robot_1 -> 200)", bool(ok))


def bell(stack: Stack, rep: Report, room: str) -> tuple[str, float]:
    started = time.monotonic()
    status, call = stack.api("POST", "/calls", {"room": room})
    took = time.monotonic() - started
    rep.check("bell: POST /calls -> 201", status == 201, f"HTTP {status}, {took * 1000:.0f} ms")
    return call["id"], took


# ---- scenarios: a normal visit end to end


CHAT_CASES = {
    "routine": dict(
        room="14",
        lines=[
            {"greeting": "Good morning Arthur, how are you?"},
            {"say": "Good morning, isn't it a lovely day", "reply": "It is lovely.", "pause_s": 6},
            {"say": "Tell me about the garden", "reply": "The roses are out."},
        ],
        urgency=1,
        live_urgency=lambda u: u <= 2,
        led=["listening", "idle"],
        statuses=["robot_en_route", "in_visit", "resolved"],
        alert=None,
        by_robot=True,
    ),
    "nurse_soon": dict(
        room="14",
        lines=[
            {"greeting": "Good morning Arthur."},
            {"say": "My tummy hurts and I feel dizzy", "reply": "I'm sorry to hear that."},
        ],
        urgency=3,
        live_urgency=lambda u: u in (3, 4),
        led=["listening", "nurse_on_way", "idle"],
        statuses=["robot_en_route", "in_visit", "escalated", "nurse_acked", "resolved"],
        alert=3,
        by_robot=False,
    ),
    "emergency": dict(
        room="12",
        lines=[
            {"greeting": "Good morning Margaret."},
            {"say": "Help, I fell and I can't get up", "reply": "Stay still, help is coming."},
        ],
        urgency=4,
        live_urgency=lambda u: u == 4,
        led=["listening", "emergency", "idle"],
        statuses=["robot_en_route", "in_visit", "escalated", "nurse_acked", "resolved"],
        alert=4,
        by_robot=False,
    ),
}


def chat_scenario(name: str, workdir: Path, live: bool, rep: Report) -> None:
    case = CHAT_CASES[name]
    room = case["room"]
    stack = Stack(workdir, live_claude=live)
    try:
        script = write_script(workdir / "script.jsonl", case["lines"])
        start_normal(stack, script)
        wait_status_reporting(stack, rep)
        call_id, took = bell(stack, rep, room)
        tracker = StatusTracker(stack, call_id)

        # dispatch: the backend's HttpRobotGateway talks to the real server through the proxy
        go_tos = stack.drive_proxy.seen("/go_to")
        rep.check(
            "dispatch: POST /go_to {room} reached the Pi and answered 2xx",
            len(go_tos) == 1
            and go_tos[0].body == {"room": room}
            and go_tos[0].upstream_status is not None
            and 200 <= go_tos[0].upstream_status < 300,
            f"seen={[(s.body, s.upstream_status) for s in go_tos]}",
        )
        if go_tos:
            rep.check(
                f"dispatch: go_to answered inside the backend's {GUARD_S:g} s guard",
                go_tos[0].duration_ms < GUARD_S * 1000,
                f"{go_tos[0].duration_ms:.0f} ms",
            )
        call = stack.call(call_id)
        rep.check(
            "dispatch: call assigned to robot_1 and robot_en_route after go_to",
            call.get("robot_id") == "robot_1" and call.get("status") == "robot_en_route",
            f"status={call.get('status')} robot_id={call.get('robot_id')}",
        )
        listen = [s.body.get("state") for s in stack.drive_proxy.seen("/led")]
        rep.check("LED: listening is sent on assignment", listen[:1] == ["listening"], f"{listen}")

        # arrival and in-visit
        arrived = wait_for(lambda: stack.events("drive", "drive.arrived", room=room), 20)
        rep.check("robot arrives (drive.arrived in the room)", bool(arrived))
        in_visit = wait_for(lambda: stack.events("speech", "visit.in_visit"), 30)
        rep.check(
            "POST /calls/{id}/in-visit sent and accepted",
            bool(in_visit) and in_visit[0].get("accepted") is True,
            f"{in_visit[:1]}",
        )
        if arrived and in_visit:
            rep.check(
                "in-visit comes after arrival",
                in_visit[0]["t"] >= arrived[0]["t"],
                f"arrived t={arrived[0]['t']:.2f}, in_visit t={in_visit[0]['t']:.2f}",
            )

        if name == "routine":
            time.sleep(0.3)
            mid = stack.call(call_id)
            rep.check("backend shows in_visit during the visit", mid.get("status") == "in_visit")
            reports = wait_for(
                lambda: [
                    r for r in stack.events("speech", "status.report") if r.get("room") == room
                ],
                15,
            )
            rep.check(
                f"status reporter sends room {room} while the robot is there",
                bool(reports),
                f"{len(reports or [])} reports",
            )
            seen = stack.robot()
            rep.check(
                "backend keeps robot_1 busy while it holds the call",
                bool(seen) and seen["status"] == "busy",
                f"{seen}",
            )

        # triage, escalation and the nurse
        if case["alert"]:
            alert = wait_for(
                lambda: next(
                    (a for a in stack.api("GET", "/alerts")[1] if a["call_id"] == call_id), None
                ),
                25,
            )
            rep.check(
                f"alert raised at level {case['alert']}",
                bool(alert) and alert["level"] == case["alert"],
                f"{alert}",
            )
            if alert:
                time.sleep(0.5)  # let the robot reach wait_nurse
                status, _ = stack.api("POST", f"/alerts/{alert['id']}/ack", {"nurse_id": NURSES[0]})
                rep.check("nurse acknowledges the alert (POST /alerts/{id}/ack)", status == 200)

        final = wait_for(
            lambda: (c := stack.call(call_id)) and c.get("status") == "resolved" and c, 40
        )
        rep.check(
            "call ends resolved", bool(final), f"last status {stack.call(call_id).get('status')}"
        )
        time.sleep(0.3)
        statuses = tracker.stop()
        final = final or stack.call(call_id)
        # Polling can miss a state that lasts milliseconds (in_visit, before a fast escalation).
        # The sequence must be an in-order part of the expected one; a missed in_visit is accepted
        # only with proof it happened: the backend set first_response_at (set only by in-visit).
        missed = [st for st in case["statuses"] if st not in statuses]
        in_order = [st for st in case["statuses"] if st in statuses] == statuses
        proven = bool(final.get("first_response_at")) and in_visit and in_visit[0]["accepted"]
        rep.check(
            "status sequence",
            in_order and all(st == "in_visit" and proven for st in missed),
            f"saw {statuses}, wanted {case['statuses']}"
            + (" (in_visit missed by polling, proven by first_response_at)" if missed else ""),
        )

        urgency = final.get("urgency")
        if live:
            rep.check(
                "triage urgency (live Claude)",
                urgency is not None and case["live_urgency"](urgency),
                f"{urgency}",
            )
        else:
            rep.check(
                f"triage urgency is {case['urgency']}", urgency == case["urgency"], f"{urgency}"
            )
        turns = final.get("transcript", [])
        said = [t["text"] for t in turns if t["speaker"] == "resident"]
        wanted = [line["say"] for line in case["lines"] if "say" in line]
        rep.check("resident turns posted in order", said == wanted, f"{said}")
        rep.check(
            "robot turns posted (greeting and replies)",
            sum(1 for t in turns if t["speaker"] == "robot") >= len(wanted) + 1,
            f"{[t['speaker'] for t in turns]}",
        )
        scores = stack.events("speech", "backend.score")
        rep.check(
            "POST /score carries urgency, category and a confidence in [0, 1]",
            bool(scores)
            and all(0.0 <= s["confidence"] <= 1.0 and s.get("category") for s in scores),
            f"{[(s['urgency'], s['category'], s['confidence']) for s in scores]}",
        )
        rep.check(
            "response-time clock started (first_response_at set)",
            bool(final.get("first_response_at")),
        )
        metrics = stack.api("GET", "/metrics")[1]
        credited = metrics.get("resolved_without_nurse")
        rep.check(
            "credited to the robot only when no nurse was needed",
            credited == (1 if case["by_robot"] else 0),
            f"resolved_without_nurse={credited}",
        )

        # LED, driving home, status
        led = [s.body.get("state") for s in stack.drive_proxy.seen("/led")]
        rep.check(
            "LED sequence from the backend", led == case["led"], f"{led}, wanted {case['led']}"
        )
        home = wait_for(lambda: stack.snapshot().get("room") == "lobby" and stack.snapshot(), 15)
        rep.check(
            "robot drives home and stops (lobby, idle, motors stopped)",
            bool(home) and home["mode"] == "idle" and home["moving"] is False,
            f"{home}",
        )
        snap = stack.snapshot()
        rep.check("Pi LED ends idle", snap.get("led") == "idle", f"{snap.get('led')}")
        idle = wait_for(lambda: (r := stack.robot()) and r["status"] == "idle" and r, 15)
        rep.check("backend sees robot_1 idle again after the call", bool(idle), f"{stack.robot()}")
        puts = stack.events("speech", "backend.request", method="PUT", status=200)
        rep.check(
            "robot status updates reached the backend (>= 2 PUTs)", len(puts) >= 2, f"{len(puts)}"
        )
        rep.check(
            "watchdog did not fire during a normal visit",
            not stack.events("drive", "drive.watchdog_stop"),
        )
        if name == "routine":
            doctor_check(stack, rep)
        bad = [
            line
            for line in stack.output("speech").splitlines()
            if "Traceback" in line or "failed:" in line and "visit:" in line
        ]
        rep.check("speech process logged no crash or failed job", not bad, f"{bad[:2]}")
    finally:
        stack.stop()


def doctor_check(stack: Stack, rep: Report) -> None:
    """scripts/doctor.py against the live stack: Pi server, backend, key and clock all OK."""
    import subprocess

    env = stack._pi_env()
    done = subprocess.run(
        [sys.executable, "scripts/doctor.py", "--no-hardware", "--json"],
        cwd=stack_pi_dir(), env=env, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    try:
        results = {r["name"]: r for r in json.loads(done.stdout[done.stdout.index("[") :])}
    except ValueError:
        rep.check(
            "doctor.py runs against the live stack", False, done.stdout[-200:] + done.stderr[-200:]
        )
        return
    for name in ("Pi server", "backend reachable", "backend API key", "clock skew"):
        got = results.get(name, {})
        rep.check(
            f"doctor: {name}",
            got.get("status") == "OK",
            f"{got.get('status')} {got.get('detail', '')}",
        )
    leaked = stack.api_key in done.stdout + done.stderr
    rep.check("doctor never prints the API key", not leaked)


def stack_pi_dir() -> Path:
    from stack import PI_DIR

    return PI_DIR


# ---- fault injection on the backend -> Pi link


FAULTS = {
    "slow_go_to": ("12", Rule(path="/go_to", latency_ms=3000), "go_to answers after 3 s"),
    "go_to_503": ("12", Rule(path="/go_to", status=503), "go_to answers 503"),
    "go_to_dropped": ("14", Rule(path="/go_to", drop="before"), "connection dropped"),
    "slow_go_to_no_risk": ("14", Rule(path="/go_to", latency_ms=3000), "go_to answers after 3 s"),
}


def fault_scenario(name: str, workdir: Path, rep: Report) -> None:
    room, rule, what = FAULTS[name]
    stack = Stack(workdir)
    try:
        script = write_script(workdir / "script.jsonl", [{"say": "hello"}])
        start_normal(stack, script)
        wait_status_reporting(stack, rep)
        stack.drive_proxy.add_rule(rule)
        call_id, took = bell(stack, rep, room)
        slow = rule.latency_ms > GUARD_S * 1000
        if slow:
            rep.check(
                f"backend gives up on go_to at its {GUARD_S:g} s guard (bell returns)",
                GUARD_S - 0.2 <= took <= GUARD_S + 1.5,
                f"POST /calls took {took:.2f} s",
            )
        time.sleep(1.0)
        call = stack.call(call_id)
        rep.check(
            f"fallback ({what}): robot is not assigned",
            call.get("robot_id") is None,
            f"robot_id={call.get('robot_id')}",
        )
        nurses = [a for a in call.get("assigned_to", []) if a in NURSES]
        alerts = [a for a in stack.api("GET", "/alerts")[1] if a["call_id"] == call_id]
        rep.check(
            f"fallback ({what}): a nurse is assigned to the call",
            bool(nurses),
            f"status={call.get('status')} assigned_to={call.get('assigned_to')}",
        )
        rep.check(
            f"fallback ({what}): an alert tells that nurse (robot could not be sent)",
            any(
                a["nurse_id"] in nurses and "robot" in a["message"].lower() and a["level"] >= 3
                for a in alerts
            ),
            f"alerts={alerts}",
        )
        rep.check(
            f"fallback ({what}): the robot was told to stop (POST /stop)",
            bool(wait_for(lambda: stack.drive_proxy.seen("/stop"), 6)),
            f"/stop seen={len(stack.drive_proxy.seen('/stop'))}",
        )
        stuck = stack.robot()
        rep.check(
            "robot_1 stays dispatchable in the backend (not stuck busy)",
            bool(stuck) and stuck["status"] == "idle",
            f"{stuck}",
        )
        if slow:
            # the request was only slow: it still reaches the Pi after the backend gave up,
            # and the backend must stop the robot as soon as it lands
            landed = wait_for(lambda: stack.drive_proxy.seen("/go_to")[0].status is not None, 8)
            time.sleep(1.5)
            snap = stack.snapshot()
            rep.check(
                "no ghost drive: a go_to the backend gave up on does not move the robot",
                bool(landed) and snap["moving"] is False and snap["room"] == "lobby",
                f"Pi snapshot after the late go_to landed: {snap}",
            )
        else:
            time.sleep(2.5)
            snap = stack.snapshot()
            rep.check(
                "robot stays put (nothing reached the Pi)",
                snap["mode"] == "idle"
                and snap["room"] == "lobby"
                and not stack.events("drive", "drive.go_to"),
                f"{snap}",
            )
        rep.check("speech process still running", stack.speech_alive())
    finally:
        stack.stop()


def watchdog_scenario(workdir: Path, rep: Report) -> None:
    """The caller goes silent after one go_to: the Pi must stop by itself."""
    stack = Stack(workdir)
    try:
        stack.start_drive("--travel-s", "30", "--drive-timeout-s", "5", "--watchdog-s", "5")
        url = stack.drive_proxy
        import httpx

        base = f"http://127.0.0.1:{url.port}"
        led = httpx.post(base + "/led", json={"state": "listening"}, timeout=3)
        go = httpx.post(base + "/go_to", json={"room": "12"}, timeout=3)
        rep.check(
            "wire format: POST /led {state} and POST /go_to {room} accepted",
            led.status_code == 200 and go.status_code == 202,
            f"{led.status_code}, {go.status_code}",
        )
        started = time.monotonic()
        time.sleep(1.5)
        snap = stack.snapshot()
        rep.check(
            "robot drives after go_to",
            snap["moving"] is True and snap["mode"] == "going",
            f"{snap}",
        )
        stopped = wait_for(lambda: stack.snapshot()["moving"] is False, 12)
        took = time.monotonic() - started
        rep.check(
            "silent caller: motors stop after the timeout (5 s here) with no new command",
            bool(stopped) and 4.5 <= took <= 8.0,
            f"stopped after {took:.1f} s",
        )
        snap = stack.snapshot()
        rep.check(
            "LED returns to idle and the goal is dropped",
            snap["led"] == "idle" and snap["target"] is None and snap["room"] == "lobby",
            f"{snap}",
        )
        rep.check("drive.watchdog_stop logged", bool(stack.events("drive", "drive.watchdog_stop")))
    finally:
        stack.stop()


def long_drive_scenario(workdir: Path, rep: Report) -> None:
    """A drive longer than the 5 s command watchdog still arrives (the backend sends go_to once)."""
    stack = Stack(workdir)
    try:
        stack.start_drive("--travel-s", "8")
        import httpx

        base = f"http://127.0.0.1:{stack.drive_proxy.port}"
        httpx.post(base + "/go_to", json={"room": "14"}, timeout=3)
        time.sleep(6.5)
        snap = stack.snapshot()
        rep.check(
            "still driving at 6.5 s (past the 5 s command watchdog)",
            snap["moving"] is True,
            f"{snap}",
        )
        arrived = wait_for(lambda: stack.snapshot()["room"] == "14" and stack.snapshot(), 6)
        rep.check(
            "arrives in room 14 after ~8 s",
            bool(arrived) and arrived["moving"] is False,
            f"{arrived}",
        )
        rep.check("no watchdog stop", not stack.events("drive", "drive.watchdog_stop"))
    finally:
        stack.stop()


# ---- the backend is unreachable


def backend_unreachable_scenario(workdir: Path, rep: Report) -> None:
    stack = Stack(workdir)
    try:
        script = write_script(workdir / "script.jsonl", [{"say": "Lovely day"}])
        stack.start_drive()
        stack.start_speech(script)  # nothing listens on the backend port yet
        time.sleep(8)
        snap = stack.snapshot()
        rep.check(
            "robot stays stopped with LED idle",
            snap["mode"] == "idle" and snap["moving"] is False and snap["led"] == "idle",
            f"{snap}",
        )
        rep.check("no drive command was issued", not stack.events("drive", "drive.go_to"))
        errors = stack.events("speech", "backend.request", error="ConnectError")
        rep.check("backend failures are logged (ConnectError)", len(errors) >= 2, f"{len(errors)}")
        reports = stack.events("speech", "status.report")
        rep.check(
            "status reporter keeps trying and reports idle",
            bool(reports) and reports[-1].get("status") == "idle",
            f"{reports[-1:]}",
        )
        rep.check(
            "speech process survives and logs no traceback",
            stack.speech_alive() and "Traceback" not in stack.output("speech"),
        )

        stack.start_backend()  # the backend comes back; the same speech process must recover
        call_id, _ = bell(stack, rep, "14")
        final = wait_for(
            lambda: (c := stack.call(call_id)) and c.get("status") == "resolved" and c, 60
        )
        rep.check(
            "after the backend returns, the same robot handles a call to resolution",
            bool(final),
            f"{stack.call(call_id).get('status')}",
        )
    finally:
        stack.stop()


def resolve_fails_scenario(workdir: Path, rep: Report) -> None:
    """The Pi -> backend link drops the resolve: the call must not be left open."""
    stack = Stack(workdir)
    try:
        script = write_script(workdir / "script.jsonl", [{"say": "Lovely day"}])
        stack.add_backend_proxy()
        start_normal(stack, script)
        wait_status_reporting(stack, rep)
        proxy = stack.backend_proxy
        call_id, _ = bell(stack, rep, "14")
        proxy.add_rule(Rule(path=f"/calls/{call_id}/resolve", status=503, times=2))
        final = wait_for(
            lambda: (c := stack.call(call_id)) and c.get("status") == "resolved" and c, 40
        )
        seen = [s.status for s in proxy.seen(f"/calls/{call_id}/resolve")]
        rep.check(
            "a failed resolve is retried until it lands (transient 503 x2)",
            bool(final),
            f"resolve answers {seen}; call status {stack.call(call_id).get('status')}",
        )
    finally:
        stack.stop()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--only", help="comma-separated scenario names")
    parser.add_argument("--strict", action="store_true", help="KNOWN backend bugs fail the run too")
    parser.add_argument(
        "--live-claude",
        action="store_true",
        help="real Claude brain and triage (needs ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--keep-logs", action="store_true", help="print the log directory and keep it"
    )
    args = parser.parse_args()

    names = [
        "routine",
        "nurse_soon",
        "emergency",
        *FAULTS,
        "watchdog",
        "long_drive",
        "backend_unreachable",
        "resolve_fails",
        "backend_dies",
    ]
    if args.only:
        wanted = args.only.split(",")
        unknown = [n for n in wanted if n not in names]
        if unknown:
            parser.error(f"unknown scenario {unknown}; choose from {names}")
        names = [n for n in names if n in wanted]

    root = Path(tempfile.mkdtemp(prefix="rover-e2e-"))
    rows: list[Row] = []
    for name in names:
        rep = Report(name, rows)
        workdir = root / name
        print(f"== {name}", flush=True)
        started = time.monotonic()
        try:
            if name in CHAT_CASES:
                if args.live_claude and not os.environ.get("ANTHROPIC_API_KEY"):
                    rep.skip("whole scenario", "--live-claude needs ANTHROPIC_API_KEY")
                    continue
                chat_scenario(name, workdir, args.live_claude, rep)
            elif name in FAULTS:
                fault_scenario(name, workdir, rep)
            elif name == "watchdog":
                watchdog_scenario(workdir, rep)
            elif name == "long_drive":
                long_drive_scenario(workdir, rep)
            elif name == "backend_unreachable":
                backend_unreachable_scenario(workdir, rep)
            elif name == "resolve_fails":
                resolve_fails_scenario(workdir, rep)
            elif name == "backend_dies":
                scenario_backend_dies.scenario(workdir, rep)
        except Exception:
            rep.check("scenario ran to the end", False, traceback.format_exc().splitlines()[-1])
            traceback.print_exc()
        print(f"   ({time.monotonic() - started:.0f} s)", flush=True)

    print_table(rows)
    failed = sum(r.status == "FAIL" for r in rows)
    known = sum(r.status == "KNOWN" for r in rows)
    print(f"\nlogs: {root}" if args.keep_logs or failed else "")
    print(
        f"{sum(r.status == 'PASS' for r in rows)} PASS, {failed} FAIL, {known} KNOWN backend bugs, "
        f"{sum(r.status == 'SKIP' for r in rows)} SKIP"
    )
    return 1 if failed or (args.strict and known) else 0


def print_table(rows: list[Row]) -> None:
    width = max((len(r.check) for r in rows), default=10)
    width = min(width, 78)
    print()
    last = None
    for row in rows:
        if row.scenario != last:
            print(f"\n[{row.scenario}]")
            last = row.scenario
        detail = f"  {row.detail}" if row.detail and row.status != "PASS" else ""
        print(f"  {row.status:<5} {row.check[:width]:<{width}}{detail}")


if __name__ == "__main__":
    raise SystemExit(main())
