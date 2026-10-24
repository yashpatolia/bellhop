"""Thin uAgent wiring for ASI:One. Needs the optional `fetch` extra (uagents)."""

import os
from datetime import UTC, datetime
from uuid import uuid4

from bellhop.fetchai.answers import answer_question
from bellhop.fetchai.client import BellhopApi, BellhopApiError

UNREACHABLE = "I cannot reach the Bellhop system right now. Please try again in a moment."


def reply_for(question: str, api: BellhopApi) -> str:
    """Fetch data and answer; never raises on backend failure."""
    try:
        return answer_question(question, api.calls(), api.alerts(), api.metrics())
    except BellhopApiError:
        return UNREACHABLE


def build_agent(api: BellhopApi | None = None):  # noqa: ANN201
    from uagents import Agent, Context, Protocol  # lazy: optional dependency
    from uagents_core.contrib.protocols.chat import (
        ChatAcknowledgement,
        ChatMessage,
        TextContent,
        chat_protocol_spec,
    )

    seed = os.environ.get("BELLHOP_AGENT_SEED")
    if not seed:
        raise RuntimeError("Set BELLHOP_AGENT_SEED (any long secret phrase) before starting.")
    api = api or BellhopApi(os.environ.get("BELLHOP_API", "http://127.0.0.1:8000"))
    agent = Agent(
        name="bellhop-liaison",
        seed=seed,
        port=int(os.environ.get("BELLHOP_AGENT_PORT", "8001")),
        mailbox=True,
    )
    protocol = Protocol(spec=chat_protocol_spec)

    @protocol.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
        await ctx.send(
            sender,
            ChatAcknowledgement(timestamp=datetime.now(UTC), acknowledged_msg_id=msg.msg_id),
        )
        question = " ".join(c.text for c in msg.content if isinstance(c, TextContent))
        await ctx.send(
            sender,
            ChatMessage(
                timestamp=datetime.now(UTC),
                msg_id=uuid4(),
                content=[TextContent(type="text", text=reply_for(question, api))],
            ),
        )

    @protocol.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
        return None

    agent.include(protocol, publish_manifest=True)
    return agent


def main() -> None:
    build_agent().run()
