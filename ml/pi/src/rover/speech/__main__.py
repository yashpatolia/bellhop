"""Voice process: find the robot's call, start the visit, talk, triage, resolve, send it home.

Run: uv run python -m rover.speech [--call <id>] [--no-face] [--room <room>]
The main thread only moves audio and Flux events; replies, posts and the ending run one job at a
time on a worker, so the mic queue is drained and Flux keeps getting audio while the robot talks.
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from rover import config
from rover.agent.brain import WAIT, Brain
from rover.agent.context import VisitHistory, activity_for, build_system_prompt
from rover.agent.tools import ToolContext, post_pi
from rover.backend import Backend
from rover.speech.flux import FluxStream
from rover.speech.gates import FaceGate, Gates, VisionListener
from rover.speech.mic import Mic
from rover.speech.offline import OfflineSTT
from rover.speech.tts import Voice
from rover.speech.visit import (
    TurnLog,
    backfill,
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
)
from rover.triage.triage import triage_and_post

FRAME_S = 1 / config.CAMERA_FPS  # check the start conditions once per vision frame
DRAFT_POLL_S = 0.05  # how often a confirmed draft is checked for its next sentence
ZEROS = np.zeros(config.BLOCK_SAMPLES, dtype=np.int16)
QUIET_GOODBYE = "I'll let you rest now. Press your bell any time you need me."
NURSE_COMING = "A nurse is on the way, I'll stay with you."
NO_MIC = "Sorry, I can't hear right now, so I've asked a nurse to come."
FINISHED = {"resolved", "closed"}
ENTER = threading.Event()  # Enter on stdin: the nurse has arrived


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
    ) -> None:
        self.call = call
        self.call_id: str = call["id"]
        self.room = room
        self.backend, self.brain, self.voice, self.stt = backend, brain, voice, stt
        self.listener, self.face = listener, face
        self.tool_ctx = ToolContext(backend, self.call_id)
        self.gates = Gates()
        self.mic = Mic()
        self.flux: FluxStream | None = None
        self.flux_ok = False
        self.events: queue.Queue[tuple[str, str, float]] = queue.Queue()
        self.history = VisitHistory()
        self.log = TurnLog()
        self.resident: dict | None = None
        self.preferences: dict | None = None
        self.memories: list[dict] = []
        self.risk_flags: list[str] = []
        # one job at a time (greeting, each turn, the ending) keeps the history in order
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.job: Future | None = None
        self.submitted = 0  # jobs handed to the worker; more than started = a turn is waiting
        self.started = 0
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
        # written by the worker, read by the main thread
        self.last_reply = ""
        self.last_activity = time.monotonic()
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
        self.voice.settings = self.backend.speech_settings(resident_id)
        self.risk_flags = list((self.resident or {}).get("risk_flags") or [])

    def run(self) -> None:
        if not self.backend.in_visit(self.call_id):
            print("visit: in-visit was not accepted; talking anyway")
        self.load_context()
        try:
            self.mic.start()
        except Exception:
            print("fallback: no microphone; posting triage-failed so a nurse comes")
            self.say_line(NO_MIC)
            self.backend.triage_failed(self.call_id)
            raise SystemExit(1) from None
        name = (self.resident or {}).get("name", "")
        self.flux = FluxStream([config.ROBOT_NAME, name], self.on_flux)
        self.flux_ok = self.flux.start()
        if not self.flux_ok:
            print("fallback: no Flux this visit; every turn goes to Moonshine")
        self.submit(self.greet)
        try:
            while not (self.done and self.idle()):
                block = self.mic.read()
                if block is not None:
                    self.hear(block, time.monotonic())
                self.handle_events()
                self.check_timers(time.monotonic())
        finally:
            self.phase = "over"
            self.cancel_draft()
            self.flux.close()
            self.mic.stop()
            self.pool.shutdown(wait=False, cancel_futures=True)
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
        stt_s = at - speech_end
        self.submit(self.handle_turn, text, "flux", audio, stt_s, speech_end, draft, face_ok)

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
            self.submit(self.offline_turn, *self.take_turn())
        quiet_s = now - self.last_activity
        if self.phase == "talk" and self.idle() and not self.turn_pending:
            if quiet_s >= config.VISIT_QUIET_END_S:
                print(f"visit: {config.VISIT_QUIET_END_S:g} s without a turn; ending the visit")
                self.phase = "ending"
                self.submit(self.finish, True)
        if self.phase == "wait_nurse" and (self.nurse_status or ENTER.is_set()):
            self.phase = "resolving"
            self.submit(self.resolve_after_nurse)

    def take_turn(self) -> tuple[np.ndarray, bool, float]:
        audio = np.concatenate(self.turn_audio) if self.turn_audio else ZEROS[:0]
        face_ok = self.turn_face_ok
        self.turn_audio, self.turn_face_ok, self.turn_pending = [], False, False
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
        return self.job is None or self.job.done()

    def submit(self, job, *args) -> None:
        self.submitted += 1
        self.job = self.pool.submit(self.guarded, job, *args)

    def guarded(self, job, *args) -> None:
        self.started += 1
        try:
            job(*args)
        except Exception as exc:
            print(f"visit: {job.__name__} failed: {exc!r}")
            traceback.print_exc()

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
        )

    def greet(self) -> None:
        hello = f"(The robot has just arrived in room {self.room}. Greet the resident.)"
        messages = [{"role": "user", "content": hello}]  # never posted as a turn
        full, _ = self.brain.reply(self.system_prompt(), messages, self.speak, self.tool_ctx)
        self.record_robot(full)
        self.last_activity = time.monotonic()

    def offline_turn(self, audio: np.ndarray, face_ok: bool, speech_end: float) -> None:
        text = self.stt.transcribe(audio)
        reason = drop_reason(text, self.last_reply)
        if reason:
            print(f"visit: dropped Moonshine turn {text!r}: {reason}")
            return
        stt_s = time.monotonic() - speech_end
        self.handle_turn(text, "moonshine", audio, stt_s, speech_end, None, face_ok)

    def handle_turn(
        self,
        text: str,
        source: str,
        audio: np.ndarray,
        stt_s: float,
        speech_end: float,
        draft: Draft | None,
        face_ok: bool,
    ) -> None:
        if self.done:
            print(f"visit: dropped turn {text!r}: the call is already resolved")
            return
        print(f"resident: {text}  ({source})")
        self.history.add("resident", text)
        self.backend.add_turn(self.call_id, "resident", text)  # before triage reads the transcript
        self.start_triage()
        if not face_ok:
            # posted and triaged anyway, so a call for help from the floor is never lost
            print("visit: no one was facing the robot during that turn; triaged it, no reply")
            if draft is not None:
                draft.cancel.set()
            self.last_activity = time.monotonic()
            return
        self.first_text_at = self.first_sound_at = None
        self.record_robot(self.reply_to(text, draft))

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
            self.system_prompt(), self.history.messages(), speak_new, self.tool_ctx
        )
        return full

    def speak(self, tone: str, sentence: str) -> None:
        if self.first_text_at is None:
            self.first_text_at = time.monotonic()
        self.mic.set_speaking(True)
        try:
            self.voice.say(sentence, tone)
        finally:
            self.mic.set_speaking(False)
        if self.first_sound_at is None:
            # Voice.say blocks through synthesis and playback: this is the first sentence heard
            self.first_sound_at = time.monotonic()

    def say_line(self, line: str) -> None:
        self.speak("calm", line)
        self.record_robot(line)

    def record_robot(self, full: str) -> None:
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
        call = triage_and_post(self.backend, self.call_id, transcript, self.risk_flags)
        if call is None:
            return  # the backend client printed why
        with self.lock:
            # answers can come back out of order; the backend never lowers urgency, so keep the top
            if urgency_rank(call) >= urgency_rank(self.latest_call):
                self.latest_call = call

    def resident_spoke(self) -> bool:
        """A turn is being heard or waits behind the running job (benign read across threads)."""
        return self.turn_pending or self.submitted > self.started

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
        if decision == "robot":
            if quiet:
                self.say_line(QUIET_GOODBYE)
            if self.resident_spoke():
                # resolving now would drop that turn untriaged ("bye... wait, my chest hurts")
                print("visit: the resident spoke while the visit was ending; carrying on")
                self.phase = "talk"
                self.last_activity = time.monotonic()
                return
            self.backend.resolve(self.call_id, by_robot=True)
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
            self.backend.resolve(self.call_id, by_robot=False)
        self.end()

    def end(self) -> None:
        """The call is closed: the visit is over and the robot drives home."""
        self.done = True
        reason = post_pi("/go_to", {"room": config.HOME_ROOM})
        if reason:
            print(f"fallback: could not send the robot home: {reason}")


def find_call(backend: Backend, call_id: str | None, finished: set[str]) -> dict | None:
    if call_id:
        call = backend.get_call(call_id)
        if call is None:
            print(f"visit: call {call_id} not found (or the backend is down)")
        return call
    print(f"visit: waiting for a call assigned to {config.ROBOT_ID}")
    while True:
        call = backend.find_assigned_call(config.ROBOT_ID)
        if call is not None and call.get("id") not in finished:
            return call
        time.sleep(config.CALL_POLL_S)


def wait_for_arrival(face: FaceGate, room: str, forced: bool) -> None:
    seen_at = time.monotonic()
    face.reset_facing()  # a timer left from the last visit would start this one at once
    marker_seen = False
    while True:
        now = time.monotonic()
        marker_m = face.marker_distance(room)
        marker_seen = marker_seen or marker_m is not None
        # a face counts only at this room's door, not anyone facing the robot on the way
        facing_s = face.facing_for(now) if marker_seen else 0.0
        reason = should_start_visit(marker_m, facing_s, now - seen_at, forced)
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Bellhop voice: one visit at a time")
    parser.add_argument("--call", help="visit this call id straight away, then exit")
    parser.add_argument("--no-face", action="store_true", help="accept turns without vision")
    parser.add_argument("--room", help="testing: room for the marker check and the greeting")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # logs piped to a file survive a kill

    backend = Backend()
    brain = Brain()
    voice = Voice()  # loaded once; each visit sets the resident's speech settings
    stt = OfflineSTT()
    listener = VisionListener()
    listener.start()
    face = FaceGate(listener, disabled=args.no_face)
    threading.Thread(target=read_enter, daemon=True).start()
    finished: set[str] = set()
    while True:
        call = find_call(backend, args.call, finished)
        if call is None:
            raise SystemExit(1)
        if call.get("status") in FINISHED:
            print(f"visit: call {call['id']} is already {call['status']}; nothing to visit")
            raise SystemExit(1)
        room = args.room or call.get("room") or ""
        print(f"visit: call {call['id']} for room {room} (status {call.get('status')})")
        wait_for_arrival(face, room, forced=bool(args.call))
        Visit(call, room, backend, brain, voice, stt, listener, face).run()
        finished.add(call["id"])  # never revisit a call the backend failed to move on
        if args.call:
            return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nvisit: stopped with Ctrl-C; an open call stays open in the backend")
