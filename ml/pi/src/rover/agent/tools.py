"""The brain's tools: look, request_staff, stop, go_to_room, follow_patient, face_patient,
start_game, end_game.

The moving tools only ask rover.drive (the robot server on this Pi); it decides how to move.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass

import httpx

from rover import config
from rover.backend import Backend
from rover.games import GAMES, Games

NO_INPUT = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
TOOLS: list[dict] = [
    {
        "name": "look",
        "description": (
            "See a photo from your camera taken in the last few seconds. Use it only when the "
            "resident asks about something you could see, such as 'what am I holding?' or "
            "'can you see my glasses?'. Never use it just to check on the resident."
        ),
        "strict": True,
        "input_schema": NO_INPUT,
    },
    {
        "name": "request_staff",
        "description": (
            "Tell the nurses that this resident needs a person now. Use it when the resident asks "
            "for a nurse or a real person or agrees to one being called, and straight away when "
            "they report a fall, chest trouble or trouble breathing. The reason is shown to the "
            "nurse."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": (
                        "One plain-English line for the nurse: what the resident said or needs, "
                        "in their words where possible. No diagnosis."
                    ),
                }
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "stop",
        "description": (
            "Stop moving immediately and forget where you were going. Use it when someone says "
            "'stop' or 'wait' while you are moving, or when you might be in someone's way."
        ),
        "strict": True,
        "input_schema": NO_INPUT,
    },
    {
        "name": "go_to_room",
        "description": (
            "Drive to a room. Use it only when a resident or a member of staff explicitly asks "
            "you to go to a room. Never use it on your own initiative, and never to come back "
            "later. The destination must be a configured room name or an ArUco marker ID."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "room": {
                    "type": "string",
                    "minLength": 1,
                    "description": "A configured room name or ArUco marker ID.",
                }
            },
            "required": ["room"],
            "additionalProperties": False,
        },
    },
    {
        "name": "follow_patient",
        "description": (
            "Follow the person in front of you at a safe distance. Use it when the resident says "
            "'come with me', 'follow me' or similar."
        ),
        "strict": True,
        "input_schema": NO_INPUT,
    },
    {
        "name": "face_patient",
        "description": (
            "Turn on the spot to face the person. Use it when the resident says 'look at me', "
            "'over here' or similar."
        ),
        "strict": True,
        "input_schema": NO_INPUT,
    },
    {
        "name": "start_game",
        "description": (
            "Open a game on your touchscreen. Use it only after the resident asked to play and "
            "chose a game; never on your own initiative. Before it, ask whether they know how to "
            "play, unless you were told they already know that game."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "game": {
                    "type": "string",
                    "enum": list(GAMES),
                    "description": "bingo, tic_tac_toe, or memory (memory match).",
                },
                "knows_rules": {
                    "type": "boolean",
                    "description": "True if the resident said they know how to play it.",
                },
            },
            "required": ["game", "knows_rules"],
            "additionalProperties": False,
        },
    },
    {
        "name": "end_game",
        "description": (
            "Close the game on your screen and show your face again. Use it when the resident "
            "wants to stop playing."
        ),
        "strict": True,
        "input_schema": NO_INPUT,
    },
]


@dataclass
class ToolContext:
    backend: Backend
    call_id: str | None
    resident_id: str | None = None
    games: Games | None = None


def _look() -> str | list[dict]:
    path = config.LATEST_JPG
    try:
        age = time.time() - path.stat().st_mtime
        image = path.read_bytes()
    except OSError as exc:
        print(f"tool look: no image: {exc}")
        return "camera image not available"
    if age > config.LOOK_MAX_AGE_S:
        print(f"tool look: image is {age:.0f}s old")
        return "camera image not available"
    return [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.standard_b64encode(image).decode("ascii"),
            },
        },
        {"type": "text", "text": "Photo from your camera, taken just now."},
    ]


def _request_staff(args: dict, ctx: ToolContext) -> str:
    reason = str(args.get("reason") or "").strip() or "Resident asked for a member of staff."
    if ctx.call_id is None:
        print("tool request_staff: no active call, nobody notified")
        return "could not notify staff: no active call"
    call = ctx.backend.score(ctx.call_id, 3, "asks_for_nurse", reason, 1.0)
    if call is None:
        return "could not notify staff: the backend did not answer"
    return "staff notified"


def post_pi(path: str, body: dict) -> str | None:
    """POST to rover.drive's server; returns a short failure reason, or None when it took it."""
    url = f"{config.PI_SERVER_URL}{path}"
    try:
        response = httpx.post(url, json=body, timeout=config.HTTP_TIMEOUT_S)
    except httpx.HTTPError as exc:
        print(f"pi server: POST {url} failed: {type(exc).__name__}: {exc}")
        return type(exc).__name__
    if response.is_error:
        print(f"pi server: POST {url} failed: {response.status_code} {response.text[:200]}")
        return str(response.status_code)
    return None


def _move(name: str, path: str, body: dict, done: str) -> str:
    reason = post_pi(path, body)
    return f"{name} failed ({reason})" if reason else done


def _go_to_room(args: dict) -> str:
    room = str(args.get("room") or "").strip()
    if config.marker_for_room(room) is None:
        print(f"tool go_to_room: refused unknown room {room!r}")
        return f"no configured room or marker {room!r}"
    return _move("go_to_room", "/go_to", {"room": room}, f"on the way to room {room}")


def _start_game(args: dict, ctx: ToolContext) -> str:
    game = str(args.get("game") or "")
    if game in GAMES and args.get("knows_rules") is True and ctx.resident_id:
        # remembered so the robot does not ask again; the backend drops a repeat as a duplicate
        ctx.backend.remember(ctx.resident_id, f"Knows how to play {GAMES[game]}.", ["game", game])
    if ctx.games is None:
        return "the screen is not available, so you cannot play a game now"
    return ctx.games.start(game)


def run_tool(name: str, args: dict, ctx: ToolContext) -> str | list[dict]:
    """Return the content for the tool_result block."""
    if name == "look":
        return _look()
    if name == "request_staff":
        return _request_staff(args, ctx)
    if name == "stop":
        return _move("stop", "/stop", {}, "stopped")
    if name == "go_to_room":
        return _go_to_room(args)
    if name == "follow_patient":
        return _move("follow_patient", "/follow", {}, "following the resident")
    if name == "face_patient":
        return _move("face_patient", "/face", {}, "turning to face the resident")
    if name == "start_game":
        return _start_game(args, ctx)
    if name == "end_game":
        return ctx.games.stop() if ctx.games is not None else "no game was open"
    print(f"tool: unknown tool {name!r}")
    return f"unknown tool {name}"
