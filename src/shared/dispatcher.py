"""Channel-to-GC dispatcher.

Receives an ``InboundMessage`` from a ``Channel``, derives a deterministic
LangGraph ``thread_id`` from the channel's ``conversation_id`` so multi-turn
memory persists per conversation (and is isolated across conversations),
invokes the General Counsel graph with the appropriate ``configurable``
config, and posts the GC's final reply back via the channel.

Design notes are in ADR 023:
- Direct ``thread_id := conversation_id`` mapping. No hashing.
- Async-first because the production channels are async I/O.
- The dispatcher depends only on the ``ainvoke`` method of the GC graph;
  the ``Graph`` Protocol below pins that contract for type checkers and
  test stubs.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.messages import AIMessage, HumanMessage

from shared.channels.base import Channel, InboundMessage


_NO_REPLY_FALLBACK = "<no reply produced>"


class Graph(Protocol):
    """Subset of LangGraph ``CompiledStateGraph`` the dispatcher depends on.

    ``create_deep_agent(...)`` returns a ``CompiledStateGraph`` which
    implements this Protocol. Tests pass a stub.
    """

    async def ainvoke(
        self,
        input: Mapping[str, Any],
        config: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...


@dataclass
class Dispatcher:
    """Bridges Channel inbound messages to a Deep Agent graph.

    Wired by the runtime (Phase 3) as::

        dispatcher = Dispatcher(channel=channel, gc_graph=gc_graph)
        channel.on_inbound_message(dispatcher.handle)
        await channel.start()
    """

    channel: Channel
    gc_graph: Graph

    async def handle(self, message: InboundMessage) -> None:
        """Round-trip one inbound message: invoke GC with thread-scoped
        config, then post the GC's final reply back via the channel."""
        thread_id = self.thread_id_for(message.conversation_id)
        result = await self.gc_graph.ainvoke(
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
