"""AgentMailChannel — Channel Protocol over the agentmail Python SDK."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from agentmail import AsyncAgentMail
from agentmail.events import MessageReceivedEvent
from agentmail.messages.types.message import Message
from agentmail.websockets import Subscribe

from shared.channels.base import Channel, InboundHandler, InboundMessage
from shared.channels.agentmail.config import AgentMailChannelSettings


_logger = logging.getLogger(__name__)

_RECONNECT_BACKOFF_SECONDS = 5.0
_FIRST_CONNECT_TIMEOUT_SECONDS = 30.0
_SUBSCRIBE_EVENT_TYPES: list[str] = ["message.received"]


class AgentMailChannel:
    """Channel implementation over the agentmail SDK.

    Inbound: long-running WebSocket subscription to the configured
    inbox's ``message.received`` events. The listen loop reconnects with
    backoff on disconnect. Outbound: ``inboxes.messages.reply(...)`` REST
    call against the most recent message_id seen in the target thread,
    so email clients thread the reply correctly via in-reply-to /
    references headers that AgentMail sets server-side.

    The thread_id → message_id map is in-memory (lifetime of the runtime
    process). On runtime restart, the channel re-receives any pending
    messages over the WebSocket on reconnection (AgentMail server
    semantics), so the map repopulates organically.
    """

    def __init__(
        self,
        *,
        api_key: str,
        inbox_id: str,
        client: AsyncAgentMail | None = None,
    ) -> None:
        self._api_key = api_key
        self._inbox_id = inbox_id
        self._client = (
            client if client is not None else AsyncAgentMail(api_key=api_key)
        )
        self._inbound: InboundHandler | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._ready_event = asyncio.Event()
        # thread_id → message_id of the most recent inbound message in
        # that thread. Used by post_message to call reply() correctly.
        self._last_message_id_by_thread: dict[str, str] = {}

    @classmethod
    def from_settings(cls, settings: AgentMailChannelSettings) -> "AgentMailChannel":
        return cls(api_key=settings.api_key, inbox_id=settings.inbox_id)

    async def start(self) -> None:
        """Open the WebSocket subscription and return once subscribed.

        The listen loop runs as a background task for the lifetime of
        the channel; on disconnect it reconnects with backoff. ``stop()``
        cancels the task.
        """
        if self._listen_task is not None:
            return
        self._stop_event.clear()
        self._ready_event.clear()
        self._listen_task = asyncio.create_task(self._listen_loop())
        try:
            await asyncio.wait_for(
                self._ready_event.wait(),
                timeout=_FIRST_CONNECT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            await self.stop()
            raise RuntimeError(
                f"agentmail: WebSocket subscription did not become ready "
                f"within {_FIRST_CONNECT_TIMEOUT_SECONDS}s — check API "
                f"key, inbox id, and network policy egress to "
                f"ws.agentmail.to."
            )

    async def stop(self) -> None:
        """Cancel the listen loop. Idempotent."""
        self._stop_event.set()
        if self._listen_task is None:
            return
        self._listen_task.cancel()
        try:
            await self._listen_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            _logger.warning("agentmail: listen task exited with: %s", exc)
        self._listen_task = None

    async def post_message(self, *, conversation_id: str, text: str) -> None:
        """Reply to the most recent inbound in the thread."""
        thread_id = conversation_id
        message_id = self._last_message_id_by_thread.get(thread_id)
        if message_id is None:
            raise RuntimeError(
                f"agentmail: cannot post to thread_id={thread_id!r} — no "
                f"inbound message_id recorded for this thread in this "
                f"runtime process. The dispatcher should only post in "
                f"response to an inbound, which always populates the map."
            )
        await self._client.inboxes.messages.reply(
            inbox_id=self._inbox_id,
            message_id=message_id,
            text=text,
        )

    def on_inbound_message(self, handler: InboundHandler) -> None:
        self._inbound = handler

    # ------------------------------------------------------------------
    # Internal — listen loop and event dispatch
    # ------------------------------------------------------------------

    async def _listen_loop(self) -> None:
        """Connect → subscribe → consume events. Reconnect on disconnect."""
        while not self._stop_event.is_set():
            try:
                async with self._client.websockets.connect(
                    api_key=self._api_key
                ) as socket:
                    await socket.send_subscribe(
                        Subscribe(
                            type="subscribe",
                            inbox_ids=[self._inbox_id],
                            event_types=_SUBSCRIBE_EVENT_TYPES,
                        )
                    )
                    self._ready_event.set()
                    async for event in socket:
                        if self._stop_event.is_set():
                            break
                        await self._dispatch_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _logger.error(
                    "agentmail: listen loop error: %s; reconnecting in %.1fs",
                    exc,
                    _RECONNECT_BACKOFF_SECONDS,
                )
                self._ready_event.clear()
                await asyncio.sleep(_RECONNECT_BACKOFF_SECONDS)

    async def _dispatch_event(self, event: Any) -> None:
        """Handle one event from the WebSocket. Only ``message.received``
        events route to the inbound handler; other events (Subscribed
        ack, message.sent, message.delivered, errors, etc.) are
        ignored."""
        if not isinstance(event, MessageReceivedEvent):
            return
        msg = event.message
        self._last_message_id_by_thread[msg.thread_id] = msg.message_id
        if self._inbound is None:
            _logger.warning(
                "agentmail: message.received before inbound handler "
                "registered; thread_id=%s message_id=%s",
                msg.thread_id,
                msg.message_id,
            )
            return
        await self._inbound(_inbound_message_from(msg))


def _inbound_message_from(msg: Message) -> InboundMessage:
    """Project an AgentMail ``Message`` into the channel-agnostic
    ``InboundMessage`` shape."""
    text = msg.extracted_text or msg.text or msg.preview or ""
    return InboundMessage(
        conversation_id=msg.thread_id,
        text=text.strip(),
        raw=msg.model_dump(),
    )


# Load-time Channel Protocol conformance assertion (matches the pattern in
# fake.py; AgentMailChannel needs credentials to construct so we use __new__
# to bypass __init__ — runtime_checkable Protocol checks for method presence
# on the instance, which class-level methods satisfy).
assert isinstance(AgentMailChannel.__new__(AgentMailChannel), Channel), (
    "AgentMailChannel does not implement the Channel Protocol; "
    "check that start, stop, post_message, on_inbound_message all exist."
)
