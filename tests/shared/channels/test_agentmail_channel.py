"""Unit tests for AgentMailChannel.

Mocks ``AsyncAgentMail`` so no live AgentMail API is hit. Covers:

- ``AgentMailChannelSettings`` — env-var validation.
- ``AgentMailChannel._dispatch_event`` — MessageReceivedEvent routes to the
  inbound handler with a correctly-shaped InboundMessage; non-message events
  ignored; no-handler path logs warning.
- ``AgentMailChannel.post_message`` — calls ``inboxes.messages.reply`` with
  the most recent ``message_id`` for the thread; raises informatively if
  no inbound has been seen.
- The thread_id → message_id map updates correctly across multiple inbounds.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from agentmail.events import MessageReceivedEvent
from agentmail.messages.types.message import Message
from agentmail.threads.types.thread_item import ThreadItem
from agentmail.websockets import Subscribed

from shared.channels.agentmail.channel import AgentMailChannel
from shared.channels.agentmail.config import AgentMailChannelSettings
from shared.channels.base import InboundMessage


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


def _make_message(
    *,
    inbox_id: str = "ibx_test",
    thread_id: str = "th_001",
    message_id: str = "msg_001",
    from_: str = "alice@example.com",
    to: tuple[str, ...] = ("gc@oscar.mail",),
    subject: str = "Please review",
    text: str = "Hi GC, can you take a look at this NDA?",
    extracted_text: str | None = None,
) -> Message:
    """Construct a minimal valid AgentMail Message for tests."""
    now = datetime.now(timezone.utc)
    kwargs: dict = {
        "inbox_id": inbox_id,
        "thread_id": thread_id,
        "message_id": message_id,
        "labels": [],
        "timestamp": now,
        "from": from_,
        "to": list(to),
        "subject": subject,
        "text": text,
        "extracted_text": extracted_text if extracted_text is not None else text,
        "size": len(text),
        "updated_at": now,
        "created_at": now,
    }
    return Message(**kwargs)


def _make_thread_item(*, inbox_id: str, thread_id: str, last_message_id: str) -> ThreadItem:
    now = datetime.now(timezone.utc)
    return ThreadItem(
        inbox_id=inbox_id,
        thread_id=thread_id,
        labels=[],
        timestamp=now,
        senders=["alice@example.com"],
        recipients=["gc@oscar.mail"],
        subject="Please review",
        last_message_id=last_message_id,
        message_count=1,
        size=10,
        updated_at=now,
        created_at=now,
    )


def _make_message_received_event(message: Message) -> MessageReceivedEvent:
    thread = _make_thread_item(
        inbox_id=message.inbox_id,
        thread_id=message.thread_id,
        last_message_id=message.message_id,
    )
    return MessageReceivedEvent(
        type="event",
        event_type="message.received",
        event_id="evt_test",
        message=message,
        thread=thread,
    )


@pytest.fixture
def mock_client() -> AsyncMock:
    """AsyncMock standing in for AsyncAgentMail. ``inboxes.messages.reply``
    is reachable through nested AsyncMock attributes."""
    return AsyncMock()


@pytest.fixture
def channel(mock_client: AsyncMock) -> AgentMailChannel:
    return AgentMailChannel(
        api_key="am_test_key",
        inbox_id="ibx_test",
        client=mock_client,
    )


# ---------------------------------------------------------------------------
# AgentMailChannelSettings
# ---------------------------------------------------------------------------


class TestSettings:
    def test_constructs_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OSCAR_AGENTMAIL_API_KEY", "am_from_env")
        monkeypatch.setenv("OSCAR_AGENTMAIL_INBOX_ID", "ibx_from_env")
        s = AgentMailChannelSettings()
        assert s.api_key == "am_from_env"
        assert s.inbox_id == "ibx_from_env"

    def test_missing_env_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OSCAR_AGENTMAIL_API_KEY", raising=False)
        monkeypatch.delenv("OSCAR_AGENTMAIL_INBOX_ID", raising=False)
        with pytest.raises(Exception):
            AgentMailChannelSettings()


# ---------------------------------------------------------------------------
# _dispatch_event
# ---------------------------------------------------------------------------


class TestDispatchEvent:
    @pytest.mark.asyncio
    async def test_message_received_routes_to_handler(
        self, channel: AgentMailChannel
    ) -> None:
        received: list[InboundMessage] = []

        async def handler(msg: InboundMessage) -> None:
            received.append(msg)

        channel.on_inbound_message(handler)

        event = _make_message_received_event(_make_message())
        await channel._dispatch_event(event)

        assert len(received) == 1
        msg = received[0]
        assert msg.conversation_id == "th_001"
        assert msg.text == "Hi GC, can you take a look at this NDA?"
        assert msg.raw["thread_id"] == "th_001"
        assert msg.raw["message_id"] == "msg_001"

    @pytest.mark.asyncio
    async def test_extracted_text_preferred_over_text(
        self, channel: AgentMailChannel
    ) -> None:
        received: list[InboundMessage] = []

        async def handler(msg: InboundMessage) -> None:
            received.append(msg)

        channel.on_inbound_message(handler)

        event = _make_message_received_event(
            _make_message(
                text="raw with quoted-history >>",
                extracted_text="just the new content",
            )
        )
        await channel._dispatch_event(event)

        assert received[0].text == "just the new content"

    @pytest.mark.asyncio
    async def test_message_id_recorded_for_thread(
        self, channel: AgentMailChannel
    ) -> None:
        async def handler(msg: InboundMessage) -> None:
            pass

        channel.on_inbound_message(handler)

        # Two messages in the same thread; latest should win in the map.
        await channel._dispatch_event(
            _make_message_received_event(
                _make_message(message_id="msg_001", thread_id="th_X")
            )
        )
        await channel._dispatch_event(
            _make_message_received_event(
                _make_message(message_id="msg_002", thread_id="th_X")
            )
        )
        assert channel._last_message_id_by_thread["th_X"] == "msg_002"

    @pytest.mark.asyncio
    async def test_subscribed_ack_ignored(
        self, channel: AgentMailChannel
    ) -> None:
        received: list[InboundMessage] = []

        async def handler(msg: InboundMessage) -> None:
            received.append(msg)

        channel.on_inbound_message(handler)

        ack = Subscribed(
            type="subscribed",
            event_types=["message.received"],
            inbox_ids=["ibx_test"],
        )
        await channel._dispatch_event(ack)
        assert received == []

    @pytest.mark.asyncio
    async def test_non_message_received_events_ignored(
        self, channel: AgentMailChannel
    ) -> None:
        """The dispatch filter is purely an isinstance check on
        MessageReceivedEvent — any other shape (the SDK's other event
        types, an Error frame, or anything unexpected) silently no-ops.
        Phase 2B handles only inbound messages; out-of-scope events are
        Phase 3+ work."""
        received: list[InboundMessage] = []

        async def handler(msg: InboundMessage) -> None:
            received.append(msg)

        channel.on_inbound_message(handler)

        # Anything that isn't a MessageReceivedEvent should be ignored.
        await channel._dispatch_event(object())
        await channel._dispatch_event({"type": "unknown"})
        await channel._dispatch_event(None)
        assert received == []

    @pytest.mark.asyncio
    async def test_no_handler_logs_warning(
        self, channel: AgentMailChannel, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Don't register a handler.
        with caplog.at_level("WARNING", logger="shared.channels.agentmail.channel"):
            await channel._dispatch_event(
                _make_message_received_event(_make_message())
            )
        assert any(
            "before inbound handler" in rec.message for rec in caplog.records
        )


# ---------------------------------------------------------------------------
# post_message
# ---------------------------------------------------------------------------


class TestPostMessage:
    @pytest.mark.asyncio
    async def test_replies_to_recorded_message_id(
        self, channel: AgentMailChannel, mock_client: AsyncMock
    ) -> None:
        async def handler(msg: InboundMessage) -> None:
            pass

        channel.on_inbound_message(handler)
        await channel._dispatch_event(
            _make_message_received_event(
                _make_message(message_id="msg_inbound", thread_id="th_X")
            )
        )

        await channel.post_message(
            conversation_id="th_X", text="Here is my analysis."
        )

        mock_client.inboxes.messages.reply.assert_awaited_once_with(
            inbox_id="ibx_test",
            message_id="msg_inbound",
            text="Here is my analysis.",
        )

    @pytest.mark.asyncio
    async def test_uses_latest_message_id_after_multiple_inbounds(
        self, channel: AgentMailChannel, mock_client: AsyncMock
    ) -> None:
        async def handler(msg: InboundMessage) -> None:
            pass

        channel.on_inbound_message(handler)
        for mid in ["msg_a", "msg_b", "msg_c"]:
            await channel._dispatch_event(
                _make_message_received_event(
                    _make_message(message_id=mid, thread_id="th_X")
                )
            )

        await channel.post_message(conversation_id="th_X", text="reply")

        mock_client.inboxes.messages.reply.assert_awaited_once_with(
            inbox_id="ibx_test",
            message_id="msg_c",
            text="reply",
        )

    @pytest.mark.asyncio
    async def test_post_to_unknown_thread_raises(
        self, channel: AgentMailChannel, mock_client: AsyncMock
    ) -> None:
        with pytest.raises(RuntimeError, match="no inbound message_id"):
            await channel.post_message(
                conversation_id="th_unknown", text="hello"
            )
        mock_client.inboxes.messages.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_threads_isolated_in_message_id_map(
        self, channel: AgentMailChannel, mock_client: AsyncMock
    ) -> None:
        async def handler(msg: InboundMessage) -> None:
            pass

        channel.on_inbound_message(handler)
        await channel._dispatch_event(
            _make_message_received_event(
                _make_message(message_id="msg_X1", thread_id="th_X")
            )
        )
        await channel._dispatch_event(
            _make_message_received_event(
                _make_message(message_id="msg_Y1", thread_id="th_Y")
            )
        )

        await channel.post_message(conversation_id="th_X", text="x-reply")
        await channel.post_message(conversation_id="th_Y", text="y-reply")

        calls = mock_client.inboxes.messages.reply.await_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["message_id"] == "msg_X1"
        assert calls[1].kwargs["message_id"] == "msg_Y1"
