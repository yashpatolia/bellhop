"""Voice process: find the robot's call, start the visit, talk, triage, resolve, send it home.

Run: uv run python -m rover.speech [--call <id>] [--no-face] [--room <room>]
The main thread only moves audio and Flux events; replies, posts and the ending run one job at a
time on a worker, so the mic queue is drained and Flux keeps getting audio while the robot talks.
"""

from __future__ import annotations

import argparse
import math
import queue
import signal
import sys
import threading
import time
import traceback
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from rover import config, obslog, safety
from rover.agent import feeds
from rover.agent.books import Reader
from rover.agent.brain import WAIT, Brain
from rover.agent.context import (
    CHAT_GREETING,
    GAMES_QUERY,
    GREETING,
    VisitHistory,
    activity_for,
    build_system_prompt,
    games_known,
)
from rover.agent.tone import AskTone, TonePick, ask_jev_tone
from rover.agent.tools import ToolContext, post_pi
from rover.backend import Backend
from rover.eyes import Eyes
from rover.games import Games
from rover.speech import ledguard
from rover.speech.flux import FluxStream
from rover.speech.gates import FaceGate, Gates, VisionListener
from rover.speech.mic import Mic
from rover.speech.offline import OfflineSTT
from rover.speech.tts import Voice, effective_tone
from rover.speech.visit import (
    TurnLog,
    backfill,
    drive_arrived,
    drop_reason,
    is_goodbye,
    messages_with,
    normalize,
    pair_blocks,
    resolve_decision,
    scene_note,
    should_start_visit,
    stt_fallback_due,
    urgency_rank,
    wake_text,
)
from rover.speech.wake import WakeListener
from rover.status import StatusReporter, fetch_snapshot
from rover.triage.triage import triage_and_post

FRAME_S = 1 / config.CAMERA_FPS  # check the start conditions once per vision frame
RESOLVE_TRIES = 4  # a resolve the backend did not accept is tried this many times
RESOLVE_RETRY_S = 0.5  # first wait between tries; doubles each time
DRIVE_CHECK_S = 1.0  # how often the drive server is asked whether the robot has arrived
DRAFT_POLL_S = 0.05  # how often a confirmed draft is checked for its next sentence
ZEROS = np.zeros(config.BLOCK_SAMPLES, dtype=np.int16)
CHAT_SLEEP = f"I'll be right here. Just say hey {config.ROBOT_NAME} when you need me."
BELL_GOODBYE = "Sorry, someone has rung their bell, so I need to go. Bye for now!"
CHAT_ID = "chat"  # the call id of a chat, which the backend never sees
# chats asked for, each with the words said after "Hey Bellhop" ("" from robot.sh open, SIGUSR1).
# A SimpleQueue: its put() is safe inside a signal handler
CHATS: queue.SimpleQueue[str] = queue.SimpleQueue()
QUIET_GOODBYE = "I'll let you rest now. Press your bell any time you need me."
NURSE_COMING = "A nurse is on the way, I'll stay with you."
NO_MIC = "Sorry, I can't hear right now, so I've asked a nurse to come."
CHAT_NO_MIC = "Sorry, I can't hear right now. Please tell a nurse my microphone isn't working."
FINISHED = {"resolved", "closed"}
ENTER = threading.Event()  # Enter on stdin: the nurse has arrived
TriageFn = Callable[[Backend, str, list[tuple[str, str]], list[str]], "dict | None"]


def read_enter() -> None:
    while True:
        if not sys.stdin.readline():
            print("visit: stdin closed, so Enter cannot resolve calls (nurse_acked still does)")
            return
        ENTER.set()


@dataclass
class Draft:
    """An early reply written on EagerEndOfTurn: buffered, never spoken until EndOfTurn agrees."""

    transcript: str
    cancel: threading.Event = field(default_factory=threading.Event)
    sentences: list[tuple[str, str]] = field(default_factory=list)
    text: str = ""
    wanted_tool: bool = False
    thread: threading.Thread | None = None


