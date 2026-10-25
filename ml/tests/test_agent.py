import os
import threading
import time
from datetime import datetime
from types import SimpleNamespace

import httpx

from rover import config
from rover.agent import brain, context, tools
from rover.agent.books import STORIES
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
    assert ctx.done == [
        "look: camera image not available",
        "look: looked through the camera (that picture is gone now: look again to see)",
        "look: camera image not available",
    ]


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
        "start_game",
        "end_game",
        "news",
        "trends",
        "read_book",
        "web_search",
    ]


class MemoryBackend:
    def __init__(self):
        self.saved = []

    def remember(self, resident_id, text, tags):
        self.saved.append((resident_id, text, tags))
        return {"id": "f1"}


class FakeGames:
    def __init__(self):
        self.started = []

    def start(self, name):
        self.started.append(name)
        return f"{name} opened"

    def stop(self):
        return "closed"


def test_start_game_remembers_only_a_game_the_resident_knows():
    backend, games = MemoryBackend(), FakeGames()
    ctx = ToolContext(backend, "c1", "res_margaret", games)
    assert run_tool("start_game", {"game": "bingo", "knows_rules": True}, ctx) == "bingo opened"
    assert run_tool("start_game", {"game": "memory", "knows_rules": False}, ctx) == "memory opened"
    assert backend.saved == [("res_margaret", "Knows how to play bingo.", ["game", "bingo"])]
    assert games.started == ["bingo", "memory"]
    assert run_tool("end_game", {}, ctx) == "closed"


def test_game_tools_without_a_screen_say_so():
    ctx = ToolContext(MemoryBackend(), "c1", None, None)
    result = run_tool("start_game", {"game": "tic_tac_toe", "knows_rules": True}, ctx)
    assert result.startswith("the screen is not available")
    assert ctx.backend.saved == []  # no resident on file: nothing to remember it for
    assert run_tool("end_game", {}, ctx) == "no game was open"


def test_start_game_is_strict_and_lists_the_three_games():
    tool = next(t for t in tools.TOOLS if t["name"] == "start_game")
    schema = tool["input_schema"]
    assert tool["strict"] and schema["required"] == ["game", "knows_rules"]
    assert schema["properties"]["game"]["enum"] == ["bingo", "tic_tac_toe", "memory"]
    assert "never on your own initiative" in tool["description"]


def test_prompt_lists_known_games_and_the_game_on_screen():
    facts = [{"tags": ["game", "memory"]}, {"tags": ["family"]}, {"tags": ["game", "bingo"]}]
    assert context.games_known(facts) == ["bingo", "memory"]
    prompt = build_system_prompt(
        MARGARET, PREFS, [], "", None, NOW, ["tic_tac_toe"], "Bingo: 3 numbers called."
    )
    assert "Games they already know how to play: tic-tac-toe" in prompt
    assert "## Right now: a game is on your screen\nBingo: 3 numbers called." in prompt
    assert "Never suggest a game" in prompt  # games come up only when the resident asks
    assert "Call start_game again only to switch" in prompt  # its tool calls are not in the history
    assert "## Right now: a game" not in build_system_prompt(MARGARET, PREFS, [], "", None, NOW)


def test_greeting_mentions_games():
    assert "play games" in context.GREETING.format(room="12")


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
    assert run_tool("go_to_room", {"room": "210"}, ctx) == "on the way to room 210"
    assert run_tool("follow_patient", {}, ctx) == "following the resident"
    assert run_tool("face_patient", {}, ctx) == "turning to face the resident"
    assert run_tool("stop", {}, ctx) == "stopped"
    url = config.PI_SERVER_URL
    assert post.sent == [
        (f"{url}/go_to", {"room": "210"}),
        (f"{url}/follow", {}),
        (f"{url}/face", {}),
        (f"{url}/stop", {}),
    ]


def test_go_to_room_refuses_unknown_rooms_without_posting(monkeypatch):
    post = FakePost()
    monkeypatch.setattr(tools.httpx, "post", post)
    answer = run_tool("go_to_room", {"room": "dining room"}, ToolContext(FakeBackend(), "c1"))
    assert post.sent == [] and "no configured room or marker" in answer


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


def capture_events(monkeypatch):
    events = []
    monkeypatch.setattr(brain.obslog, "event", lambda name, **kw: events.append((name, kw)))
    return events


