"""Channel Protocol + InboundMessage dataclass."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class InboundMessage:
    """A user message arriving from a channel.

    `conversation_id` is the channel-specific stable identifier the
    dispatcher maps to a LangGraph `thread_id` so multi-turn memory
    persists for the same conversation across invocations (ADR 023).

    `raw` carries the unmodified channel-specific payload so future
    enrichment (audit logs, header extraction, attachment handling) does
    not require changing the Protocol.
    """

    conversation_id: str
    text: str
    raw: dict[str, Any] = field(default_factory=dict)


InboundHandler = Callable[[InboundMessage], Awaitable[None]]


@runtime_checkable
class Channel(Protocol):
    """Channel I/O surface.

    Async throughout because the Phase 2 channels (slack-bolt Socket Mode,
    AgentMail WebSocket) are inherently async I/O. Sync-only callers wrap
    in ``asyncio.run(...)``.
    """

    async def start(self) -> None:
        """Open the connection and return once ready to receive inbound
        messages and accept outbound posts. The implementation manages
        any background task it needs to keep the connection alive."""

    async def stop(self) -> None:
        """Close the connection. Idempotent — safe to call when already
        stopped."""

    async def post_message(self, *, conversation_id: str, text: str) -> None:
        """Post `text` into the conversation identified by
        `conversation_id`. The channel parses the id back into whatever
        shape its provider needs (e.g. Slack channel + thread_ts)."""

    async def post_progress(self, *, conversation_id: str, text: str) -> None:
        """Post a progress-narration update into the same conversation.

        Distinguished from ``post_message`` so channels with a more
        idiomatic surface for status updates (e.g. Slack reactions,
        ephemeral messages) can override; the default for Slack is
        identical to ``post_message`` (a threaded reply). The dispatcher
        binds this per-invocation to a callback the redline tool can
        await at well-defined milestones — see ADR 028.
        """

    def on_inbound_message(self, handler: InboundHandler) -> None:
        """Register the dispatcher's handler. Called once before
        ``start()``; replacing the handler after ``start()`` is not
        supported in Phase 1."""
