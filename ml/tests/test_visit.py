import json
import math
import threading
import time
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from rover import config
from rover.agent.brain import WAIT
from rover.agent.context import VisitHistory
from rover.speech import __main__ as voice_main
from rover.speech.gates import FaceGate
from rover.speech.visit import (
    TurnLog,
    backfill,
    drive_arrived,
    drop_reason,
    is_echo,
    is_goodbye,
    messages_with,
    pair_blocks,
    resolve_decision,
    scene_note,
    should_start_visit,
    stt_fallback_due,
    urgency_rank,
    wake_text,
)


def block(value: int) -> np.ndarray:
    return np.full(config.BLOCK_SAMPLES, value, dtype=np.int16)


@pytest.mark.parametrize(
    "text",
    ["Okay, bye!", "Goodbye.", "good bye then", "See you later", "Not now, thanks", "Bye-bye"],
)
def test_goodbye_phrases(text):
    assert is_goodbye(text)


@pytest.mark.parametrize(
    "text", ["Can you see your glasses?", "I'm fine", "Nobody came", "I can't see you", ""]
)
def test_not_goodbye(text):
    assert not is_goodbye(text)


def test_echo_whole_or_part_of_last_reply():
    reply = "Lovely to see you! Would you like a cup of tea?"
    assert is_echo("would you like a cup of tea", reply)
    assert is_echo("Lovely to see you, would you like a cup of tea?", reply)
    assert not is_echo("I would like a cup of coffee", reply)


def test_short_answers_are_never_echo():
    assert not is_echo("Tea.", "Would you like water or tea?")
    assert not is_echo("Yes please", "Shall I call a nurse? Yes please or no?")


def test_drop_reason():
    assert drop_reason("  ", "") == "empty transcript"
    assert "echo" in drop_reason("would you like some tea", "Would you like some tea?")
    assert drop_reason("I need help", "Hello!") is None


def test_should_start_visit():
    assert should_start_visit(None, 0.0, 0.0, forced=True)
    assert "marker" in should_start_visit(config.ARRIVE_DISTANCE_M, 0.0, 0.0, forced=False)
    assert should_start_visit(config.ARRIVE_DISTANCE_M + 0.5, 0.0, 0.0, forced=False) is None
    assert should_start_visit(math.nan, 0.0, 0.0, forced=False) is None
    assert "face" in should_start_visit(None, config.FACE_START_S, 0.0, forced=False)
    assert should_start_visit(None, math.nan, 0.0, forced=False) is None
    assert should_start_visit(None, 0.0, config.VISIT_START_FALLBACK_S, False) == "timeout"


@pytest.mark.parametrize("urgency", [None, 1, 2])
def test_low_urgency_resolves_by_robot(urgency):
    assert resolve_decision(urgency) == "robot"


@pytest.mark.parametrize("urgency", [3, 4, "3", True, 2.5])
def test_high_or_unreadable_urgency_waits_for_nurse(urgency):
    assert resolve_decision(urgency) == "wait_nurse"


def test_no_urgency_after_triage_waits_for_nurse():
    assert resolve_decision(None, triaged=True) == "wait_nurse"
    assert resolve_decision(1, triaged=True) == "robot"


def test_urgency_rank():
    assert urgency_rank(None) == 0
    assert urgency_rank({"urgency": None}) == 0
    assert urgency_rank({"urgency": True}) == 0
    assert urgency_rank({"urgency": 4}) == 4


def test_stt_fallback_due():
    assert not stt_fallback_due(False, False, 100.0)
    assert not stt_fallback_due(True, True, config.FLUX_TURN_LIMIT_S - 0.1)
    assert stt_fallback_due(True, True, config.FLUX_TURN_LIMIT_S)
    assert stt_fallback_due(True, False, config.EOT_TIMEOUT_MS / 1000)


def test_backfill_sends_only_the_zeroed_blocks():
    preroll = [block(i) for i in range(16)]
    assert [b[0] for b in backfill(preroll, 0)] == [15]
    assert [b[0] for b in backfill(preroll, 3)] == [12, 13, 14, 15]
    assert len(backfill(preroll, 500)) == 16
    assert backfill([], 5) == []


def test_pair_blocks():
    pairs, rest = pair_blocks([block(1), block(2), block(3)])
    assert len(pairs) == 1 and len(pairs[0]) == 2 * config.BLOCK_SAMPLES * 2
    assert len(rest) == 1 and rest[0][0] == 3
    pairs, rest = pair_blocks(rest + [block(4)])
    assert len(pairs) == 1 and rest == []


def test_messages_with_leaves_history_alone():
    history = VisitHistory()
    history.add("robot", "Hello!")
    messages = messages_with(history, "Hi there")
    assert messages[-1] == {"role": "user", "content": "Hi there"}
    assert history.transcript() == [("robot", "Hello!")]


def test_scene_note():
    assert scene_note(None) == ""
    assert scene_note({"person": None, "face": None}) == "No one is in view."
    assert "facing you" in scene_note({"face": {"facing": True}})
    assert "not facing" in scene_note({"person": {"id": 1}, "face": None})


def test_turn_log(tmp_path):
    log = TurnLog(tmp_path)
    log.write("call_1", "hello", "flux", block(7), 0.4, 1.2, None)
    log.write("call_1", "again", "moonshine", block(8), 3.0, None, None)
    day = next(tmp_path.iterdir())
    with wave.open(str(day / "2.wav")) as wav:
        assert wav.getframerate() == config.SAMPLE_RATE and wav.getsampwidth() == 2
        assert wav.getnframes() == config.BLOCK_SAMPLES
    lines = [json.loads(line) for line in (day / "turns.jsonl").read_text().splitlines()]
    assert [line["source"] for line in lines] == ["flux", "moonshine"]
    assert lines[0]["stt_s"] == 0.4 and lines[0]["first_sound_s"] is None


