import os
import threading
import time
from datetime import datetime
from types import SimpleNamespace

import httpx

from rover import config
from rover.agent import brain, context, tools
from rover.agent.brain import Brain, SentenceSplitter, split_tone
from rover.agent.context import VisitHistory, activity_for, build_system_prompt
from rover.agent.tools import ToolContext, run_tool

MARGARET = {
    "id": "res_margaret",
    "name": "Margaret",
    "room": "12",
    "risk_flags": ["falls"],
    "birth_year": 1938,
}
PREFS = {
    "hard_of_hearing": True,
    "quiet_mode": False,
    "night_mode": False,
    "favourite_drink": "tea",
}
NOW = datetime(2026, 10, 24, 15, 30)


def test_prompt_has_resident_facts_activity_and_time():
    memories = [{"text": "Takes her tea with two sugars"}, {"text": "Grandson is called Tom"}]
    prompt = build_system_prompt(
        MARGARET, PREFS, memories, "One person, facing you.", "pain_check", NOW
    )
    for expected in (
        "Margaret",
        "Room: 12",
        "falls",
        "1938",
        "hard of hearing",
        "favourite drink: tea",
        "Takes her tea with two sugars",
        "One person, facing you.",
        "pain check",
        "Saturday 24 October 2026",
        "15:30",
        config.ROBOT_NAME,
    ):
        assert expected in prompt
    assert "{robot_name}" not in prompt
    assert "quiet mode" not in prompt


def test_prompt_without_memories_or_resident_invents_nothing():
    prompt = build_system_prompt(MARGARET, None, [], "", None, NOW)
    assert "Things you know" not in prompt
    assert "Preferences" not in prompt
    assert "camera" not in prompt.split("## Who you are talking to")[1]
    unknown = build_system_prompt(None, None, [], "", None, NOW)
    assert "Ask their name" in unknown and "Margaret" not in unknown


def test_activity_for_category():
    assert activity_for("pain") == "pain_check"
    assert activity_for("confusion") == "gentle"
    assert activity_for("fall") is None and activity_for(None) is None
    assert "one question at a time" in context.load_activity("gentle")


def test_history_merges_alternates_and_starts_with_user():
    history = VisitHistory()
    history.add("robot", "Hello Margaret!")
    history.add("resident", "Hello.")
    history.add("resident", "My hip hurts.")
    history.add("assistant", "I'm sorry.")
    history.add("user", "   ")
    messages = history.messages()
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0]["content"] == context.VISIT_START
    assert messages[2]["content"] == "Hello. My hip hurts."
    assert history.transcript() == [
        ("robot", "Hello Margaret!"),
        ("resident", "Hello."),
        ("resident", "My hip hurts."),
        ("robot", "I'm sorry."),
    ]


def test_history_keeps_last_exchanges(monkeypatch):
    monkeypatch.setattr(config, "HISTORY_EXCHANGES", 2)
    history = VisitHistory()
    history.add("robot", "Hi!")
    for n in range(5):
        history.add("resident", f"r{n}")
        history.add("robot", f"b{n}")
    history.add("resident", "last")
    messages = history.messages()
    assert messages[0]["role"] == "user"
    assert [m["content"] for m in messages] == ["r4", "b4", "last"]
    assert len(history.transcript()) == 12


def test_split_tone():
    assert split_tone("[calm] Take your time.") == ("calm", "Take your time.")
    assert split_tone("[Gentle]I'm sorry.") == ("gentle", "I'm sorry.")
    assert split_tone("[shouty] Hi!") == (config.DEFAULT_TONE, "Hi!")
    assert split_tone("No tag here.") == (config.DEFAULT_TONE, "No tag here.")


def test_sentence_splitter_waits_for_a_boundary():
    splitter = SentenceSplitter()
    assert splitter.feed("Hello there") == []
    assert splitter.feed("!") == []
    assert splitter.feed(" How are") == ["Hello there!"]
    assert splitter.feed(" you? It costs 3.50 today") == ["How are you?"]
    assert splitter.feed("\nBye") == ["It costs 3.50 today"]
    assert splitter.flush() == ["Bye"]
    assert splitter.flush() == []