def test_first_text_budget_fits_a_slow_pi_link():
    assert config.FIRST_TEXT_TIMEOUT_S >= 6.0


def test_brain_logs_latency_per_reply(monkeypatch):
    events = capture_events(monkeypatch)
    Brain(FakeClient(FakeStream(["Hello there. Bye."], done(), delay=0.05))).reply(
        "sys", [], lambda tone, s: None, None
    )
    ((name, fields),) = [e for e in events if e[0] == "brain.reply"]
    assert fields["fallback"] is False and fields["error"] is None
    assert fields["latency_ms"] >= fields["first_text_ms"] >= 40
    assert fields["draft"] is False


def test_brain_logs_the_fallback_and_draft_flag(monkeypatch):
    monkeypatch.setattr(config, "FIRST_TEXT_TIMEOUT_S", 0.05)
    events = capture_events(monkeypatch)
    client = FakeClient(FakeStream(["Hi."], done(), delay=0.3))
    Brain(client).reply("sys", [], lambda tone, s: None, None, allow_tools=False)
    fields = next(kw for name, kw in events if name == "brain.reply")
    assert fields["fallback"] is True and fields["draft"] is True


def test_fallback_line_is_not_spoken_twice_in_a_row(monkeypatch):
    monkeypatch.setattr(config, "FIRST_TEXT_TIMEOUT_S", 0.05)
    robot = Brain(
        FakeClient(
            FakeStream(["One."], done(), delay=0.3),
            FakeStream(["Two."], done(), delay=0.3),
            FakeStream(["Three."], done(), delay=0.3),
        )
    )
    said = []
    for _ in range(3):
        robot.reply("sys", [], lambda tone, s: said.append(s), None)
    assert said == [brain.FALLBACK_LINE, "One.", "Two.", "Three."]


def test_a_good_reply_re_arms_the_fallback(monkeypatch):
    robot = Brain(FakeClient(FakeStream(["Fine."], done())))
    robot._fell_back = True
    said = []
    robot.reply("sys", [], lambda tone, s: said.append(s), None)
    assert said == ["Fine."] and robot._fell_back is False


def test_failed_stream_does_not_repeat_the_fallback():
    class Boom(FakeStream):
        def __iter__(self):
            raise RuntimeError("down")
            yield

    robot = Brain(FakeClient(Boom([], done()), Boom([], done())))
    said = []
    for _ in range(2):
        robot.reply("sys", [], lambda tone, s: said.append(s), None)
    assert said == [brain.FALLBACK_LINE]


def test_warm_makes_one_cheap_request_and_never_raises():
    calls = []
    client = SimpleNamespace(models=SimpleNamespace(list=lambda **kw: calls.append(kw)))
    Brain(client).warm()
    assert len(calls) == 1

    def broken(**kw):
        raise httpx.ConnectError("offline")

    Brain(SimpleNamespace(models=SimpleNamespace(list=broken))).warm()
    Brain(object()).warm()


def test_claude_client_keeps_connections_alive_for_the_whole_visit(monkeypatch):
    seen = {}

    class Spy:
        api_key = "k"
        auth_token = None
        credentials = None

        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(brain, "_shared", None)
    monkeypatch.setattr(brain.anthropic, "Anthropic", Spy)
    first = brain.claude_client()
    assert first is not None and brain.claude_client() is first  # one shared pool
    pool = seen["http_client"]._transport._pool
    assert pool._keepalive_expiry == config.CLAUDE_KEEPALIVE_S >= 20


def test_the_prompt_lists_what_the_robot_did_so_it_does_not_redo_it():
    actions = [f"end_game: closed {i}" for i in range(config.ACTIONS_SHOWN + 2)]
    prompt = build_system_prompt(MARGARET, PREFS, [], "", None, NOW, actions=actions)
    assert "## What you have done this visit" in prompt and "Do not repeat one" in prompt
    assert "never say one worked if its result says it failed" in prompt  # no false "nurse coming"
    assert "- end_game: closed 2" in prompt and f"- end_game: closed {len(actions) - 1}" in prompt
    assert "- end_game: closed 1\n" not in prompt and "- end_game: closed 0" not in prompt
    assert "## What you have done" not in build_system_prompt(MARGARET, PREFS, [], "", None, NOW)