# ---- the visit's turn and ending flow, with fakes


class FakeBackend:
    def __init__(self, urgency=None, status="in_visit"):
        self.log = []
        self.call = {"id": "c1", "room": "12", "urgency": urgency, "status": status}

    def add_turn(self, call_id, speaker, text):
        self.log.append(("turn", speaker, text))
        return self.call

    def get_call(self, call_id):
        return dict(self.call)

    def resolve(self, call_id, by_robot):
        self.log.append(("resolve", by_robot))
        return self.call

    def triage_failed(self, call_id):
        self.log.append(("triage_failed",))
        self.call.update(urgency=3, status="escalated")
        return dict(self.call)


class FakeBrain:
    def __init__(self, sentences=("Oh no.", "Help is coming.")):
        self.sentences = sentences
        self.calls = 0

    def reply(self, system, messages, on_sentence, tool_ctx, allow_tools=True, cancel=None):
        self.calls += 1
        for sentence in self.sentences:
            on_sentence("calm", sentence)
        return " ".join(self.sentences), False


class FakeVoice:
    def __init__(self):
        self.said = []
        self.settings = None
        self.waits = 0
        self.on_play = lambda until: None

    def say(self, sentence, tone):
        self.said.append(sentence)
        self.on_play(time.monotonic())  # as the real voice does when a sentence starts

    def wait(self):
        self.waits += 1


class FakeListener:
    def latest(self):
        return None

    def age(self, now):
        return math.inf


def make_visit(tmp_path, monkeypatch, backend, brain):
    def fake_triage(backend_, call_id, transcript, risk_flags):
        backend_.log.append(("triage", transcript[-1][1]))
        return backend_.call

    monkeypatch.setattr(voice_main, "triage_and_post", fake_triage)
    monkeypatch.setattr(voice_main, "post_pi", lambda path, body: backend.log.append((path, body)))
    visit = voice_main.Visit(
        backend.call,
        "12",
        backend,
        brain,
        FakeVoice(),
        None,
        FakeListener(),
        FaceGate(None, disabled=True),
    )
    visit.log = TurnLog(tmp_path)
    return visit


def test_turn_posts_resident_before_triage_then_robot(tmp_path, monkeypatch):
    backend = FakeBackend()
    visit = make_visit(tmp_path, monkeypatch, backend, FakeBrain())
    visit.handle_turn("I've fallen", "flux", block(1), 0.5, time.monotonic(), None, True)
    for thread in visit.triage_threads:
        thread.join()
    assert backend.log[0] == ("turn", "resident", "I've fallen")
    assert ("turn", "robot", "Oh no. Help is coming.") in backend.log
    assert ("triage", "I've fallen") in backend.log
    assert visit.voice.said == ["Oh no.", "Help is coming."]
    assert visit.last_reply == "Oh no. Help is coming."
    assert not visit.mic.muted(time.monotonic() + config.ECHO_TAIL_S)


def test_matching_draft_is_spoken_without_a_new_reply(tmp_path, monkeypatch):
    brain = FakeBrain()
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), brain)
    draft = voice_main.Draft("Can I have some water", sentences=[("cheerful", "Of course!")])
    draft.text = "Of course!"
    draft.thread = threading.Thread(target=lambda: None)
    draft.thread.start()
    assert visit.reply_to("can I have some water?", draft) == "Of course!"
    assert brain.calls == 0 and visit.voice.said == ["Of course!"]

    other = voice_main.Draft("Can I have", sentences=[("cheerful", "Sure.")])
    other.thread = threading.Thread(target=lambda: None)
    other.thread.start()
    visit.reply_to("Can I have a nurse", other)
    assert other.cancel.is_set() and brain.calls == 1


def test_wait_reply_is_not_posted(tmp_path, monkeypatch):
    backend = FakeBackend()
    visit = make_visit(tmp_path, monkeypatch, backend, FakeBrain())
    visit.record_robot(WAIT)
    assert backend.log == [] and visit.history.transcript() == []


def test_goodbye_with_low_urgency_resolves_by_robot(tmp_path, monkeypatch):
    backend = FakeBackend(urgency=1)
    visit = make_visit(tmp_path, monkeypatch, backend, FakeBrain(("Bye now!",)))
    visit.handle_turn("Okay, bye", "flux", block(1), 0.5, time.monotonic(), None, True)
    assert backend.log[-2:] == [("resolve", True), ("/go_to", {"room": config.HOME_ROOM})]
    assert visit.done


def test_high_urgency_waits_for_the_nurse_then_resolves(tmp_path, monkeypatch):
    backend = FakeBackend(urgency=4, status="escalated")
    visit = make_visit(tmp_path, monkeypatch, backend, FakeBrain())
    visit.finish(quiet=True)
    assert visit.phase == "wait_nurse" and not visit.done
    assert voice_main.NURSE_COMING in visit.voice.said
    backend.call["status"] = "nurse_acked"
    deadline = time.monotonic() + 5
    while visit.nurse_status is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert visit.nurse_status == "nurse_acked"
    visit.resolve_after_nurse()
    go_home = ("/go_to", {"room": config.HOME_ROOM})
    assert backend.log[-2:] == [("resolve", False), go_home] and visit.done


def test_failed_trip_home_prints_a_fallback(tmp_path, monkeypatch, capsys):
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(urgency=1), FakeBrain())
    monkeypatch.setattr(voice_main, "post_pi", lambda path, body: "ConnectError")
    visit.finish(quiet=False)
    assert visit.done
    assert "fallback: could not send the robot home: ConnectError" in capsys.readouterr().out


