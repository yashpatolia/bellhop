"""Claude replies for the visit, streamed sentence by sentence so the voice can start early."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable

import anthropic

from rover import config
from rover.agent.tools import TOOLS, ToolContext, run_tool

FALLBACK_LINE = "Sorry, give me a moment."
FALLBACK_TONE = "calm"
WAIT = "WAIT"  # the persona's answer to speech that was not meant for the robot
TAG = re.compile(r"\[([A-Za-z_]+)\]")
LEADING_TAG = re.compile(r"^\s*\[([A-Za-z_]+)\]\s*")
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"


def claude_client() -> anthropic.Anthropic | None:
    """A client when any Anthropic credential resolves (env key, token or an `ant auth` profile)."""
    client = anthropic.Anthropic()
    if client.api_key or client.auth_token or client.credentials:
        return client
    return None


def split_tone(text: str) -> tuple[str, str]:
    match = LEADING_TAG.match(text)
    if match is None:
        return config.DEFAULT_TONE, text.strip()
    tag = match.group(1).lower()
    return (tag if tag in config.TONES else config.DEFAULT_TONE), text[match.end() :].strip()


def strip_tags(text: str) -> str:
    return " ".join(TAG.sub("", text).split())


class SentenceSplitter:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: str) -> list[str]:
        self._buffer += chunk
        *done, self._buffer = SENTENCE_BREAK.split(self._buffer)
        return [sentence.strip() for sentence in done if sentence.strip()]

    def flush(self) -> list[str]:
        rest, self._buffer = self._buffer.strip(), ""
        return [rest] if rest else []


class _Turn:
    """One reply: what has been said, in which tone, and whether any text has arrived."""

    def __init__(self, on_sentence: Callable[[str, str], None], cancel: threading.Event | None):
        self._on_sentence = on_sentence
        self._cancel = cancel
        self._lock = threading.Lock()  # the first-text timer speaks from its own thread
        self._splitter = SentenceSplitter()
        self.got_text = threading.Event()
        self.tone: str | None = None
        self.spoken: list[str] = []
        self.saw_wait = False

    def cancelled(self) -> bool:
        return self._cancel is not None and self._cancel.is_set()

    def say(self, tone: str, line: str) -> None:
        with self._lock:
            if self.cancelled():
                return
            self.spoken.append(line)
            self._on_sentence(tone, line)

    def add_text(self, chunk: str) -> None:
        self.got_text.set()
        for sentence in self._splitter.feed(chunk):
            self._speak(sentence)

    def flush(self) -> None:
        for sentence in self._splitter.flush():
            self._speak(sentence)

    def _speak(self, sentence: str) -> None:
        if self.tone is None:
            self.tone, sentence = split_tone(sentence)
        sentence = strip_tags(sentence)
        if sentence.rstrip(".!") == WAIT:
            self.saw_wait = True
        elif sentence:
            self.say(self.tone, sentence)

    def first_text_timeout(self) -> None:
        if not self.got_text.is_set() and not self.cancelled():
            print(f"fallback: no reply in {config.FIRST_TEXT_TIMEOUT_S:g}s")
            self.say(FALLBACK_TONE, FALLBACK_LINE)

    def fail(self, reason: str) -> None:
        print(f"fallback: {reason}")
        if not self.spoken:
            self.say(FALLBACK_TONE, FALLBACK_LINE)


class Brain:
    def __init__(self, client=None) -> None:
        self.client = client if client is not None else claude_client()
        if self.client is None:
            print("fallback: no ANTHROPIC_API_KEY; every reply will be the fallback line")

    def reply(
        self,
        system: str,
        messages: list[dict],
        on_sentence: Callable[[str, str], None],
        tool_ctx: ToolContext | None,
        allow_tools: bool = True,
        cancel: threading.Event | None = None,
    ) -> tuple[str, bool]:
        """Speak the reply through on_sentence(tone, sentence); return (text, wanted_tool).

        With allow_tools=False (an early draft) tools are still offered, so the model's wish to
        use one is visible, but none is run: wanted_tool=True tells the caller to redo the turn.
        """
        if self.client is None:
            print("fallback: no ANTHROPIC_API_KEY")
            on_sentence(FALLBACK_TONE, FALLBACK_LINE)
            return FALLBACK_LINE, False
        turn = _Turn(on_sentence, cancel)
        timer = threading.Timer(config.FIRST_TEXT_TIMEOUT_S, turn.first_text_timeout)
        timer.daemon = True
        timer.start()
        wanted_tool = False
        try:
            wanted_tool = self._run(system, list(messages), turn, tool_ctx, allow_tools)
        except anthropic.APIStatusError as exc:
            turn.fail(f"Claude API error {exc.status_code}: {exc.message}")
        except anthropic.APIConnectionError as exc:
            turn.fail(f"no connection to Claude ({type(exc).__name__})")
        except Exception as exc:  # errors mid-stream (e.g. a read timeout) arrive unwrapped
            turn.fail(f"Claude stream failed: {exc!r}")
        finally:
            timer.cancel()
        if turn.saw_wait and not turn.spoken:
            return WAIT, False
        return " ".join(turn.spoken), wanted_tool

    def _run(
        self,
        system: str,
        messages: list[dict],
        turn: _Turn,
        tool_ctx: ToolContext | None,
        allow_tools: bool,
    ) -> bool:
        for _ in range(config.BRAIN_MAX_TOOL_ROUNDS + 1):
            with self.client.beta.messages.stream(
                model=config.BRAIN_MODEL,
                max_tokens=config.MAX_REPLY_TOKENS,
                system=system,
                messages=messages,
                tools=TOOLS,
                # No extended thinking: the reply is spoken, so the first word must come fast.
                thinking={"type": "between_tools"},
                output_config={"effort": config.BRAIN_EFFORT},
                betas=[SERVER_FALLBACK_BETA],
                fallbacks="default",
                timeout=config.BRAIN_STREAM_TIMEOUT_S,
            ) as stream:
                for event in stream:
                    if turn.cancelled():
                        return False
                    if event.type == "text":
                        turn.add_text(event.text)
                final = stream.get_final_message()
            turn.flush()
            if final.stop_reason == "refusal":
                category = final.stop_details.category if final.stop_details else None
                turn.fail(f"Claude declined to answer ({category})")
                return False
            tool_uses = [block for block in final.content if block.type == "tool_use"]
            if final.stop_reason != "tool_use" or not tool_uses:
                return False
            if not allow_tools:
                return True
            results = [_tool_result(block, tool_ctx) for block in tool_uses]
            messages = [
                *messages,
                {"role": "assistant", "content": final.content},
                {"role": "user", "content": results},
            ]
        print(f"brain: gave up after {config.BRAIN_MAX_TOOL_ROUNDS} tool rounds")
        return False


def _tool_result(block, tool_ctx: ToolContext | None) -> dict:
    args = block.input if isinstance(block.input, dict) else {}
    if tool_ctx is None:
        print(f"brain: tool {block.name} asked for but no tool context was given")
        content = "tools are not available right now"
    else:
        content = run_tool(block.name, args, tool_ctx)
    print(f"brain: tool {block.name} -> {content if isinstance(content, str) else 'image'}")
    return {"type": "tool_result", "tool_use_id": block.id, "content": content}
