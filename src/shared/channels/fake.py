"""In-memory FakeChannel for unit and integration tests.

No external I/O. Tests drive inbound messages with ``simulate_inbound()``
and assert against ``posted_messages`` after the dispatcher (or other
handler) has run. The class shape mirrors the production Channel
implementations so swapping FakeChannel for SlackChannel / AgentMailChannel
in a runbook test (docs/operations/runbook-channel-switch.md) is one line.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shared.channels.base import Channel, InboundHandler, InboundMessage


@dataclass(frozen=True)
class PostedMessage:
    """Outbound message recorded by FakeChannel.post_message."""

    conversation_id: str
    text: str


@dataclass
class FakeChannel:
    """Channel implementation backed by in-process state.

    Conforms to the ``Channel`` Protocol. ``simulate_inbound()`` is a
    test-only affordance for triggering the registered handler with a
    crafted ``InboundMessage``.
    """

    posted_messages: list[PostedMessage] = field(default_factory=list)
    _handler: InboundHandler | None = None
    _started: bool = False

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def post_message(self, *, conversation_id: str, text: str) -> None:
        self.posted_messages.append(
            PostedMessage(conversation_id=conversation_id, text=text)
        )

    def on_inbound_message(self, handler: InboundHandler) -> None:
        self._handler = handler

    async def simulate_inbound(self, message: InboundMessage) -> None:
        """Drive the registered handler with `message`. Raises if no
        handler is registered — surfaces wiring bugs in tests."""
        if self._handler is None:
            raise RuntimeError(
                "FakeChannel.simulate_inbound called before "
                "on_inbound_message registered a handler."
            )
        await self._handler(message)


# Static check: FakeChannel matches the Channel Protocol surface.
_: Channel = FakeChannel()