def test_unfaced_turn_is_posted_and_triaged_but_not_answered(tmp_path, monkeypatch):
    backend = FakeBackend()
    brain = FakeBrain()
    visit = make_visit(tmp_path, monkeypatch, backend, brain)
    visit.handle_turn("Help, I've fallen", "flux", block(1), 0.5, time.monotonic(), None, False)
    for thread in visit.triage_threads:
        thread.join()
    assert ("turn", "resident", "Help, I've fallen") in backend.log
    assert ("triage", "Help, I've fallen") in backend.log
    assert brain.calls == 0 and visit.voice.said == []


def test_turn_waiting_during_the_ending_stops_the_resolve(tmp_path, monkeypatch):
    backend = FakeBackend(urgency=1)
    visit = make_visit(tmp_path, monkeypatch, backend, FakeBrain(("Bye now!",)))
    visit.submitted = visit.started + 1  # "wait, my chest hurts" is queued behind this job
    visit.handle_turn("Okay, bye", "flux", block(1), 0.5, time.monotonic(), None, True)
    go_home = ("/go_to", {"room": config.HOME_ROOM})
    assert ("resolve", True) not in backend.log and go_home not in backend.log
    assert visit.phase == "talk" and not visit.done


def test_triage_that_never_reached_the_backend_posts_triage_failed(tmp_path, monkeypatch):
    backend = FakeBackend(urgency=None)
    visit = make_visit(tmp_path, monkeypatch, backend, FakeBrain())
    visit.handle_turn("I feel strange", "flux", block(1), 0.5, time.monotonic(), None, True)
    visit.finish(quiet=True)
    visit.phase = "over"  # stops the nurse poller
    assert ("triage_failed",) in backend.log and ("resolve", True) not in backend.log
    assert voice_main.NURSE_COMING in visit.voice.said


def test_draft_sentences_are_spoken_as_they_arrive(tmp_path, monkeypatch):
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), FakeBrain())
    first_spoken = threading.Event()

    def say(sentence, tone):
        visit.voice.said.append(sentence)
        first_spoken.set()

    visit.voice.say = say
    draft = voice_main.Draft("How are you")

    def write():
        draft.sentences.append(("cheerful", "Very well."))
        live = first_spoken.wait(2)  # joining the whole draft first would never set this
        draft.sentences.append(("cheerful", "Live." if live else "Late."))
        draft.text = " ".join(sentence for _, sentence in draft.sentences)

    draft.thread = threading.Thread(target=write)
    draft.thread.start()
    assert visit.reply_to("How are you?", draft) == "Very well. Live."
    assert visit.voice.said == ["Very well.", "Live."]


def test_draft_that_wanted_a_tool_is_not_repeated(tmp_path, monkeypatch):
    brain = FakeBrain(("Oh no.", "Help is coming."))
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), brain)
    draft = voice_main.Draft("Get me a nurse", sentences=[("calm", "Oh no.")], wanted_tool=True)
    draft.thread = threading.Thread(target=lambda: None)
    draft.thread.start()
    visit.reply_to("get me a nurse", draft)
    assert brain.calls == 1 and visit.voice.said == ["Oh no.", "Help is coming."]


class FacingListener:
    def __init__(self, markers):
        self.message = {"face": {"facing": True}, "markers": markers}

    def latest(self):
        return self.message

    def age(self, now):
        return 0.0


def test_arrival_ignores_a_stale_facing_timer_and_faces_before_the_door(monkeypatch, capsys):
    monkeypatch.setattr(voice_main, "fetch_snapshot", lambda: None)
    monkeypatch.setattr(config, "VISIT_START_FALLBACK_S", 0.3)
    face = FaceGate(FacingListener([]))
    face._facing_since = time.monotonic() - 100  # left over from the last visit
    voice_main.wait_for_arrival(face, "12", forced=False)
    assert "fallback: no room marker" in capsys.readouterr().out


def test_arrival_counts_facing_once_the_door_marker_is_seen(monkeypatch, capsys):
    monkeypatch.setattr(voice_main, "fetch_snapshot", lambda: None)
    monkeypatch.setattr(config, "FACE_START_S", 0.1)
    face = FaceGate(FacingListener([{"room": "12", "distance_m": 3.0}]))
    voice_main.wait_for_arrival(face, "12", forced=False)
    assert "face facing" in capsys.readouterr().out


# ---- arrival from the drive server (the Sim navigator never sees a marker)


def test_drive_arrival_needs_the_room_and_a_stopped_robot():
    idle_at = {"room": "12", "target": None, "mode": "idle", "moving": False}
    assert drive_arrived(idle_at, "12")
    assert not drive_arrived(idle_at, "14")
    assert not drive_arrived({**idle_at, "mode": "going", "moving": True, "room": "lobby"}, "12")
    assert not drive_arrived({**idle_at, "moving": True}, "12")
    assert not drive_arrived(None, "12")
    assert not drive_arrived({"room": "12"}, "12")  # no mode: not trusted
    assert not drive_arrived(idle_at, "")


def test_visit_starts_when_the_drive_reports_arrival():
    reason = should_start_visit(None, 0.0, 0.0, forced=False, drive_arrived=True)
    assert reason and "drive" in reason
    assert should_start_visit(None, 0.0, 0.0, forced=False) is None