def searched(query, stop_reason="end_turn"):
    block = SimpleNamespace(
        type="server_tool_use", id="srv_1", name="web_search", input={"query": query}
    )
    return SimpleNamespace(stop_reason=stop_reason, content=[block], stop_details=None)


def test_a_paused_web_search_is_sent_back_and_noted():
    client = FakeClient(
        FakeStream([], searched("giants score", "pause_turn")),
        FakeStream(["[excited] They won!"], done()),
    )
    ctx = ToolContext(FakeBackend(), "c1")
    said = []
    question = {"role": "user", "content": "who won?"}
    _, wanted_tool = Brain(client).reply("sys", [question], lambda t, s: said.append(s), ctx)
    assert said == ["They won!"] and wanted_tool is False
    resent = client.requests[1]["messages"]
    assert resent == [question, {"role": "assistant", "content": searched("giants score").content}]
    gone = "the results are gone now: search again if needed"
    assert ctx.done == [f'web_search: searched for "giants score" ({gone})']


class SearchingStream(FakeStream):
    def __iter__(self):
        block = SimpleNamespace(type="server_tool_use")
        yield SimpleNamespace(type="content_block_start", content_block=block)
        raise AssertionError("the draft read on past the search")


class PreambleStream(FakeStream):
    def __init__(self, said):
        super().__init__([], searched("score"))
        self.said = said

    def __iter__(self):
        yield SimpleNamespace(type="text", text="[calm] Let me look.")
        block = SimpleNamespace(type="server_tool_use")
        yield SimpleNamespace(type="content_block_start", content_block=block)
        assert self.said == ["Let me look."]  # said while the search runs, not after it
        yield SimpleNamespace(type="text", text=" They won.")


def test_the_words_before_a_tool_are_said_before_it_runs():
    said = []
    Brain(FakeClient(PreambleStream(said))).reply("sys", [], lambda t, s: said.append(s), None)
    assert said == ["Let me look.", "They won."]


def test_a_draft_stops_at_a_web_search():
    client = FakeClient(SearchingStream([], done()))
    _, wanted_tool = Brain(client).reply("sys", [], lambda t, s: None, None, allow_tools=False)
    assert wanted_tool is True


def test_web_search_is_anthropics_own_tool():
    search = tools.TOOLS[-1]
    assert search["type"] == config.WEB_SEARCH_TOOL and search["name"] == "web_search"
    assert "strict" not in search and "input_schema" not in search


class FakeReader:
    def __init__(self):
        self.opened = []

    def open(self, query):
        self.opened.append(query)
        return "now reading it"


def test_news_trends_and_books_dispatch(monkeypatch):
    monkeypatch.setattr(tools.feeds, "tool_text", lambda name: f"{name} head:\n- one\n- two")
    ctx = ToolContext(MemoryBackend(), "c1")
    assert run_tool("news", {}, ctx) == "news head:\n- one\n- two"
    assert run_tool("trends", {}, ctx).startswith("trends head:")
    book = {"story": "the_gift_of_the_magi"}
    assert run_tool("read_book", book, ctx) == "you cannot read aloud right now"
    assert ctx.done[:2] == [
        "news: news head: (that list is gone now: use news again to see it)",
        "trends: trends head: (that list is gone now: use trends again to see it)",
    ]

    games, reader = FakeGames(), FakeReader()
    games.phase = "play"
    ctx = ToolContext(MemoryBackend(), "c1", None, games, reader=reader)
    assert run_tool("read_book", book, ctx).startswith("a game is on your screen")
    games.phase = None
    assert run_tool("read_book", book, ctx) == "now reading it"
    assert reader.opened == ["the_gift_of_the_magi"]


def test_read_book_offers_only_the_short_stories():
    tool = next(t for t in tools.TOOLS if t["name"] == "read_book")
    assert tool["strict"] and tool["input_schema"]["properties"]["story"]["enum"] == list(STORIES)
    assert "The Gift of the Magi by O. Henry, about 14 minutes" in tool["description"]


def test_prompt_shows_the_open_book():
    status = "Emma, stopped about 20% through."
    prompt = build_system_prompt(None, None, [], "", None, NOW, reading=status)
    assert "## A story is open\nEmma, stopped about 20% through." in prompt
    assert "A story is open" not in build_system_prompt(None, None, [], "", None, NOW)
