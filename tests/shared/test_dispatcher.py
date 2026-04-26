"""Dispatcher unit tests against FakeChannel + a stub Graph.

Covers the four directives from M2 spec § Tests:
  1. Dispatcher forwards inbound messages to the GC invoker.
  2. Dispatcher posts replies back to the originating ``conversation_id``.
  3. Same conversation produces the same LangGraph thread_id across invocations.
  4. Different conversations produce different thread_ids.

No LLM, no network. The Graph stub records calls and returns canned messages
shaped like a real Deep Agent ``ainvoke`` result.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from shared.channels.base import InboundMessage
from shared.channels.fake import FakeChannel
from shared.dispatcher import Dispatcher


@dataclass
class StubGraph:
    """Records ainvoke calls and returns a canned reply.

    Substitutes for a real ``CompiledStateGraph`` so the dispatcher can be
    exercised without invoking real LLMs.
    """

    reply: str = "stub-reply"
    calls: list[tuple[Mapping[str, Any], Mapping[str, Any] | None]] = field(
        default_factory=list
    )

    async def ainvoke(
        self,
        input: Mapping[str, Any],
        config: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        self.calls.append((input, config))
        original = input["messages"][0]
        return {"messages": [original, AIMessage(self.reply)]}


@pytest.fixture
def channel() -> FakeChannel:
    return FakeChannel()


@pytest.fixture
def graph() -> StubGraph:
    return StubGraph()


@pytest.fixture
def dispatcher(channel: FakeChannel, graph: StubGraph) -> Dispatcher:
    d = Dispatcher(channel=channel, gc_graph=graph)
    channel.on_inbound_message(d.handle)
    return d


@pytest.mark.asyncio
async def test_inbound_text_reaches_graph(
    channel: FakeChannel, graph: StubGraph, dispatcher: Dispatcher
) -> None:
    """Directive 1: dispatcher forwards inbound message text to the GC."""
    await channel.simulate_inbound(
        InboundMessage(conversation_id="C1:T1", text="hello there")
    )

    assert len(graph.calls) == 1
    input_arg, _ = graph.calls[0]
    msgs = input_arg["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], HumanMessage)
    assert msgs[0].content == "hello there"


@pytest.mark.asyncio
async def test_reply_posted_to_originating_conversation_id(
    channel: FakeChannel, graph: StubGraph, dispatcher: Dispatcher
) -> None:
    """Directive 2: reply lands on the conversation_id that received the inbound."""
    graph.reply = "the-reply-text"
    await channel.simulate_inbound(
        InboundMessage(conversation_id="C1:T1", text="hello")
    )

    assert len(channel.posted_messages) == 1
    posted = channel.posted_messages[0]
    assert posted.conversation_id == "C1:T1"
    assert posted.text == "the-reply-text"


@pytest.mark.asyncio
async def test_same_conversation_yields_same_thread_id(
    channel: FakeChannel, graph: StubGraph, dispatcher: Dispatcher
) -> None:
    """Directive 3: same-thread memory persistence relies on stable thread_id.

    The dispatcher must pass the same ``thread_id`` for two messages with the
    same ``conversation_id``, so a checkpointer-backed graph (MemorySaver in
    Phase 1, durable store in M3+) keys multi-turn memory consistently.
    """
    await channel.simulate_inbound(
        InboundMessage(conversation_id="C1:T1", text="first turn")
    )
    await channel.simulate_inbound(
        InboundMessage(conversation_id="C1:T1", text="second turn")
    )

    assert len(graph.calls) == 2
    tid_first = _thread_id_from(graph.calls[0][1])
    tid_second = _thread_id_from(graph.calls[1][1])

    assert tid_first == "C1:T1"
    assert tid_second == "C1:T1"
    assert tid_first == tid_second


@pytest.mark.asyncio
async def test_different_conversations_yield_distinct_thread_ids(
    channel: FakeChannel, graph: StubGraph, dispatcher: Dispatcher
) -> None:
    """Directive 4: distinct-thread isolation relies on distinct thread_ids."""
    await channel.simulate_inbound(
        InboundMessage(conversation_id="C1:T1", text="m1")
    )
    await channel.simulate_inbound(
        InboundMessage(conversation_id="C2:T2", text="m2")
    )

    assert len(graph.calls) == 2
    tid1 = _thread_id_from(graph.calls[0][1])
    tid2 = _thread_id_from(graph.calls[1][1])

    assert tid1 == "C1:T1"
    assert tid2 == "C2:T2"
    assert tid1 != tid2


def test_thread_id_derivation_is_pure_and_deterministic() -> None:
    """Direct mapping (ADR 023). Thread_id == conversation_id verbatim, no
    hashing, no per-call variation."""
    assert Dispatcher.thread_id_for("C1:T1") == "C1:T1"
    assert Dispatcher.thread_id_for("X:Y:Z") == "X:Y:Z"
    assert Dispatcher.thread_id_for("C1:T1") == Dispatcher.thread_id_for("C1:T1")


def _thread_id_from(config: Mapping[str, Any] | None) -> str | None:
    """Helper: dig the thread_id out of the config the dispatcher passed."""
    if config is None:
        return None
    return config.get("configurable", {}).get("thread_id")
