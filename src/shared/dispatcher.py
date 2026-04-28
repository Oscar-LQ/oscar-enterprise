"""Channel-to-agent dispatcher.

Receives an ``InboundMessage`` from a ``Channel``, derives a deterministic
LangGraph ``thread_id`` from the channel's ``conversation_id`` so multi-
turn memory persists per conversation (and is isolated across
conversations), constructs a per-invocation agent with a progress
callback bound to the originating conversation, invokes the agent with
the appropriate ``configurable`` config, and posts the agent's final
reply back via the channel.

Design notes:
- ADR 023: direct ``thread_id := conversation_id`` mapping, no hashing,
  async-first.
- ADR 026: front-door agent is a LangChain ``CompiledStateGraph``
  built by :func:`shared.agents.orchestrator.build_orchestrator`.
- ADR 028: progress narration is a per-invocation callback bound to the
  Slack-thread-scoped ``Channel.post_progress``. The dispatcher rebuilds
  the agent per ``handle()`` call so the redline tool's closure captures
  the right callback for this conversation. The shared ``MemorySaver`` is
  passed by the runtime so per-conversation memory persists across
  rebuilds.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.messages import AIMessage, HumanMessage

from shared.channels.base import Channel, InboundMessage


_NO_REPLY_FALLBACK = "<no reply produced>"


class Graph(Protocol):
    """Subset of LangGraph ``CompiledStateGraph`` the dispatcher depends on.

    Both ``deepagents.create_deep_agent`` (M2) and
    ``langchain.agents.create_agent`` (M3) return objects that implement
    this Protocol. Tests pass a stub.
    """

    async def ainvoke(
        self,
        input: Mapping[str, Any],
        config: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...


ProgressCallback = Callable[[str], Awaitable[None]]
"""Async callback the dispatcher hands to the agent factory per invocation."""

AgentFactory = Callable[[ProgressCallback], Graph]
"""Constructs an agent bound to a particular conversation's progress callback.

The runtime supplies a factory that closes over the shared MemorySaver and
M3 default paths; the dispatcher calls it once per inbound message,
passing a callback that posts to the originating conversation.
"""


@dataclass
class Dispatcher:
    """Bridges Channel inbound messages to a LangChain (or Deep Agent) graph.

    Wired by the runtime as::

        dispatcher = Dispatcher(channel=channel, agent_factory=factory)
        channel.on_inbound_message(dispatcher.handle)
        await channel.start()

    The factory shape captures the per-invocation rebuild rule from
    ADR 028: each inbound message gets a fresh agent with a callback
    bound to its conversation_id.
    """

    channel: Channel
    agent_factory: AgentFactory

    async def handle(self, message: InboundMessage) -> None:
        """Round-trip one inbound message: build agent for this
        conversation, invoke it with thread-scoped config, post the
        final reply back via the channel."""
        thread_id = self.thread_id_for(message.conversation_id)

        async def _progress(text: str) -> None:
            await self.channel.post_progress(
                conversation_id=message.conversation_id, text=text
            )

        agent = self.agent_factory(_progress)
        result = await agent.ainvoke(
            {"messages": [HumanMessage(message.text)]},
            config={"configurable": {"thread_id": thread_id}},
        )
        reply = self._final_reply_text(result.get("messages", []))
        await self.channel.post_message(
            conversation_id=message.conversation_id, text=reply
        )

    @staticmethod
    def thread_id_for(conversation_id: str) -> str:
        """Direct mapping (ADR 023). The ``conversation_id`` is already a
        stable per-conversation identifier supplied by the channel
        (e.g. Slack ``channel:thread_ts``); LangGraph imposes no length
        or character constraints on ``thread_id``, so no hashing is
        required."""
        return conversation_id

    @staticmethod
    def _final_reply_text(messages: list[Any]) -> str:
        """Last AIMessage with content and no tool_calls is the user-facing
        reply. Mirrors the Sprint 9 ``_final_text`` helper."""
        for msg in reversed(messages):
            if (
                isinstance(msg, AIMessage)
                and msg.content
                and not getattr(msg, "tool_calls", None)
            ):
                return _stringify_content(msg.content)
        return _NO_REPLY_FALLBACK


def _stringify_content(content: Any) -> str:
    """LangChain ``AIMessage.content`` can be a plain string or a list of
    block dicts (multimodal / structured content). Flatten to a string."""
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", block)))
            else:
                parts.append(str(block))
        return " ".join(parts)
    return str(content)