def test_wait_for_arrival_returns_when_the_drive_server_says_arrived(monkeypatch, capsys):
    monkeypatch.setattr(config, "VISIT_START_FALLBACK_S", 30.0)
    snapshots = iter(
        [
            {"room": "lobby", "mode": "going", "moving": True},
            {"room": "12", "mode": "idle", "moving": False},
        ]
    )
    monkeypatch.setattr(voice_main, "fetch_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(voice_main, "DRIVE_CHECK_S", 0.0)
    started = time.monotonic()
    voice_main.wait_for_arrival(FaceGate(None, disabled=True), "12", forced=False)
    assert time.monotonic() - started < 5
    assert "the drive server reports arrival" in capsys.readouterr().out


# ---- a resolve the backend did not accept must not leave the call open


class FlakyResolve(FakeBackend):
    """resolve() answers None (the client's way of saying it failed) `failures` times."""

    def __init__(self, failures, status_after_failure="in_visit", **kwargs):
        super().__init__(**kwargs)
        self.failures = failures
        self.status_after_failure = status_after_failure

    def resolve(self, call_id, by_robot):
        self.log.append(("resolve", by_robot))
        if self.failures > 0:
            self.failures -= 1
            self.call["status"] = self.status_after_failure
            return None
        self.call["status"] = "resolved"
        return dict(self.call)


@pytest.fixture
def quick_resolve(monkeypatch):
    monkeypatch.setattr(voice_main, "RESOLVE_RETRY_S", 0.0)


def test_failed_resolve_is_retried_until_it_lands(tmp_path, monkeypatch, quick_resolve):
    backend = FlakyResolve(2, urgency=1)
    visit = make_visit(tmp_path, monkeypatch, backend, FakeBrain())
    visit.finish(quiet=False)
    assert [e for e in backend.log if e[0] == "resolve"] == [("resolve", True)] * 3
    assert backend.call["status"] == "resolved"
    assert backend.log[-1] == ("/go_to", {"room": config.HOME_ROOM}) and visit.done


def test_lost_resolve_answer_is_not_retried_when_the_call_is_resolved(
    tmp_path, monkeypatch, quick_resolve
):
    backend = FlakyResolve(1, status_after_failure="resolved", urgency=1)
    visit = make_visit(tmp_path, monkeypatch, backend, FakeBrain())
    visit.finish(quiet=False)
    assert [e for e in backend.log if e[0] == "resolve"] == [("resolve", True)]
    assert visit.done


def test_resolve_that_never_lands_asks_for_a_nurse(tmp_path, monkeypatch, quick_resolve, capsys):
    backend = FlakyResolve(99, urgency=1)
    visit = make_visit(tmp_path, monkeypatch, backend, FakeBrain())
    visit.finish(quiet=False)
    assert len([e for e in backend.log if e[0] == "resolve"]) == voice_main.RESOLVE_TRIES
    assert ("triage_failed",) in backend.log  # the backend then escalates the open call
    assert "fallback: could not resolve" in capsys.readouterr().out
    assert visit.done


def test_nurse_resolve_is_retried_too(tmp_path, monkeypatch, quick_resolve):
    backend = FlakyResolve(1, urgency=4, status="nurse_acked")
    visit = make_visit(tmp_path, monkeypatch, backend, FakeBrain())
    visit.nurse_status = "nurse_acked"
    visit.resolve_after_nurse()
    assert [e for e in backend.log if e[0] == "resolve"] == [("resolve", False)] * 2
    assert ("triage_failed",) not in backend.log


class RecordingMic:
    def __init__(self, fail_start=False):
        self.events = []
        self.fail_start = fail_start

    def start(self):
        if self.fail_start:
            raise OSError("no mic")
        self.events.append("start")

    def stop(self):
        self.events.append("stop")

    def set_speaking(self, speaking, until=0.0):
        pass


def test_mic_is_closed_when_the_visit_setup_fails_after_it_opened(tmp_path, monkeypatch):
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), FakeBrain())
    visit.mic = RecordingMic()
    visit.begin = lambda: None

    def boom(*args, **kwargs):
        raise RuntimeError("flux setup")

    monkeypatch.setattr(voice_main, "FluxStream", boom)
    with pytest.raises(RuntimeError):
        visit.run()
    assert visit.mic.events == ["start", "stop"]


def test_mic_is_closed_when_the_loop_is_interrupted(tmp_path, monkeypatch):
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), FakeBrain())
    visit.mic = RecordingMic()
    visit.begin = lambda: None

    class Flux:
        def __init__(self, *a):
            self.closed = False

        def start(self):
            return True

        def close(self):
            self.closed = True

    monkeypatch.setattr(voice_main, "FluxStream", Flux)
    visit.submit = lambda *a, **k: None
    visit.mic.read = lambda: (_ for _ in ()).throw(SystemExit(0))  # SIGTERM lands in the loop
    with pytest.raises(SystemExit):
        visit.run()
    assert visit.mic.events == ["start", "stop"]
    assert visit.flux.closed


class FakePi:
    def __init__(self):
        self.posts = []

    def post(self, path, body):
        self.posts.append((path, body))

    def fetch(self):
        return {"led": "idle"}


def attend_with(monkeypatch, make_visit, released):
    from rover.speech import ledguard

    pi = FakePi()
    monkeypatch.setattr(ledguard, "_post", pi.post)
    monkeypatch.setattr(ledguard, "_fetch", pi.fetch)
    monkeypatch.setattr(voice_main, "wait_for_arrival", lambda *a, **k: None)
    return pi, lambda: voice_main.attend({"id": "c1"}, "12", None, make_visit, False, released)


def test_attend_normal_visit_end_sets_led_idle_without_stopping(monkeypatch):
    ran = []

    class V:
        def run(self):
            ran.append(1)

    released = []
    pi, go = attend_with(monkeypatch, lambda call, room: V(), lambda: released.append(1))
    go()
    assert ran == [1] and released == []
    assert pi.posts == [("/led", {"state": "idle"})]


def test_attend_crash_during_the_visit_releases_the_robot(monkeypatch):
    class V:
        def run(self):
            raise RuntimeError("backend died")

    released = []
    pi, go = attend_with(monkeypatch, lambda call, room: V(), lambda: released.append(1))
    with pytest.raises(RuntimeError):
        go()
    assert released == [1]