class Visit:
    greeting = GREETING  # Claude's cue to say hello
    no_mic = NO_MIC
    exit_without_mic = True  # a call: a nurse has been asked to come, so stop

    def __init__(
        self,
        call: dict,
        room: str,
        backend: Backend,
        brain: Brain,
        voice: Voice,
        stt: OfflineSTT,
        listener: VisionListener,
        face: FaceGate,
        gates: Gates | None = None,
        triage_fn: TriageFn | None = None,
        eyes: Eyes | None = None,
        games: Games | None = None,
    ) -> None:
        self.call = call
        self.call_id: str = call["id"]
        self.room = room
        self.backend, self.brain, self.voice, self.stt = backend, brain, voice, stt
        self.listener, self.face = listener, face
        self.games = games  # None: no screen, so start_game says it cannot play
        self.reader = Reader(call.get("resident_id"))  # a book read aloud, between turns
        self.tool_ctx = ToolContext(
            backend, self.call_id, call.get("resident_id"), games, reader=self.reader
        )
        self.gates = gates if gates is not None else Gates()
        self.triage_fn = triage_fn  # None = the real triage_and_post (looked up when used)
        self.eyes = eyes if eyes is not None else Eyes()  # Eyes() alone draws nothing
        # Jev is an optional background tone suggestion.  Tests and local deployments can set
        # this to None; with no key its worker returns immediately.
        self.ask_tone: AskTone | None = ask_jev_tone
        self.tone_pick: TonePick | None = None
        self.mic = Mic()
        self.mood = config.DEFAULT_TONE  # the tone of the sentence being spoken, for the face
        self.voice.on_play = self.on_play
        self.flux: FluxStream | None = None
        self.flux_ok = False
        self.events: queue.Queue[tuple[str, str, float]] = queue.Queue()
        self.history = VisitHistory()
        self.log = TurnLog()
        self.resident: dict | None = None
        self.preferences: dict | None = None
        self.memories: list[dict] = []
        self.games_known: list[str] = []
        self.risk_flags: list[str] = []
        # one job at a time (greeting, each turn, the ending) keeps the history in order
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.job: Future | None = None
        # Moonshine takes seconds on the Pi: its own thread, so replies and game lines go on
        self.stt_pool = ThreadPoolExecutor(max_workers=1)
        self.transcribing: list[Future] = []  # in turn order; each turn then goes to the worker
        self.submitted = 0  # jobs handed to the worker; more than started = a turn is waiting
        self.started = 0
        self.turns_submitted = 0  # the same for turns only: they are answered together
        self.turns_started = 0
        self.reply_quiet = False  # a reply is being written and has said nothing yet
        self.waiting_face_ok = False  # a skipped turn was said to the robot (worker only)
        self.lock = threading.Lock()
        self.triage_threads: list[threading.Thread] = []
        self.latest_call: dict | None = None
        # audio and turn state, main thread only
        self.outbox: list[np.ndarray] = []
        self.closed_run = 0
        self.turn_audio: list[np.ndarray] = []
        self.turn_face_ok = False
        self.turn_pending = False
        self.speech_end = time.monotonic()
        self.skip_flux_turn = False
        self.draft: Draft | None = None
        self.interrupt = threading.Event()  # the running job's: set, its reply stops short
        # written by the worker, read by the main thread
        self.last_reply = ""
        self.last_activity = time.monotonic()
        self.read_done_at = -math.inf  # when the last part of the story finished
        self.read_paused = False  # a turn stopped the story; a WAIT reply to it reads on
        self.phase = "talk"  # talk -> ending -> (wait_nurse -> resolving) -> over
        self.nurse_status: str | None = None
        self.done = False
        self.first_text_at: float | None = None
        self.first_sound_at: float | None = None

    # ---- setup and the main loop (main thread)

    def load_context(self) -> None:
        resident_id = self.call.get("resident_id")
        if not resident_id:
            print(f"visit: no resident on file for room {self.room}; using the generic prompt")
            self.voice.settings = None
            return
        self.resident = self.backend.resident(resident_id)
        self.preferences = self.backend.preferences(resident_id)
        self.memories = self.backend.memory(resident_id, q="")
        self.games_known = games_known(self.backend.memory(resident_id, q=GAMES_QUERY, k=10))
        self.voice.settings = self.backend.speech_settings(resident_id)
        self.risk_flags = list((self.resident or {}).get("risk_flags") or [])

    def begin(self) -> None:
        """Tell the backend the robot is with the resident (starts its response-time clock)."""
        accepted = self.backend.in_visit(self.call_id)
        obslog.event("visit.in_visit", call_id=self.call_id, room=self.room, accepted=accepted)
        if not accepted:
            print("visit: in-visit was not accepted; talking anyway")
        self.load_context()
        self.eyes.base = "listening"
        if self.games is not None:
            self.games.attach(self.events.put)  # its lines come back through handle_events

    def run(self) -> None:
        self.begin()
        try:
            self.mic.start()
        except Exception:
            print("fallback: no microphone; saying so (a call is posted triage-failed)")
            self.say_line(self.no_mic)
            self.backend.triage_failed(self.call_id)
            if self.exit_without_mic:
                raise SystemExit(1) from None
            self.eyes.base = "idle"
            if self.games is not None:
                self.games.attach(None)
            self.end()  # stops the bell watch; the robot still goes to the next bell
            return
        try:
            name = (self.resident or {}).get("name", "")
            self.flux = FluxStream([config.ROBOT_NAME, name], self.on_flux)
            self.flux_ok = self.flux.start()
            if not self.flux_ok:
                print("fallback: no Flux this visit; every turn goes to Moonshine")
            self.submit(self.greet)
            while not (self.done and self.idle()):
                block = self.mic.read()
                if block is not None:
                    self.hear(block, time.monotonic())
                self.handle_events()
                self.check_timers(time.monotonic())
        finally:  # also on SIGTERM (SystemExit) or a crash: the mic must not stay open
            self.phase = "over"
            self.eyes.base = "idle"
            if self.games is not None:
                self.games.stop()
                self.games.attach(None)
            self.cancel_draft()
            if self.flux is not None:
                self.flux.close()
            self.mic.stop()
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.stt_pool.shutdown(wait=False, cancel_futures=True)
        print(f"visit: call {self.call_id} done")

    def on_flux(self, event: str, transcript: str) -> None:
        self.events.put((event, transcript, time.monotonic()))  # handled on the main thread

    def hear(self, block: np.ndarray, now: float) -> None:
        if not self.mic.muted(now) and self.gates.check(block, now):
            blocks = backfill(self.mic.preroll(), self.closed_run)
            self.closed_run = 0
            self.turn_audio += blocks
            self.turn_pending = True
            self.speech_end = now
            self.turn_face_ok = self.turn_face_ok or self.face.ok(now)
        else:
            blocks = [ZEROS]  # gated or muted: zeros keep the socket alive and the timing true
            self.closed_run += 1
        pairs, self.outbox = pair_blocks(self.outbox + blocks)
        for pcm in pairs:
            self.flux.send(pcm)

    def handle_events(self) -> None:
        while True:
            try:
                event, text, at = self.events.get_nowait()
            except queue.Empty:
                return
            if event == "StartOfTurn":
                self.skip_flux_turn = False
                self.cancel_draft()
            elif event == "EagerEndOfTurn":
                self.start_draft(text)
            elif event == "TurnResumed":
                self.cancel_draft()
            elif event == "EndOfTurn":
                self.end_of_turn(text, at)
            elif event == "GameTouch":
                self.last_activity = at  # playing quietly is not a quiet visit
            elif event in ("GameSay", "GameNote") and self.phase == "talk":
                self.submit(self.game_line, text, event == "GameNote")
            elif event == "Error":
                self.flux_ok = False
                self.cancel_draft()
                print(f"fallback: Flux stopped ({text}); turns go to Moonshine")

    def end_of_turn(self, text: str, at: float) -> None:
        draft, self.draft = self.draft, None
        audio, face_ok, speech_end = self.take_turn()
        if self.skip_flux_turn:
            self.skip_flux_turn = False
            reason = "Moonshine already answered this turn"
        else:
            reason = drop_reason(text, self.last_reply)
        if reason:
            print(f"visit: dropped turn {text!r}: {reason}")
            if draft is not None:
                draft.cancel.set()
            return
        named = wake_text(text) is not None
        if not self.idle() and (named or (self.reply_quiet and face_ok)):
            # its name, or more words before the reply began: stop it, answer them all at once
            why = "the robot's name" if named else "more speech before the reply began"
            print(f"visit: heard {why}; cutting the reply in progress short")
            self.interrupt.set()
        if self.transcribing:  # Moonshine is still on an earlier turn: this one goes after it
            if draft is not None:
                draft.cancel.set()
            heard: Future = Future()
            heard.set_result((text, "flux", audio, face_ok, speech_end, at))
            self.transcribing.append(heard)
            return
        stt_s = at - speech_end
        self.submit_turn(text, "flux", audio, stt_s, speech_end, draft, face_ok)

    def check_timers(self, now: float) -> None:
        if stt_fallback_due(self.turn_pending, self.flux_ok, now - self.speech_end):
            if self.flux_ok:
                print(
                    f"fallback: no Flux result {config.FLUX_TURN_LIMIT_S:g} s after speech; "
                    "transcribing the turn with Moonshine"
                )
            else:
                print("fallback: Flux is down; transcribing the turn with Moonshine")
            self.skip_flux_turn = self.flux_ok
            self.cancel_draft()
            self.transcribing.append(self.stt_pool.submit(self.transcribe, *self.take_turn()))
        while self.transcribing and self.transcribing[0].done():
            self.heard_turn(*self.transcribing[0].result())
            self.transcribing.pop(0)  # after the submit: resident_spoke() sees one or the other
        reading = self.phase == "talk" and self.reader.reading and not self.turn_pending
        if reading and self.idle() and now - self.read_done_at >= config.READ_GAP_S:
            self.submit(self.read_on)  # the gap before it is when the mic can hear them
        quiet_s = now - self.last_activity
        if self.phase == "talk" and self.idle() and not self.turn_pending:
            if quiet_s >= self.quiet_limit_s():
                print(f"visit: {self.quiet_limit_s():g} s without a turn; ending the visit")
                self.phase = "ending"
                self.submit(self.finish, True)
        waiting = self.nurse_status or ENTER.is_set()
        if self.phase == "wait_nurse" and waiting and not self.transcribing:
            self.phase = "resolving"
            self.submit(self.resolve_after_nurse)

    def quiet_limit_s(self) -> float:
        return config.VISIT_QUIET_END_S

    def take_turn(self) -> tuple[np.ndarray, bool, float]:
        audio = np.concatenate(self.turn_audio) if self.turn_audio else ZEROS[:0]
        face_ok = self.turn_face_ok
        self.turn_audio, self.turn_face_ok, self.turn_pending = [], False, False
        self.last_activity = max(self.last_activity, self.speech_end)  # dropped or not: they spoke
        return audio, face_ok, self.speech_end

    def start_draft(self, text: str) -> None:
        self.cancel_draft()
        if not self.idle() or self.phase not in ("talk", "wait_nurse") or not normalize(text):
            return  # the history is still changing, so a draft now would answer the wrong thing
        draft = Draft(text)
        system, messages = self.system_prompt(), messages_with(self.history, text)

        def write() -> None:
            draft.text, draft.wanted_tool = self.brain.reply(
                system,
                messages,
                lambda tone, sentence: draft.sentences.append((tone, sentence)),
                None,
                allow_tools=False,
                cancel=draft.cancel,
            )

        draft.thread = threading.Thread(target=write, daemon=True)
        draft.thread.start()
        self.draft = draft

    def cancel_draft(self) -> None:
        if self.draft is not None:
            self.draft.cancel.set()
            self.draft = None

    def idle(self) -> bool:
        return (self.job is None or self.job.done()) and not self.transcribing

    def submit(self, job, *args) -> None:
        self.submitted += 1
        self.job = self.pool.submit(self.guarded, job, *args)

    def submit_turn(self, *turn) -> None:
        self.turns_submitted += 1
        self.submit(self.queued_turn, *turn)

    def queued_turn(self, *turn) -> None:
        """A heard turn on the worker: answered, unless more turns already wait behind it."""
        self.turns_started += 1
        answer = self.turns_submitted == self.turns_started
        face_ok = turn[-1] or self.waiting_face_ok  # joined like their words: any said to it
        self.waiting_face_ok = False if answer else face_ok
        self.handle_turn(*turn[:-1], face_ok, answer=answer)

    def guarded(self, job, *args) -> None:
        self.started += 1
        self.interrupt = threading.Event()
        try:
            job(*args)
        except Exception as exc:
            print(f"visit: {job.__name__} failed: {exc!r}")
            traceback.print_exc()
        finally:
            self.voice.wait()  # its last sentence still plays: the job is done when it ends

    # ---- jobs (worker thread, one at a time)

    def system_prompt(self) -> str:
        fresh = self.listener.age(time.monotonic()) <= config.VISION_STALE_S
        category = (self.latest_call or {}).get("category")
        return build_system_prompt(
            self.resident,
            self.preferences,
            self.memories,
            scene_note(self.listener.latest() if fresh else None),
            activity_for(category),
            datetime.now(),
            self.games_known,
            self.games.status() if self.games is not None else None,
            self.tool_ctx.done,
            self.reader.status(),
        )

    def greet(self) -> None:
        hello = self.greeting.format(room=self.room)
        messages = [{"role": "user", "content": hello}]  # never posted as a turn
        self.eyes.base = "thinking"
        try:
            full, _ = self.brain.reply(
                self.system_prompt(), messages, self.speak, self.tool_ctx, cancel=self.interrupt
            )
        finally:
            self.eyes.base = "listening"
        self.record_robot(full)
        self.last_activity = time.monotonic()

    def transcribe(
        self, audio: np.ndarray, face_ok: bool, speech_end: float
    ) -> tuple[str, str, np.ndarray, bool, float, float]:
        """Moonshine's thread. heard_turn (main thread) takes what it heard."""
        try:
            text = self.stt.transcribe(audio)
        except Exception as exc:  # guarded() caught this when Moonshine ran on the worker
            print(f"visit: Moonshine failed: {exc!r}")
            text = ""
        return text, "moonshine", audio, face_ok, speech_end, time.monotonic()

    def heard_turn(
        self, text: str, source: str, audio: np.ndarray, face_ok: bool, speech_end: float, at: float
    ) -> None:
        """A turn that waited for Moonshine (its own, or a Flux turn behind it), in order."""
        reason = drop_reason(text, self.last_reply)
        if reason:
            print(f"visit: dropped {source} turn {text!r}: {reason}")
            return
        stt_s = at - speech_end
        self.submit_turn(text, source, audio, stt_s, speech_end, None, face_ok)

    def handle_turn(
        self,
        text: str,
        source: str,
        audio: np.ndarray,
        stt_s: float,
        speech_end: float,
        draft: Draft | None,
        face_ok: bool,
        answer: bool = True,
    ) -> None:
        if self.done:
            print(f"visit: dropped turn {text!r}: the call is already resolved")
            return
        print(f"resident: {text}  ({source})")
        # any turn stops the story, even one not facing the robot: it may be a call for help
        self.read_paused = self.reader.pause() or self.read_paused  # merged turns keep it
        obslog.event(
            "visit.turn", call_id=self.call_id, room=self.room, source=source, chars=len(text)
        )
        self.history.add("resident", text)
        self.backend.add_turn(self.call_id, "resident", text)  # before triage reads the transcript
        self.start_triage()
        if not answer:
            # the history joins it to the turns waiting behind it, and the last one replies
            print("visit: more speech is waiting; answering it all together")
            if draft is not None:
                draft.cancel.set()
            self.last_activity = time.monotonic()
            return
        if not face_ok:
            # posted and triaged anyway, so a call for help from the floor is never lost
            print("visit: no one was facing the robot during that turn; triaged it, no reply")
            self.read_paused = False  # the story stays stopped
            if draft is not None:
                draft.cancel.set()
            self.last_activity = time.monotonic()
            return
        self.first_text_at = self.first_sound_at = None
        self.eyes.base = "thinking"  # until the first sentence brings the reply's tone
        if self.ask_tone is not None:
            self.tone_pick = TonePick(self.history.transcript(), self.ask_tone)
        self.reply_quiet = True  # until its first sentence: more speech restarts the reply
        try:
            full = self.reply_to(text, draft)
        finally:
            self.reply_quiet = False
            self.eyes.base = "listening"
            self.tone_pick = None
        self.record_robot(full)
        if self.read_paused and full == WAIT:
            self.reader.resume()  # that speech was not for the robot: read on
        self.read_paused = False

        def since(at: float | None) -> float | None:
            return None if at is None else at - speech_end

        self.log.write(
            self.call_id,
            text,
            source,
            audio,
            stt_s,
            since(self.first_text_at),
            since(self.first_sound_at),
        )
        self.last_activity = time.monotonic()
        if self.phase == "talk" and is_goodbye(text):
            print("visit: the resident said goodbye")
            self.phase = "ending"
            self.finish(quiet=False)

    def reply_to(self, text: str, draft: Draft | None) -> str:
        already_said: set[str] = set()
        if draft is not None and normalize(draft.transcript) == normalize(text):
            # speak each sentence as it arrives, so first words and the 3 s fallback stay on time
            spoken = 0
            while draft.thread.is_alive() or spoken < len(draft.sentences):
                if self.interrupt.is_set():
                    draft.cancel.set()
                    return " ".join(sentence for _, sentence in draft.sentences[:spoken])
                if spoken < len(draft.sentences):
                    self.speak(*draft.sentences[spoken])
                    spoken += 1
                else:
                    draft.thread.join(DRAFT_POLL_S)
            if not draft.wanted_tool and (draft.sentences or draft.text == WAIT):
                return draft.text
            already_said = {normalize(sentence) for _, sentence in draft.sentences}
        if draft is not None:
            draft.cancel.set()

        def speak_new(tone: str, sentence: str) -> None:
            if normalize(sentence) not in already_said:  # the draft said it before wanting a tool
                self.speak(tone, sentence)

        full, _ = self.brain.reply(
            self.system_prompt(),
            self.history.messages(),
            speak_new,
            self.tool_ctx,
            cancel=self.interrupt,
        )
        return full

    def speak(self, tone: str, sentence: str) -> None:
        self.reply_quiet = False
        if self.first_text_at is None:
            self.first_text_at = time.monotonic()
        if self.tone_pick is not None:
            tone = self.tone_pick.choose(tone)
        self.mood = effective_tone(tone, getattr(self.voice, "settings", None))
        self.voice.say(sentence, self.mood)  # returns as the sentence starts playing
        if self.first_sound_at is None:
            self.first_sound_at = time.monotonic()

    def on_play(self, until: float | None) -> None:
        """The voice's hook: a sentence's sound plays until `until`. None: it has stopped."""
        if until is None:
            self.mic.set_speaking(False)
            return
        self.mic.set_speaking(True, until)  # muted while sound comes out, not while it is made
        self.eyes.feel(self.mood, until)  # held for EYES_MOOD_HOLD_S after the sound ends

    def game_line(self, line: str, keep: bool) -> None:
        """A game's line: kept in the transcript (keep) when it is news, like who won."""
        self.speak("cheerful", line)
        if keep:
            self.record_robot(line)
        self.last_activity = time.monotonic()

    def read_on(self) -> None:
        """The next part of the open story. Not kept in the history: the prompt's story status
        says where it stopped."""
        call = self.latest_call
        if call is not None and resolve_decision(call.get("urgency")) == "wait_nurse":
            self.reader.pause()  # no story while a nurse is needed; the quiet clock runs on
            print("visit: triage asks for a nurse; the story stops")
            return
        sentences = self.reader.next_part()
        for sentence in sentences:
            if self.interrupt.is_set() or self.resident_spoke():
                break  # they spoke as it began, or a job (a bell) waits: read it again later
            self.speak(config.READ_TONE, sentence)
        else:
            self.reader.done_part()
        self.voice.wait()
        self.last_reply = " ".join(sentences)  # its echo in the gap is dropped like a reply's
        self.gates.open_attention(time.monotonic())  # a quiet "stop" in the gap is heard
        self.read_done_at = self.last_activity = time.monotonic()  # a chat never sleeps mid-book

    def say_line(self, line: str) -> None:
        self.speak("calm", line)
        self.record_robot(line)

    def record_robot(self, full: str) -> None:
        self.voice.wait()  # the reply has been heard: attention and the quiet clock start now
        if full == WAIT:
            print("visit: that speech was not for the robot (WAIT); saying nothing")
            return
        if not full:
            return
        self.history.add("robot", full)
        self.backend.add_turn(self.call_id, "robot", full)
        self.last_reply = full
        self.gates.open_attention(time.monotonic())

    def start_triage(self) -> None:
        args = (self.history.transcript(),)
        thread = threading.Thread(target=self.triage, args=args, daemon=True)
        thread.start()
        self.triage_threads.append(thread)

    def triage(self, transcript: list[tuple[str, str]]) -> None:
        triage_fn = self.triage_fn or triage_and_post
        call = triage_fn(self.backend, self.call_id, transcript, self.risk_flags)
        if call is None:
            return  # the backend client printed why
        obslog.event(
            "visit.triaged",
            call_id=self.call_id,
            urgency=call.get("urgency"),
            category=call.get("category"),
            call_status=call.get("status"),
        )
        with self.lock:
            # answers can come back out of order; the backend never lowers urgency, so keep the top
            if urgency_rank(call) >= urgency_rank(self.latest_call):
                self.latest_call = call

    def resident_spoke(self) -> bool:
        """A turn is being heard, transcribed or waits behind the running job (benign read across
        threads)."""
        return self.turn_pending or bool(self.transcribing) or self.submitted > self.started

    def wait_for_triage(self) -> None:
        deadline = time.monotonic() + config.TRIAGE_WAIT_BEFORE_RESOLVE_S
        for thread in self.triage_threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        running = [thread for thread in self.triage_threads if thread.is_alive()]
        if running:
            # the backend ignores a score posted after resolve, so an emergency could be lost
            print(
                f"visit: triage still running after {config.TRIAGE_WAIT_BEFORE_RESOLVE_S:g} s; "
                "waiting for it before resolving"
            )
            for thread in running:
                thread.join()

    def finish(self, quiet: bool) -> None:
        self.wait_for_triage()
        call = self.backend.get_call(self.call_id) or self.latest_call
        status = call.get("status") if call else None
        urgency = call.get("urgency") if call else None
        if status in FINISHED:
            print(f"visit: call already {status}; nothing to resolve")
            self.end()
            return
        if urgency is None and self.triage_threads:
            print("fallback: no triage score reached the backend; posting triage-failed")
            call = self.backend.triage_failed(self.call_id) or call
            urgency = call.get("urgency") if call else None
        decision = resolve_decision(urgency, triaged=bool(self.triage_threads))
        print(f"visit: ending with urgency {urgency} -> {decision}")
        obslog.event("visit.ending", call_id=self.call_id, urgency=urgency, decision=decision)
        if decision == "robot":
            if quiet:
                self.say_line(QUIET_GOODBYE)
            if self.resident_spoke():
                # resolving now would drop that turn untriaged ("bye... wait, my chest hurts")
                print("visit: the resident spoke while the visit was ending; carrying on")
                self.phase = "talk"
                self.last_activity = time.monotonic()
                return
            self.close_call(by_robot=True)
            self.end()
            return
        self.say_line(NURSE_COMING)
        ENTER.clear()
        self.phase = "wait_nurse"
        print("visit: staying until the call shows nurse_acked (or press Enter when they arrive)")
        threading.Thread(target=self.poll_for_nurse, daemon=True).start()

    def poll_for_nurse(self) -> None:
        while self.phase == "wait_nurse":
            call = self.backend.get_call(self.call_id)
            status = call.get("status") if call else None
            if status == "nurse_acked" or status in FINISHED:
                self.nurse_status = status
                return
            time.sleep(config.CALL_POLL_S)

    def resolve_after_nurse(self) -> None:
        if self.nurse_status in FINISHED:
            print(f"visit: call already {self.nurse_status}; nothing to resolve")
        else:
            print(f"visit: {'nurse acknowledged' if self.nurse_status else 'Enter pressed'}")
            self.wait_for_triage()  # the backend ignores a score posted after resolve
            self.close_call(by_robot=False)
        self.end()

    def close_call(self, by_robot: bool) -> bool:
        """Resolve the call and make sure it landed: a failed resolve left the call open for good,
        and the backend keeps a robot with an open call busy, so the robot was lost to dispatch.
        When it never lands, a robot-closed call is escalated (triage-failed) so a nurse sees it."""
        wait = RESOLVE_RETRY_S
        for attempt in range(1, RESOLVE_TRIES + 1):
            if self.backend.resolve(self.call_id, by_robot=by_robot) is not None:
                return True
            latest = self.backend.get_call(self.call_id)  # the answer may only have been lost
            if latest is not None and latest.get("status") in FINISHED:
                return True
            if attempt < RESOLVE_TRIES:
                print(f"visit: resolve not accepted (try {attempt} of {RESOLVE_TRIES}); retrying")
                time.sleep(wait)
                wait *= 2
        print(f"fallback: could not resolve call {self.call_id}; leaving it for a nurse")
        obslog.event("visit.resolve_failed", call_id=self.call_id, by_robot=by_robot)
        if by_robot:
            self.backend.triage_failed(self.call_id)
        return False

    def end(self) -> None:
        """The call is closed: the visit is over and the robot drives home."""
        self.done = True
        obslog.event("visit.end", call_id=self.call_id, room=self.room)
        reason = post_pi("/go_to", {"room": config.HOME_ROOM})
        if reason:
            print(f"fallback: could not send the robot home: {reason}")


