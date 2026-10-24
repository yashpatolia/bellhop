"""Play the three Bellhop demo scenes against a running server.

    python scripts/demo_scenes.py --base-url http://127.0.0.1:8000 --scene all --pace 2

Start the server with seed data first: BELLHOP_SEED_DEMO=1 uvicorn bellhop.api.main:app
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

Context = dict[str, Any]
Check = Callable[[Any, Context], str | None]


class DemoError(Exception):
    pass


@dataclass(frozen=True)
class Step:
    scene: int
    say: str  # narration: what is sent and what the dashboard should show
    method: str
    path: str  # may contain {call_id}, {resident_id}, {alert_id}
    body: dict[str, Any] | None = None
    expect: int = 200
    after: Callable[[Any, Context], None] | None = None  # save ids into the context
    check: Check | None = None  # return an error message to fail the step
    fields: dict[str, Any] = field(default_factory=dict)


def _save_call(data: Any, ctx: Context) -> None:
    ctx["call_id"] = data["id"]
    ctx["resident_id"] = data["resident_id"]


def _remembers_sugar(data: Any, ctx: Context) -> str | None:
    if any("sugar" in fact["text"].lower() for fact in data):
        return None
    return "memory recall did not return the two-sugars fact (is the server seeded?)"


def _save_alert(level: int) -> Callable[[Any, Context], None]:
    def save(data: Any, ctx: Context) -> None:
        match = [a for a in data if a["call_id"] == ctx["call_id"] and a["level"] == level]
        if match:
            ctx["alert_id"] = match[0]["id"]
            ctx["nurse_id"] = match[0]["nurse_id"]

    return save


def _expects_alert(level: int, broadcast: bool) -> Check:
    def check(data: Any, ctx: Context) -> str | None:
        match = [a for a in data if a["call_id"] == ctx["call_id"] and a["level"] == level]
        if not match:
            return f"no level {level} alert was raised for this call"
        if broadcast and match[0]["nurse_id"] is not None:
            return "expected a broadcast alert (no single nurse)"
        if not broadcast and match[0]["nurse_id"] is None:
            return "expected the alert to name a nurse"
        return None

    return check


def _scene(
    n: int, room: str, turns: list[tuple[str, str]], score: dict[str, Any], tail: list[Step]
) -> list[Step]:
    steps = [
        Step(
            n,
            f"Room {room} presses the bell; dashboard shows a new call.",
            "POST",
            "/calls",
            {"room": room},
            201,
            after=_save_call,
        ),
        Step(
            n,
            "Robot rolls over; dashboard shows the call in visit.",
            "POST",
            "/calls/{call_id}/in-visit",
        ),
    ]
    steps += [
        Step(
            n,
            f"{speaker.capitalize()} says: {text!r}; live transcript updates.",
            "POST",
            "/calls/{call_id}/turns",
            {"speaker": speaker, "text": text},
        )
        for speaker, text in turns
    ]
    steps.append(Step(n, "", "POST", "/calls/{call_id}/score", score))
    return steps + tail


def build_steps(room: str = "12", scene: int | None = None) -> list[Step]:
    """Pure description of the demo: every HTTP call in order, tagged by scene."""
    s1 = _scene(
        1,
        room,
        [
            ("resident", "Can I get a cup of tea and a chat?"),
            ("robot", "Of course, Margaret. Two sugars as usual? How is your grandson?"),
        ],
        {"urgency": 1, "category": "social", "summary": "Wants tea and a chat"},
        [],
    )
    s1.insert(
        2,
        Step(
            1,
            "Robot recalls what Margaret likes; two sugars should come back.",
            "GET",
            "/residents/{resident_id}/memory?q=tea+sugar",
            check=_remembers_sugar,
        ),
    )
    s1[-1] = Step(
        1,
        "Scored urgency 1 (social); dashboard shows no nurse alert.",
        "POST",
        "/calls/{call_id}/score",
        s1[-1].body,
    )
    s1.append(
        Step(
            1,
            "Resolved by the robot; 'resolved without nurse' ticks up.",
            "POST",
            "/calls/{call_id}/resolve",
            {"by_robot": True},
        )
    )

    s2 = _scene(
        2,
        room,
        [
            ("resident", "My hip has been aching since last night."),
            (
                "robot",
                "I am sorry to hear that. Where does it hurt, and how bad is it from 1 to 10?",
            ),
            ("resident", "Left hip, about a 6."),
        ],
        {
            "urgency": 3,
            "category": "pain",
            "summary": "Left hip pain since last night, about 6 out of 10",
        },
        [],
    )
    s2[-1] = Step(
        2,
        "Scored urgency 3 (pain); a nurse alert with the summary appears.",
        "POST",
        "/calls/{call_id}/score",
        s2[-1].body,
    )
    s2 += [
        Step(
            2,
            "Fetching the alert the nurse received.",
            "GET",
            "/alerts",
            after=_save_alert(3),
            check=_expects_alert(3, False),
        ),
        Step(
            2,
            "Nurse taps 'on my way'; the alert shows as acknowledged.",
            "POST",
            "/alerts/{alert_id}/ack",
            fields={"nurse": True},
            check=lambda data, ctx: None if data.get("acked_at") else "alert was not acknowledged",
        ),
        Step(
            2,
            "Nurse resolves the call in person.",
            "POST",
            "/calls/{call_id}/resolve",
            {"by_robot": False},
        ),
    ]

    s3 = _scene(
        3,
        room,
        [("resident", "I've fallen and I can't get up.")],
        {
            "urgency": 4,
            "category": "fall",
            "confidence": 0.9,
            "summary": "Resident reports a fall and cannot get up",
        },
        [],
    )
    s3[-1] = Step(
        3,
        "Scored urgency 4 (fall); red banner, alert goes to all nurses.",
        "POST",
        "/calls/{call_id}/score",
        s3[-1].body,
    )
    s3 += [
        Step(3, "Fetching the broadcast alert.", "GET", "/alerts", check=_expects_alert(4, True)),
        Step(
            3,
            "Help arrives; nurse resolves the call.",
            "POST",
            "/calls/{call_id}/resolve",
            {"by_robot": False},
        ),
    ]

    steps = s1 + s2 + s3
    return [s for s in steps if scene is None or s.scene == scene]


def _send(client: httpx.Client, step: Step, ctx: Context) -> Any:
    path = step.path.format(**ctx)
    body = step.body
    if step.fields.get("nurse"):
        body = {"nurse_id": ctx.get("nurse_id") or "nurse_demo"}
    try:
        response = client.request(step.method, path, json=body)
    except httpx.TransportError as exc:
        raise DemoError(f"cannot reach the server at {client.base_url}: {exc}") from exc
    if response.status_code != step.expect:
        raise DemoError(
            f"{step.method} {path} returned {response.status_code}, expected {step.expect}: "
            f"{response.text[:200]}"
        )
    return response.json()


def run(client: httpx.Client, steps: Sequence[Step], pace: float, out=print) -> None:
    ctx: Context = {}
    current = None
    for step in steps:
        if step.scene != current:
            current = step.scene
            out(f"\n== Scene {current} ==")
        data = _send(client, step, ctx)
        if step.after:
            step.after(data, ctx)
        if step.check and (problem := step.check(data, ctx)):
            raise DemoError(f"{step.method} {step.path}: {problem}")
        if step.say:
            out(f"  {step.method} {step.path.split('?')[0]}: {step.say}")
        if pace > 0:
            time.sleep(pace)


def main(argv: Sequence[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(description="Play the Bellhop demo scenes.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--scene", choices=["1", "2", "3", "all"], default="all")
    parser.add_argument("--pace", type=float, default=2.0, help="seconds between steps")
    parser.add_argument("--room", default="12")
    args = parser.parse_args(argv)

    scene = None if args.scene == "all" else int(args.scene)
    steps = build_steps(args.room, scene)
    try:
        with httpx.Client(base_url=args.base_url, transport=transport, timeout=10) as client:
            run(client, steps, args.pace)
    except DemoError as exc:
        print(f"demo failed: {exc}", file=sys.stderr)
        return 1
    print("\nDemo complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