def test_attend_sigterm_while_waiting_for_arrival_releases_the_robot(monkeypatch):
    released = []
    pi, go = attend_with(monkeypatch, lambda call, room: None, lambda: released.append(1))

    def term(*a, **k):
        raise SystemExit(0)

    monkeypatch.setattr(voice_main, "wait_for_arrival", term)
    with pytest.raises(SystemExit):
        go()
    assert released == [1]


def test_the_reply_tone_shows_on_the_eyes_and_always_calm_wins(tmp_path, monkeypatch):
    backend = FakeBackend()
    visit = make_visit(tmp_path, monkeypatch, backend, FakeBrain())
    visit.speak("excited", "Hooray!")
    assert visit.eyes.expression(time.monotonic()) == "excited"
    visit.voice.settings = {"tone": "calm"}
    visit.speak("excited", "Hooray!")
    assert visit.eyes.expression(time.monotonic()) == "calm"
    visit.handle_turn("hello", "flux", block(1), 0.5, time.monotonic(), None, True)
    assert visit.eyes.base == "listening"  # thinking only while the reply is being written


class RecordingGames:
    def __init__(self):
        self.calls = []

    def attach(self, post):
        self.calls.append(("attach", post))

    def stop(self):
        self.calls.append(("stop",))
        return "closed"

    def status(self):
        return "Bingo: 2 numbers called."


def test_game_events_keep_the_visit_going_and_news_reaches_the_transcript(tmp_path, monkeypatch):
    backend = FakeBackend()
    visit = make_visit(tmp_path, monkeypatch, backend, FakeBrain())
    visit.events.put(("GameTouch", "", 123.0))
    visit.events.put(("GameSay", "N 34", 123.0))
    visit.handle_events()
    visit.job.result(timeout=5)
    visit.events.put(("GameNote", "Bingo! You got a line, well done!", 124.0))
    visit.handle_events()
    visit.job.result(timeout=5)
    assert visit.voice.said == ["N 34", "Bingo! You got a line, well done!"]
    robot_turns = [entry for entry in backend.log if entry[:2] == ("turn", "robot")]
    assert robot_turns == [("turn", "robot", "Bingo! You got a line, well done!")]  # not "N 34"
    assert visit.last_activity > 123.0


def test_the_game_shows_in_the_prompt_and_closes_when_the_visit_ends(tmp_path, monkeypatch):
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), FakeBrain())
    visit.games = games = RecordingGames()
    assert (
        "## Right now: a game is on your screen\nBingo: 2 numbers called." in visit.system_prompt()
    )
    visit.mic = RecordingMic()
    visit.begin = lambda: None

    def boom(*args, **kwargs):
        raise RuntimeError("flux setup")

    monkeypatch.setattr(voice_main, "FluxStream", boom)
    with pytest.raises(RuntimeError):
        visit.run()
    assert games.calls == [("stop",), ("attach", None)]


def make_chat(tmp_path, monkeypatch, sent):
    monkeypatch.setattr(voice_main, "post_pi", lambda path, body: sent.append(path))
    monkeypatch.setattr(voice_main, "triage_and_post", lambda *args: sent.append("triage"))
    call = {"id": "chat", "room": "", "status": "assigned"}
    visit = voice_main.ChatVisit(
        call,
        "",
        voice_main.NoBackend(),
        FakeBrain(("Hello!",)),
        FakeVoice(),
        None,
        FakeListener(),
        FaceGate(None, disabled=True),
    )
    visit.log = TurnLog(tmp_path)
    return visit


def test_a_chat_talks_and_ends_on_goodbye_without_triage_or_driving(tmp_path, monkeypatch):
    sent = []
    visit = make_chat(tmp_path, monkeypatch, sent)
    assert "called you over" in visit.greeting
    visit.handle_turn("Hi there", "flux", block(1), 0.5, time.monotonic(), None, True)
    assert visit.voice.said == ["Hello!"] and not visit.done
    visit.handle_turn("Okay, bye", "flux", block(1), 0.5, time.monotonic(), None, True)
    assert visit.done and sent == []  # no triage, no /go_to


def test_a_quiet_chat_goes_back_to_sleep(tmp_path, monkeypatch):
    sent = []
    visit = make_chat(tmp_path, monkeypatch, sent)
    assert visit.quiet_limit_s() == config.CHAT_QUIET_S
    visit.finish(quiet=True)
    assert visit.voice.said == [voice_main.CHAT_SLEEP] and visit.done and sent == []


def test_a_chat_never_sleeps_while_a_game_is_open(tmp_path, monkeypatch):
    visit = make_chat(tmp_path, monkeypatch, [])
    visit.games = RecordingGames()
    visit.games.phase = "play"
    visit.last_activity = time.monotonic() - 10 * config.CHAT_QUIET_S
    visit.check_timers(time.monotonic())
    assert visit.phase == "talk" and visit.job is None and visit.games.calls == []


def test_the_words_after_the_wake_word_are_the_chats_first_turn(tmp_path, monkeypatch):
    visit = make_chat(tmp_path, monkeypatch, [])
    visit.call = {**visit.call, "first": "tell me a joke"}
    visit.greet()
    assert visit.history.transcript() == [("resident", "tell me a joke"), ("robot", "Hello!")]


def test_a_bell_during_a_chat_ends_it_without_driving(tmp_path, monkeypatch):
    sent = []
    visit = make_chat(tmp_path, monkeypatch, sent)
    visit.bell = {"id": "c9"}
    visit.check_timers(time.monotonic())
    visit.job.result(5)
    assert visit.done and visit.voice.said == [voice_main.BELL_GOODBYE]
    assert sent == []  # the backend has already sent the robot; the chat itself never drives