def test_brain_without_client_speaks_the_fallback_line():
    robot = Brain(client=object())
    robot.client = None
    said = []
    text, wanted_tool = robot.reply("sys", [], lambda tone, s: said.append((tone, s)), None)
    assert said == [(brain.FALLBACK_TONE, brain.FALLBACK_LINE)]
    assert (text, wanted_tool) == (brain.FALLBACK_LINE, False)


class FakeStream:
    def __init__(self, chunks, final, delay=0.0):
        self.chunks, self.final, self.delay = chunks, final, delay

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        time.sleep(self.delay)
        for chunk in self.chunks:
            yield SimpleNamespace(type="text", text=chunk)

    def get_final_message(self):
        return self.final


class FakeClient:
    def __init__(self, *streams):
        self.streams = list(streams)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    def stream(self, **kwargs):
        self.requests.append(kwargs)
        return self.streams.pop(0)


def done(*content):
    return SimpleNamespace(stop_reason="end_turn", content=list(content), stop_details=None)


def wants_tool(name, args):
    block = SimpleNamespace(type="tool_use", id="tool_1", name=name, input=args)
    return SimpleNamespace(stop_reason="tool_use", content=[block], stop_details=None)


def test_brain_streams_sentences_with_one_tone_and_no_tags():
    client = FakeClient(
        FakeStream(["[calm] Hello", " there. How are", " you? [gentle]I am", " here"], done())
    )
    said = []
    text, wanted_tool = Brain(client).reply(
        "sys", [{"role": "user", "content": "hi"}], lambda tone, s: said.append((tone, s)), None
    )
    assert said == [("calm", "Hello there."), ("calm", "How are you?"), ("calm", "I am here")]
    assert (text, wanted_tool) == ("Hello there. How are you? I am here", False)
    request = client.requests[0]
    assert request["model"] == config.BRAIN_MODEL and "temperature" not in request


def test_brain_returns_wait_without_speaking():
    said = []
    result = Brain(FakeClient(FakeStream(["WAIT"], done()))).reply(
        "sys", [], lambda tone, s: said.append(s), None
    )
    assert result == ("WAIT", False) and said == []


class FakeBackend:
    def __init__(self):
        self.scores = []

    def score(self, *args):
        self.scores.append(args)
        return {"id": args[0]}


def test_brain_runs_a_tool_then_continues():
    backend = FakeBackend()
    client = FakeClient(
        FakeStream([], wants_tool("request_staff", {"reason": "Wants a nurse"})),
        FakeStream(["[calm] A nurse is on the way."], done()),
    )
    said = []
    text, wanted_tool = Brain(client).reply(
        "sys",
        [{"role": "user", "content": "nurse please"}],
        lambda tone, s: said.append(s),
        ToolContext(backend, "c1"),
    )
    assert backend.scores == [("c1", 3, "asks_for_nurse", "Wants a nurse", 1.0)]
    assert said == ["A nurse is on the way."] and wanted_tool is False
    tool_result = client.requests[1]["messages"][-1]["content"][0]
    assert tool_result == {
        "type": "tool_result",
        "tool_use_id": "tool_1",
        "content": "staff notified",
    }


def test_brain_draft_reports_a_wanted_tool_without_running_it():
    backend = FakeBackend()
    client = FakeClient(FakeStream(["Let me check."], wants_tool("request_staff", {"reason": "x"})))
    _, wanted_tool = Brain(client).reply(
        "sys", [], lambda tone, s: None, ToolContext(backend, "c1"), allow_tools=False
    )
    assert wanted_tool is True and backend.scores == []


def test_brain_speaks_fallback_when_first_text_is_late(monkeypatch):
    monkeypatch.setattr(config, "FIRST_TEXT_TIMEOUT_S", 0.05)
    client = FakeClient(FakeStream(["[cheerful] Here I am."], done(), delay=0.5))
    said = []
    Brain(client).reply("sys", [], lambda tone, s: said.append(s), None)
    assert said == [brain.FALLBACK_LINE, "Here I am."]


