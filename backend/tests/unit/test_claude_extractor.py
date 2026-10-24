from datetime import UTC, datetime
from types import SimpleNamespace

from bellhop.adapters.claude_extractor import DEFAULT_MODEL, ClaudeFactExtractor
from bellhop.domain import Turn
from bellhop.domain.learning import CandidateFact, ExtractedFacts, FactKind, Subject

AT = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
TALK = [
    Turn(speaker="resident", text="I take my tea with two sugars.", at=AT),
    Turn(speaker="robot", text="Noted.", at=AT),
]
FACT = CandidateFact(
    kind=FactKind.LIKE,
    text="Takes tea with two sugars",
    quote="I take my tea with two sugars",
    speaker="resident",
    subject=Subject.RESIDENT,
    confidence=0.9,
)


class FakeClient:
    def __init__(self, parsed):
        self.calls = []
        self.messages = SimpleNamespace(parse=self._parse)
        self._parsed = parsed

    def _parse(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(parsed_output=self._parsed, stop_reason="end_turn")


def test_returns_the_parsed_facts():
    client = FakeClient(ExtractedFacts(facts=[FACT]))
    assert ClaudeFactExtractor(client=client).extract(TALK) == [FACT]


def test_asks_for_the_structured_schema_and_sends_the_transcript():
    client = FakeClient(ExtractedFacts(facts=[]))
    ClaudeFactExtractor(client=client).extract(TALK, known_facts=["Likes crosswords"])
    call = client.calls[0]
    assert call["output_format"] is ExtractedFacts
    content = call["messages"][0]["content"]
    assert "resident: I take my tea with two sugars." in content
    assert "robot: Noted." in content
    assert "Likes crosswords" in content


def test_system_prompt_states_the_accuracy_rules():
    client = FakeClient(ExtractedFacts(facts=[]))
    ClaudeFactExtractor(client=client).extract(TALK)
    system = client.calls[0]["system"]
    system = system if isinstance(system, str) else " ".join(b["text"] for b in system)
    for rule in ("verbatim", "never what the robot said", "hypothetical", "negat", "empty"):
        assert rule in system.lower(), rule


def test_model_and_effort_are_configurable():
    client = FakeClient(ExtractedFacts(facts=[]))
    ClaudeFactExtractor(client=client, model="claude-sonnet-5-5", effort="medium").extract(TALK)
    call = client.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert call["output_config"] == {"effort": "medium"}


def test_default_model_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("BELLHOP_EXTRACTOR_MODEL", "claude-haiku-5-5")
    client = FakeClient(ExtractedFacts(facts=[]))
    ClaudeFactExtractor(client=client).extract(TALK)
    assert client.calls[0]["model"] == "claude-haiku-5-5"


def test_default_model_without_environment(monkeypatch):
    monkeypatch.delenv("BELLHOP_EXTRACTOR_MODEL", raising=False)
    client = FakeClient(ExtractedFacts(facts=[]))
    ClaudeFactExtractor(client=client).extract(TALK)
    assert client.calls[0]["model"] == DEFAULT_MODEL


def test_a_refusal_or_unparsed_reply_yields_no_facts():
    assert ClaudeFactExtractor(client=FakeClient(None)).extract(TALK) == []