def test_the_chat_keeps_looking_until_a_bell_rings(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CALL_POLL_S", 0.0)
    visit = make_chat(tmp_path, monkeypatch, [])
    answers = iter([None, None, {"id": "c9"}])
    visit.bell_check = lambda: next(answers)
    visit.watch_bells()
    assert visit.bell == {"id": "c9"}


class Bells:
    def __init__(self, *calls):
        self.calls = list(calls)

    def find_assigned_call(self, robot_id):
        return self.calls.pop(0) if self.calls else None


def test_a_bell_goes_before_an_asked_for_chat(monkeypatch):
    monkeypatch.setattr(config, "CALL_POLL_S", 0.01)
    voice_main.CHATS.put("what games do you have")
    try:
        assert voice_main.find_call(Bells({"id": "c1"}), None, set())["id"] == "c1"
        chat = voice_main.find_call(Bells(), None, set())
        assert chat["id"] == voice_main.CHAT_ID and chat["first"] == "what games do you have"
        assert voice_main.CHATS.empty()  # one request, one chat
        assert voice_main.next_call(Bells({"id": "c1"}), {"c1"}) is None  # already visited
    finally:
        voice_main.drop_chats()


@pytest.mark.parametrize(
    "text, words",
    [
        ("Hey Bellhop, what games do you have?", "what games do you have"),
        ("hey bellhop what games do you have", "what games do you have"),
        ("Hey, Bell hop.", ""),
        ("Bellhops!", ""),
        ("Nice weather today", None),
        ("The bell rang", None),
    ],
)
def test_wake_text(text, words):
    assert wake_text(text) == words


class SlowBrain(FakeBrain):
    """The first reply says one sentence, then keeps writing until it is cancelled."""

    def reply(self, system, messages, on_sentence, tool_ctx, allow_tools=True, cancel=None):
        self.calls += 1
        if self.calls == 1:
            on_sentence("calm", "Once upon a time.")
            assert cancel.wait(5)
            return "Once upon a time.", False
        return super().reply(system, messages, on_sentence, tool_ctx, allow_tools, cancel)


def test_its_name_cuts_the_reply_being_written_short(tmp_path, monkeypatch):
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), SlowBrain(("Okay.",)))
    visit.submit(visit.handle_turn, "Tell me a story", "flux", block(1), 0.5, 0.0, None, True)
    deadline = time.monotonic() + 5
    while not visit.voice.said and time.monotonic() < deadline:
        time.sleep(0.01)
    visit.turn_face_ok = True  # as hear() sets it for a turn said to the robot
    visit.end_of_turn("Bellhop, stop", time.monotonic())
    visit.job.result(timeout=5)
    assert visit.voice.said == ["Once upon a time.", "Okay."]
    assert [line for _, line in visit.history.transcript()] == [
        "Tell me a story",
        "Once upon a time.",
        "Bellhop, stop",
        "Okay.",
    ]


def test_the_mic_is_muted_only_while_sound_plays_and_the_face_holds_the_mood(
    tmp_path, monkeypatch
):
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), FakeBrain())
    assert visit.voice.on_play == visit.on_play
    visit.mood = "excited"
    ends = time.monotonic() + 2.0  # a sentence starts that plays for 2 s
    visit.on_play(ends)
    assert visit.mic.muted(ends - 0.1)
    assert not visit.mic.muted(ends + config.ECHO_TAIL_S)  # by itself: no wait() needed
    assert visit.eyes.expression(ends + config.EYES_MOOD_HOLD_S - 0.1) == "excited"
    visit.on_play(None)  # cut off early
    assert not visit.mic.muted(time.monotonic() + config.ECHO_TAIL_S)


def test_a_job_and_a_recorded_reply_wait_for_the_last_sentence_to_play(tmp_path, monkeypatch):
    backend = FakeBackend()
    visit = make_visit(tmp_path, monkeypatch, backend, FakeBrain())
    visit.voice.wait = lambda: backend.log.append(("played",))
    visit.submit(visit.say_line, "Hello.")
    visit.job.result(timeout=5)
    # before the turn is posted and the attention window opens, and again at the job's end
    assert backend.log == [("played",), ("turn", "robot", "Hello."), ("played",)]


def test_speech_that_was_dropped_still_keeps_a_chat_awake(tmp_path, monkeypatch):
    visit = make_chat(tmp_path, monkeypatch, [])
    now = time.monotonic()
    visit.last_activity = now - 10 * config.CHAT_QUIET_S
    visit.speech_end, visit.turn_pending = now - 1, True
    visit.end_of_turn("", now)  # an empty transcript is dropped
    visit.check_timers(now)
    assert visit.phase == "talk" and visit.job is None


def test_a_chat_does_not_answer_speech_flux_saw_no_turn_in(tmp_path, monkeypatch, capsys):
    visit = make_chat(tmp_path, monkeypatch, [])
    visit.flux_ok = True
    now = time.monotonic()
    visit.turn_audio, visit.turn_pending, visit.turn_face_ok = [block(5)], True, True
    visit.speech_end = now - config.FLUX_TURN_LIMIT_S - 0.1
    visit.check_timers(now)
    assert not visit.turn_pending and visit.idle() and not visit.skip_flux_turn
    assert "not answering" in capsys.readouterr().out
    visit.end_of_turn("Hello there", now)  # Flux was only late: its turn is answered
    visit.job.result(timeout=5)
    assert visit.voice.said == ["Hello!"]
    assert "no one was facing" not in capsys.readouterr().out