class NoBackend:
    """--chat has no call, so nothing is sent: every request gets no answer (None)."""

    def __getattr__(self, name: str) -> Callable[..., None]:
        return lambda *args, **kwargs: None


class ChatVisit(Visit):
    """A chat: a visit with no call behind it, started by "Hey Bellhop" or robot.sh open. It talks
    and plays games, but there is no triage, nurse, resolve or drive home, so it is for trying the
    robot out, never for someone who may need help (asked for a nurse, Claude hears that staff
    could not be reached). It goes back to sleep on goodbye or a quiet spell, but never while a
    game is on screen. A bell rung meanwhile ends it: the robot says sorry and the main loop
    visits that call next (the backend has already sent the robot on its way)."""

    greeting = CHAT_GREETING
    no_mic = CHAT_NO_MIC  # there is no call, so no nurse was asked
    exit_without_mic = False

    def __init__(
        self, *args: Any, bell_check: Callable[[], dict | None] = lambda: None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.bell_check = bell_check  # one look at the backend for a call assigned to this robot
        self.bell: dict | None = None

    def begin(self) -> None:
        super().begin()
        threading.Thread(target=self.watch_bells, daemon=True, name="bells").start()

    def watch_bells(self) -> None:
        while not self.done:
            self.bell = self.bell_check()
            if self.bell is not None:
                return
            time.sleep(config.CALL_POLL_S)

    def check_timers(self, now: float) -> None:
        if self.flux_ok and stt_fallback_due(self.turn_pending, True, now - self.speech_end):
            # Flux heard no turn in it, so it was side-talk or noise: Moonshine would answer it.
            # A late Flux turn is still answered: skip_flux_turn stays off, the face flag is kept
            print(f"visit: no Flux turn {config.FLUX_TURN_LIMIT_S:g} s after speech; not answering")
            self.turn_face_ok = self.take_turn()[1]
        super().check_timers(now)
        if self.bell is not None and self.phase == "talk":
            print(f"visit: call {self.bell.get('id')} rang during the chat; ending it")
            self.phase = "ending"
            self.submit(self.leave_for_bell)

    def greet(self) -> None:
        first = self.call.get("first")
        if not first:  # just "Hey Bellhop", or robot.sh open
            super().greet()
            return
        print(f"visit: answering what came after the name: {first!r}")
        self.handle_turn(first, "wake", ZEROS[:0], 0.0, time.monotonic(), None, True)

    def quiet_limit_s(self) -> float:
        if self.games is not None and self.games.phase is not None:
            return math.inf  # sleeping would close the game under the resident
        return config.CHAT_QUIET_S

    def leave_for_bell(self) -> None:
        self.say_line(BELL_GOODBYE)
        self.end()

    def start_triage(self) -> None:
        pass  # no call to score

    def finish(self, quiet: bool) -> None:
        if quiet:
            self.say_line(CHAT_SLEEP)
        self.end()

    def end(self) -> None:
        self.done = True  # never drives


def next_call(backend: Backend, finished: set[str]) -> dict | None:
    """A call assigned to this robot that it has not visited yet, or None."""
    call = backend.find_assigned_call(config.ROBOT_ID)
    return call if call is not None and call.get("id") not in finished else None


def find_call(backend: Backend, call_id: str | None, finished: set[str]) -> dict | None:
    """The next thing to do: a bell, or else a chat if one was asked for (CHATS)."""
    if call_id:
        call = backend.get_call(call_id)
        if call is None:
            print(f"visit: call {call_id} not found (or the backend is down)")
        return call
    print(f"visit: waiting for a call assigned to {config.ROBOT_ID}")
    while True:
        call = next_call(backend, finished)
        if call is not None:
            return call
        try:
            first = CHATS.get(timeout=config.CALL_POLL_S)
        except queue.Empty:
            continue
        return {"id": CHAT_ID, "room": "", "status": "assigned", "first": first}


def drop_chats() -> None:
    """A chat asked for while busy is dropped, not saved for later."""
    while not CHATS.empty():
        CHATS.get_nowait()


def wait_for_arrival(face: FaceGate, room: str, forced: bool, check_drive: bool = True) -> None:
    seen_at = time.monotonic()
    next_drive_check = 0.0
    at_room = False
    face.reset_facing()  # a timer left from the last visit would start this one at once
    marker_seen = False
    while True:
        now = time.monotonic()
        marker_m = face.marker_distance(room)
        marker_seen = marker_seen or marker_m is not None
        # a face counts only at this room's door, not anyone facing the robot on the way
        facing_s = face.facing_for(now) if marker_seen else 0.0
        if check_drive and now >= next_drive_check:
            # the simulated navigator never sees a marker, so the drive server tells us
            at_room = drive_arrived(fetch_snapshot(), room)
            next_drive_check = now + DRIVE_CHECK_S
        reason = should_start_visit(marker_m, facing_s, now - seen_at, forced, at_room)
        if reason == "timeout":
            print(
                f"fallback: no room marker or facing face after "
                f"{config.VISIT_START_FALLBACK_S:g} s; starting the visit"
            )
            return
        if reason:
            print(f"visit: starting ({reason})")
            return
        time.sleep(FRAME_S)


def attend(
    call: dict,
    room: str,
    face: FaceGate,
    make_visit: Callable[[dict, str], Visit],
    forced: bool,
    release: Callable[[], object],
) -> None:
    """Drive to the room, wait to arrive, run the visit. The LED is kept up while it lasts and
    set idle when it ends; if it ends abnormally (crash, SIGTERM) `release` also stops the robot,
    because a dead backend can no longer send idle."""
    with ledguard.visit_guard(release):
        wait_for_arrival(face, room, forced=forced)
        make_visit(call, room).run()


def start_status(backend: Backend, disabled: bool = False) -> threading.Thread | None:
    """Report battery, room and status to the backend every few seconds, in a daemon thread."""
    if disabled:
        return None
    return StatusReporter(backend).start(threading.Event())


def main() -> None:
    parser = argparse.ArgumentParser(description="Bellhop voice: one visit at a time")
    parser.add_argument("--call", help="visit this call id straight away, then exit")
    parser.add_argument("--no-face", action="store_true", help="accept turns without vision")
    parser.add_argument("--room", help="testing: room for the marker check and the greeting")
    parser.add_argument("--no-status", action="store_true", help="do not report robot status")
    parser.add_argument(
        "--chat",
        action="store_true",
        help='listen for "Hey Bellhop" to chat (no call, triage or driving); bells come first',
    )
    parser.add_argument(
        "--script",
        help="text mode: resident lines from a JSONL file, no mic or audio (see speech.textmode)",
    )
    parser.add_argument(
        "--live-claude",
        action="store_true",
        help="with --script: real Claude replies and triage instead of the offline mocks",
    )
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # logs piped to a file survive a kill
    obslog.configure("speech")

    backend = Backend()
    start_status(backend, disabled=args.no_status)
    if not args.script or args.live_claude:  # mock text runs never spend Apify credit
        feeds.start()
    if args.script:
        from rover.speech import textmode  # text mode only: keeps the audio stack out of its way

        script = textmode.load_script(args.script)
        face = FaceGate(None, disabled=True)

        def make_visit(call: dict, room: str) -> Visit:
            return textmode.TextVisit(call, room, backend, script, live_claude=args.live_claude)

    else:
        brain = Brain()
        threading.Thread(target=brain.warm, daemon=True, name="claude-warm").start()
        voice = Voice()  # loaded once; each visit sets the resident's speech settings
        stt = OfflineSTT()
        listener = VisionListener()
        listener.start()
        face = FaceGate(listener, disabled=args.no_face or args.chat)
        eyes = Eyes().start()  # one face for the whole process: idle between calls
        games = Games(eyes).start_threads()  # on the same screen, while a visit asks for one

        def make_visit(call: dict, room: str) -> Visit:
            if call["id"] == CHAT_ID:
                return ChatVisit(
                    *(call, room, NoBackend(), brain, voice, stt, listener, face),
                    eyes=eyes,
                    games=games,
                    bell_check=lambda: next_call(backend, finished),
                )
            return Visit(
                call, room, backend, brain, voice, stt, listener, face, eyes=eyes, games=games
            )

    threading.Thread(target=read_enter, daemon=True).start()
    # SIGTERM/SIGINT/SIGHUP: LED idle and wheels stopped, then exit 0 (finally blocks still run)
    release = safety.install_motors_off(
        ledguard.release_robot, hard_exit_after_s=config.SHUTDOWN_GRACE_S
    )
    finished: set[str] = set()
    signal.signal(signal.SIGUSR1, lambda signum, frame: CHATS.put(""))  # robot.sh open, running
    while True:
        # asleep: only --chat listens for its name (one mic: closed before a chat or visit opens it)
        wake = WakeListener(CHATS.put).start() if args.chat and not args.call else None
        try:
            call = find_call(backend, args.call, finished)
        finally:
            if wake is not None:
                wake.stop()
        if call is None:
            raise SystemExit(1)
        if call.get("status") in FINISHED:
            print(f"visit: call {call['id']} is already {call['status']}; nothing to visit")
            raise SystemExit(1)
        room = args.room or call.get("room") or ""
        print(f"visit: call {call['id']} for room {room} (status {call.get('status')})")
        obslog.event(
            "visit.assigned", call_id=call["id"], room=room, call_status=call.get("status")
        )
        attend(call, room, face, make_visit, bool(args.call) or call["id"] == CHAT_ID, release)
        finished.add(call["id"])  # never revisit a call the backend failed to move on
        drop_chats()
        if args.call:
            return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nvisit: stopped with Ctrl-C; an open call stays open in the backend")