def test_brain_cancel_stops_speaking():
    cancel = threading.Event()
    cancel.set()
    said = []
    Brain(FakeClient(FakeStream(["Hello. There."], done()))).reply(
        "sys", [], lambda tone, s: said.append(s), None, cancel=cancel
    )
    assert said == []


def test_look_returns_a_fresh_image_only(tmp_path, monkeypatch):
    jpg = tmp_path / "latest.jpg"
    monkeypatch.setattr(config, "LATEST_JPG", jpg)
    ctx = ToolContext(backend=FakeBackend(), call_id="c1")
    assert run_tool("look", {}, ctx) == "camera image not available"
    jpg.write_bytes(b"\xff\xd8fake")
    content = run_tool("look", {}, ctx)
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
    old = time.time() - config.LOOK_MAX_AGE_S - 5
    os.utime(jpg, (old, old))
    assert run_tool("look", {}, ctx) == "camera image not available"


def test_request_staff_without_call_reports_failure():
    assert run_tool("request_staff", {"reason": "x"}, ToolContext(FakeBackend(), None)).startswith(
        "could not notify staff"
    )
    assert [tool["name"] for tool in tools.TOOLS] == [
        "look",
        "request_staff",
        "stop",
        "go_to_room",
        "follow_patient",
        "face_patient",
    ]


class FakePost:
    def __init__(self, status=200, error=None):
        self.status, self.error, self.sent = status, error, []

    def __call__(self, url, json, timeout):
        self.sent.append((url, json))
        if self.error:
            raise self.error
        return httpx.Response(self.status, request=httpx.Request("POST", url))


def test_moving_tools_post_to_the_drive_server(monkeypatch):
    post = FakePost()
    monkeypatch.setattr(tools.httpx, "post", post)
    ctx = ToolContext(FakeBackend(), "c1")
    assert run_tool("go_to_room", {"room": "12"}, ctx) == "on the way to room 12"
    assert run_tool("follow_patient", {}, ctx) == "following the resident"
    assert run_tool("face_patient", {}, ctx) == "turning to face the resident"
    assert run_tool("stop", {}, ctx) == "stopped"
    url = config.PI_SERVER_URL
    assert post.sent == [
        (f"{url}/go_to", {"room": "12"}),
        (f"{url}/follow", {}),
        (f"{url}/face", {}),
        (f"{url}/stop", {}),
    ]


def test_go_to_room_refuses_unknown_rooms_without_posting(monkeypatch):
    post = FakePost()
    monkeypatch.setattr(tools.httpx, "post", post)
    answer = run_tool("go_to_room", {"room": "dining room"}, ToolContext(FakeBackend(), "c1"))
    assert post.sent == [] and "valid rooms are" in answer
    assert all(room in answer for room in config.MARKER_ROOMS.values())


def test_moving_tool_failures_are_short_and_printed(monkeypatch, capsys):
    ctx = ToolContext(FakeBackend(), "c1")
    monkeypatch.setattr(tools.httpx, "post", FakePost(error=httpx.ConnectError("refused")))
    assert run_tool("stop", {}, ctx) == "stop failed (ConnectError)"
    monkeypatch.setattr(tools.httpx, "post", FakePost(status=503))
    assert run_tool("follow_patient", {}, ctx) == "follow_patient failed (503)"
    out = capsys.readouterr().out
    assert "refused" in out and "503" in out


class BrokenStream(FakeStream):
    def __iter__(self):
        yield SimpleNamespace(type="text", text="[calm] Hello there. Still")
        raise TimeoutError("read timed out")


def test_brain_survives_a_stream_error_mid_reply(capsys):
    said = []
    text, wanted_tool = Brain(FakeClient(BrokenStream([], done()))).reply(
        "sys", [], lambda tone, s: said.append(s), None
    )
    assert said == ["Hello there."] and (text, wanted_tool) == ("Hello there.", False)
    assert "fallback: Claude stream failed" in capsys.readouterr().out