def test_moonshine_transcribes_on_its_own_thread_while_the_robot_carries_on(
    tmp_path, monkeypatch
):
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), FakeBrain(("Righto.",)))
    release = threading.Event()

    def transcribe(audio):
        release.wait(5)  # Moonshine on the Pi's CPU
        return "I would like some water please"

    visit.stt = SimpleNamespace(transcribe=transcribe)
    now = time.monotonic()
    visit.turn_audio, visit.turn_pending, visit.turn_face_ok = [block(5)], True, True
    visit.speech_end = now - config.FLUX_TURN_LIMIT_S - 0.1
    visit.check_timers(now)  # Flux is down (flux_ok False)
    assert visit.transcribing and not visit.idle()  # nor does a quiet timer end the visit
    visit.events.put(("GameSay", "Your turn!", now))
    visit.handle_events()
    visit.job.result(timeout=5)  # the worker was free for the game's line
    assert visit.voice.said == ["Your turn!"]
    release.set()
    visit.transcribing[0].result(timeout=5)
    visit.check_timers(time.monotonic())
    visit.job.result(timeout=5)
    assert visit.voice.said == ["Your turn!", "Righto."] and visit.idle()
    assert visit.history.transcript()[-2] == ("resident", "I would like some water please")


def test_a_chat_with_no_mic_does_not_say_a_nurse_is_coming(tmp_path, monkeypatch):
    visit = make_chat(tmp_path, monkeypatch, [])
    visit.mic = RecordingMic(fail_start=True)
    visit.begin = lambda: None
    visit.run()  # no SystemExit: the robot stays up for the next bell
    assert visit.voice.said == [voice_main.CHAT_NO_MIC] and "nurse to come" not in visit.no_mic
    assert visit.done and visit.eyes.base == "idle"


def test_a_visit_does_not_end_while_moonshine_is_still_hearing_the_resident(
    tmp_path, monkeypatch
):
    backend = FakeBackend(urgency=1)
    visit = make_visit(tmp_path, monkeypatch, backend, FakeBrain())
    release = threading.Event()
    visit.stt = SimpleNamespace(transcribe=lambda audio: release.wait(5) and "wait my chest hurts")
    now = time.monotonic()
    visit.turn_audio, visit.turn_pending, visit.turn_face_ok = [block(5)], True, True
    visit.speech_end = now - config.FLUX_TURN_LIMIT_S - 0.1
    visit.check_timers(now)
    assert visit.resident_spoke()  # so finish() keeps talking instead of resolving
    release.set()
    visit.transcribing[0].result(timeout=5)
    visit.check_timers(time.monotonic())
    visit.job.result(timeout=5)
    assert ("resident", "wait my chest hurts") in visit.history.transcript()


def test_a_flux_turn_waits_behind_an_earlier_moonshine_turn(tmp_path, monkeypatch):
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), FakeBrain(("Yes.",)))
    visit.flux_ok = True
    release = threading.Event()
    visit.stt = SimpleNamespace(transcribe=lambda audio: release.wait(5) and "first thing I said")
    now = time.monotonic()
    visit.turn_audio, visit.turn_pending, visit.turn_face_ok = [block(5)], True, True
    visit.speech_end = now - config.FLUX_TURN_LIMIT_S - 0.1
    visit.check_timers(now)  # Flux is late: Moonshine takes the first turn
    visit.events.put(("StartOfTurn", "", now))
    visit.handle_events()
    visit.turn_audio, visit.turn_pending, visit.turn_face_ok = [block(5)], True, True
    visit.speech_end = time.monotonic()
    visit.end_of_turn("second thing I said", time.monotonic())
    assert visit.job is None and len(visit.transcribing) == 2  # queued, not answered first
    release.set()
    visit.transcribing[0].result(timeout=5)
    for _ in range(2):
        visit.check_timers(time.monotonic())
        visit.job.result(timeout=5)
    said = [text for speaker, text in visit.history.transcript() if speaker == "resident"]
    assert said == ["first thing I said", "second thing I said"]


class QuietBrain(FakeBrain):
    """The first reply thinks (says nothing) until it is cancelled; later ones answer."""

    def __init__(self, sentences=("Okay.",)):
        super().__init__(sentences)
        self.thinking = threading.Event()
        self.heard = []

    def reply(self, system, messages, on_sentence, tool_ctx, allow_tools=True, cancel=None):
        self.heard.append(messages[-1]["content"])
        if self.calls == 0:
            self.calls += 1
            self.thinking.set()
            assert cancel.wait(5)
            return "", False
        return super().reply(system, messages, on_sentence, tool_ctx, allow_tools, cancel)


def test_more_speech_before_the_reply_begins_is_answered_with_it(tmp_path, monkeypatch, capsys):
    brain = QuietBrain()
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), brain)
    visit.turn_face_ok = True
    visit.end_of_turn("Can we play", time.monotonic())
    assert brain.thinking.wait(5)
    visit.turn_face_ok = True
    visit.end_of_turn("tic-tac-toe please", time.monotonic())
    visit.job.result(timeout=5)
    assert visit.voice.said == ["Okay."]  # one answer, to both
    assert brain.heard[-1] == "Can we play tic-tac-toe please"
    assert "more speech before the reply began" in capsys.readouterr().out


def test_turns_waiting_behind_a_reply_get_one_answer(tmp_path, monkeypatch):
    brain = FakeBrain(("Sure.",))
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), brain)
    gate = threading.Event()

    def busy():
        gate.wait(5)  # the robot is still answering something else

    visit.submit(busy)
    for words in ("Can we", "play bingo"):
        visit.turn_face_ok = True
        visit.end_of_turn(words, time.monotonic())
    gate.set()
    visit.job.result(timeout=5)
    assert brain.calls == 1 and visit.voice.said == ["Sure."]
    assert [line for _, line in visit.history.transcript()] == ["Can we", "play bingo", "Sure."]


def test_the_prompt_carries_what_the_robot_did_this_visit(tmp_path, monkeypatch):
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), FakeBrain())
    visit.tool_ctx.done.append("end_game: the game is closed")
    assert "- end_game: the game is closed" in visit.system_prompt()


def make_facing_visit(tmp_path, monkeypatch, brain):
    """A real visit's face gate: turns can be said to the robot or not."""
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), brain)
    visit.face = FaceGate(None)  # not disabled
    return visit


