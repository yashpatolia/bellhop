"""Build the brain's system prompt and keep this visit's conversation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from rover import config
from rover.games import GAMES

ACTIVITY_BY_CATEGORY = {"pain": "pain_check", "confusion": "gentle"}
MAX_MEMORY_FACTS = 3
PREFERENCE_FLAGS = ("hard_of_hearing", "quiet_mode", "night_mode")
SPEAKER_BY_ROLE = {
    "user": "resident",
    "resident": "resident",
    "assistant": "robot",
    "robot": "robot",
}
ROLE_BY_SPEAKER = {"resident": "user", "robot": "assistant"}
VISIT_START = "(The robot has arrived and greeted the resident.)"
GREETING = (
    "(The robot has just arrived in room {room}. Greet the resident and ask how you can help, "
    "then add in a few words that you can also play games on your screen.)"
)
CHAT_GREETING = (
    "(Someone has just called you over by name for a chat; they did not press a call bell. Greet "
    "them and ask how you can help, then add in a few words that you can also play games on your "
    "screen.)"
)
GAMES_QUERY = "knows how to play a game"  # recalls the facts start_game saved


def games_known(facts: list[dict]) -> list[str]:
    """The games a resident knows, from the memory facts start_game tagged with the game."""
    return sorted({tag for fact in facts for tag in fact.get("tags") or () if tag in GAMES})


def load_persona() -> str:
    text = (config.AGENT_DIR / "persona.md").read_text(encoding="utf-8")
    return text.replace("{robot_name}", config.ROBOT_NAME)


def load_activity(name: str) -> str:
    return (config.AGENT_DIR / "activities" / f"{name}.md").read_text(encoding="utf-8")


def activity_for(category: str | None) -> str | None:
    return ACTIVITY_BY_CATEGORY.get(category or "")


def _resident_block(
    resident: dict | None,
    preferences: dict | None,
    memories: list[dict],
    known: Sequence[str] = (),
) -> str:
    if resident is None:
        return "## Who you are talking to\nUnknown. Ask their name."
    lines = ["## Who you are talking to"]
    for label, key in (("Name", "name"), ("Room", "room"), ("Birth year", "birth_year")):
        if resident.get(key):
            lines.append(f"{label}: {resident[key]}")
    if resident.get("risk_flags"):
        lines.append(f"Risk flags: {', '.join(resident['risk_flags'])}")
    prefs = preferences or {}
    wanted = [key.replace("_", " ") for key in PREFERENCE_FLAGS if prefs.get(key) is True]
    if prefs.get("favourite_drink"):
        wanted.append(f"favourite drink: {prefs['favourite_drink']}")
    if wanted:
        lines.append(f"Preferences: {', '.join(wanted)}")
    facts = [m["text"] for m in memories if m.get("text")][:MAX_MEMORY_FACTS]
    if facts:
        lines.append("Things you know about them:")
        lines += [f"- {fact}" for fact in facts]
    if known:
        lines.append(f"Games they already know how to play: {', '.join(GAMES[g] for g in known)}")
    return "\n".join(lines)


def build_system_prompt(
    resident: dict | None,
    preferences: dict | None,
    memories: list[dict],
    scene_note: str,
    activity: str | None,
    now: datetime,
    known_games: Sequence[str] = (),
    game_status: str | None = None,
    actions: Sequence[str] = (),
) -> str:
    parts = [load_persona(), _resident_block(resident, preferences, memories, known_games)]
    if scene_note:
        parts.append(f"## What your camera sees\n{scene_note}")
    parts.append(f"## Now\nIt is {now:%A %d %B %Y}, {now:%H:%M}.")
    if activity:
        parts.append(load_activity(activity))
    if game_status:
        parts.append(
            "## Right now: a game is on your screen\n"
            f"{game_status}\n"
            "You opened it with start_game. Call start_game again only to switch to a different "
            "game.\nKeep each reply to one short sentence while they play."
        )
    if actions:
        done = "\n".join(f"- {action}" for action in actions[-config.ACTIONS_SHOWN :])
        parts.append(
            "## What you have done this visit\n"
            "Your tool calls and what each returned, oldest first. Trust these results: never say "
            "one that worked did not happen, and never say one worked if its result says it "
            "failed. Do not repeat one unless it failed, the resident asks, or something new "
            "happens (use request_staff again for a new problem, and stop whenever needed):\n"
            f"{done}"
        )
    return "\n\n".join(part.strip() for part in parts)


class VisitHistory:
    """This visit's lines, resent to the brain on every turn."""

    def __init__(self) -> None:
        self._lines: list[tuple[str, str]] = []

    def add(self, role: str, text: str) -> None:
        if role not in SPEAKER_BY_ROLE:
            raise ValueError(f"unknown role {role!r}")
        if text.strip():
            self._lines.append((SPEAKER_BY_ROLE[role], text.strip()))

    def messages(self) -> list[dict]:
        merged: list[dict] = []
        for speaker, text in self._lines:
            role = ROLE_BY_SPEAKER[speaker]
            if merged and merged[-1]["role"] == role:
                merged[-1]["content"] += f" {text}"
            else:
                merged.append({"role": role, "content": text})
        # shortcut: older exchanges are dropped; summarise them if visits get long
        recent = merged[-2 * config.HISTORY_EXCHANGES :]
        if recent and recent[0]["role"] == "assistant":
            if len(recent) < len(merged):
                recent = recent[1:]  # the cut split an exchange: drop its orphaned robot line
            else:
                # The API needs a user turn first; keep the robot's greeting rather than drop it.
                recent.insert(0, {"role": "user", "content": VISIT_START})
        return recent

    def transcript(self) -> list[tuple[str, str]]:
        return list(self._lines)