def test_speech_not_said_to_the_robot_does_not_cut_a_reply_or_lose_a_turn(tmp_path, monkeypatch):
    brain = QuietBrain()
    visit = make_facing_visit(tmp_path, monkeypatch, brain)
    visit.turn_face_ok = True
    visit.end_of_turn("Can you get me some water", time.monotonic())
    assert brain.thinking.wait(5)
    visit.turn_face_ok = False  # a nurse in the doorway answers someone else
    visit.end_of_turn("yes dear, in a minute", time.monotonic())
    assert not visit.interrupt.is_set()  # the resident's reply is not cut
    visit.interrupt.set()  # end the QuietBrain's first reply so the test can finish
    visit.job.result(timeout=5)


def test_a_waiting_turn_said_to_the_robot_is_answered_even_if_the_next_is_not(
    tmp_path, monkeypatch
):
    brain = FakeBrain(("Of course.",))
    visit = make_facing_visit(tmp_path, monkeypatch, brain)
    gate = threading.Event()

    def busy():
        gate.wait(5)

    visit.submit(busy)
    for words, facing in (("Can you get me some water", True), ("yes dear, in a minute", False)):
        visit.turn_face_ok = facing
        visit.end_of_turn(words, time.monotonic())
    gate.set()
    visit.job.result(timeout=5)
    assert brain.calls == 1 and visit.voice.said == ["Of course."]


class OpenBook:
    """Reader stand-in: a title, then one paragraph, then the end."""

    def __init__(self):
        self.parts = [["Chapter 1."], ["It was cold.", "They walked."]]
        self.at = 0
        self.reading = True

    def next_part(self):
        return self.parts[self.at] if self.reading else []

    def done_part(self):
        if self.reading:
            self.at += 1
            self.reading = self.at < len(self.parts)

    def pause(self):
        was, self.reading = self.reading, False
        return was

    def resume(self):
        self.reading = self.at < len(self.parts)

    def status(self):
        return "The Happy Prince by Oscar Wilde, stopped about 10% through."


class WaitBrain(FakeBrain):
    def reply(self, system, messages, on_sentence, tool_ctx, allow_tools=True, cancel=None):
        self.calls += 1
        return WAIT, False


def test_the_open_book_is_read_in_the_gaps(tmp_path, monkeypatch):
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), FakeBrain())
    assert visit.tool_ctx.reader is visit.reader  # the read_book tool opens this visit's book
    visit.reader = OpenBook()
    visit.check_timers(time.monotonic())
    visit.job.result(5)
    assert visit.voice.said == ["Chapter 1."] and visit.last_reply == "Chapter 1."
    gap_over = visit.read_done_at + config.READ_GAP_S
    visit.check_timers(gap_over - 0.1)  # the gap: the mic is listening
    visit.speech_end, visit.turn_pending = gap_over, True
    visit.check_timers(gap_over)  # they are speaking
    assert visit.submitted == 1
    visit.turn_pending = False
    visit.check_timers(gap_over)
    visit.job.result(5)
    assert visit.voice.said == ["Chapter 1.", "It was cold.", "They walked."]
    assert visit.history.transcript() == []  # the book is not the conversation


def test_any_turn_stops_the_book_and_only_wait_reads_on(tmp_path, monkeypatch):
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), WaitBrain())
    visit.reader = OpenBook()
    visit.handle_turn("so I told her", "flux", block(1), 0.5, time.monotonic(), None, True)
    assert visit.reader.reading  # that was not for the robot

    visit.handle_turn("help me", "flux", block(1), 0.5, time.monotonic(), None, False)
    assert not visit.reader.reading  # not facing the robot, but it may be a call for help
    visit.reader.resume()
    visit.brain = FakeBrain(("I'll stop there.",))
    visit.handle_turn("stop reading", "flux", block(1), 0.5, time.monotonic(), None, True)
    assert not visit.reader.reading and visit.voice.said == ["I'll stop there."]
    for thread in visit.triage_threads:
        thread.join()
    status = "The Happy Prince by Oscar Wilde, stopped about 10% through."
    assert f"## A story is open\n{status}" in visit.system_prompt()


def test_speech_as_a_part_begins_stops_it_and_it_is_read_again(tmp_path, monkeypatch):
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), FakeBrain())
    visit.reader = OpenBook()
    visit.reader.at = 1
    said = visit.voice.say

    def say_then_hear(sentence, tone):
        said(sentence, tone)
        visit.turn_pending = True  # "help, I've fallen" as the first sentence starts

    visit.voice.say = say_then_hear
    visit.read_on()
    assert visit.voice.said == ["It was cold."]  # not "They walked."
    assert visit.reader.at == 1 and visit.reader.reading  # the part is read again


def test_no_story_while_triage_asks_for_a_nurse(tmp_path, monkeypatch, capsys):
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), FakeBrain())
    visit.reader = OpenBook()
    visit.latest_call = {"urgency": 3}
    quiet_since = visit.last_activity
    visit.read_on()
    assert visit.voice.said == [] and not visit.reader.reading
    assert visit.last_activity == quiet_since  # the quiet clock leads on to the nurse path
    assert "triage asks for a nurse" in capsys.readouterr().out


def test_a_wait_reply_to_merged_turns_reads_on(tmp_path, monkeypatch):
    visit = make_visit(tmp_path, monkeypatch, FakeBackend(), WaitBrain())
    visit.reader = OpenBook()
    visit.handle_turn("so then", "flux", block(1), 0.5, time.monotonic(), None, True, False)
    visit.handle_turn("she said", "flux", block(1), 0.5, time.monotonic(), None, True)
    for thread in visit.triage_threads:
        thread.join()
    assert visit.reader.reading and visit.read_paused is False
