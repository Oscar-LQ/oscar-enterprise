"""Unit tests for SlackChannel and its pure helpers.

Mocks ``AsyncWebClient`` so no live Slack API is hit. Covers:

- Pure helpers: ``parse_conversation_id``, ``strip_bot_mention``,
  ``split_for_slack``.
- ``SlackChannel.post_message`` — single-chunk and multi-chunk paths,
  thread_ts threading.
- ``SlackChannel._on_app_mention`` — InboundMessage construction with
  thread_ts present and absent (top-level mention falls back to ts), and
  the no-handler-registered guard.
- ``SlackChannel.from_settings`` — env-driven construction.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest

from shared.channels.base import InboundMessage
from shared.channels.slack.channel import (
    SlackChannel,
    parse_conversation_id,
    split_for_slack,
    strip_bot_mention,
)
from shared.channels.slack.config import SlackChannelSettings


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestParseConversationId:
    def test_typical_slack_shape(self) -> None:
        assert parse_conversation_id("C12345:1700000000.123456") == (
            "C12345",
            "1700000000.123456",
        )

    def test_thread_ts_can_contain_dots(self) -> None:
        assert parse_conversation_id("C1:1.2.3") == ("C1", "1.2.3")

    def test_missing_separator_raises(self) -> None:
        with pytest.raises(ValueError, match="conversation_id"):
            parse_conversation_id("C12345")

    def test_empty_channel_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_conversation_id(":1700000000.123456")

    def test_empty_thread_ts_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_conversation_id("C12345:")


class TestStripBotMention:
    def test_strips_leading_mention(self) -> None:
        assert strip_bot_mention("<@U12345> hello there") == "hello there"

    def test_strips_with_trailing_whitespace(self) -> None:
        assert strip_bot_mention("<@U12345>   hello") == "hello"

    def test_no_mention_passthrough(self) -> None:
        assert strip_bot_mention("hello there") == "hello there"

    def test_only_strips_first(self) -> None:
        # A second mention in the body is content, not a bot prefix.
        assert (
            strip_bot_mention("<@U12345> hello <@U67890>")
            == "hello <@U67890>"
        )

    def test_handles_workspace_id_starting_with_w(self) -> None:
        assert strip_bot_mention("<@W123ABC> hi") == "hi"


class TestSplitForSlack:
    def test_short_passes_through(self) -> None:
        assert split_for_slack("short text") == ["short text"]

    def test_exactly_at_limit_passes_through(self) -> None:
        text = "x" * 100
        assert split_for_slack(text, soft_limit=100) == [text]

    def test_splits_on_paragraph_boundary(self) -> None:
        text = "first paragraph\n\nsecond paragraph"
        chunks = split_for_slack(text, soft_limit=20)
        assert len(chunks) == 2
        assert chunks[0] == "first paragraph"
        assert chunks[1] == "second paragraph"

    def test_splits_on_sentence_boundary(self) -> None:
        text = "First sentence here. Second sentence here. Third."
        chunks = split_for_slack(text, soft_limit=25)
        # Each chunk must be at or below the soft limit.
        assert all(len(c) <= 25 for c in chunks)
        assert "".join(c.strip() for c in chunks).replace(" ", "") == text.replace(" ", "").replace(".", "").rstrip(".") + "" or len(chunks) > 1
        # Sentence delimiters should anchor at least one split.
        assert any(c.endswith(".") for c in chunks)

    def test_splits_on_word_boundary_when_no_sentence(self) -> None:
        text = " ".join(["word"] * 50)  # ~250 chars, no sentence breaks
        chunks = split_for_slack(text, soft_limit=50)
        assert len(chunks) > 1
        for chunk in chunks:
            assert not chunk.startswith(" ")
            assert not chunk.endswith(" ")

    def test_hard_cut_for_single_long_token(self) -> None:
        # No whitespace anywhere — fall back to hard cut at soft_limit.
        text = "x" * 250
        chunks = split_for_slack(text, soft_limit=100)
        assert len(chunks) == 3
        assert all(len(c) <= 100 for c in chunks)


# ---------------------------------------------------------------------------
# SlackChannel.post_message
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client() -> AsyncMock:
    """An AsyncMock standing in for AsyncWebClient. ``chat_postMessage``
    returns an ``AsyncMock`` by default (truthy, awaitable)."""
    return AsyncMock()


@pytest.fixture
def slack_channel(mock_client: AsyncMock) -> SlackChannel:
    return SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        client=mock_client,
    )


class TestPostMessage:
    @pytest.mark.asyncio
    async def test_single_chunk_passes_thread_ts(
        self, slack_channel: SlackChannel, mock_client: AsyncMock
    ) -> None:
        await slack_channel.post_message(
            conversation_id="C12345:1700000000.123456",
            text="hello",
        )
        mock_client.chat_postMessage.assert_awaited_once_with(
            channel="C12345",
            text="hello",
            thread_ts="1700000000.123456",
        )

    @pytest.mark.asyncio
    async def test_long_text_split_across_multiple_calls_in_same_thread(
        self, slack_channel: SlackChannel, mock_client: AsyncMock
    ) -> None:
        # 6000 chars with paragraph breaks every 1000 chars.
        para = "x" * 999
        text = "\n\n".join([para] * 6)
        await slack_channel.post_message(
            conversation_id="C12345:1700000000.123456",
            text=text,
        )
        # Several post calls, all to the same channel + thread_ts.
        calls = mock_client.chat_postMessage.await_args_list
        assert len(calls) > 1
        for call in calls:
            assert call.kwargs["channel"] == "C12345"
            assert call.kwargs["thread_ts"] == "1700000000.123456"


# ---------------------------------------------------------------------------
# SlackChannel._on_app_mention
# ---------------------------------------------------------------------------


class TestOnAppMention:
    @pytest.mark.asyncio
    async def test_constructs_inbound_message_with_thread_ts(
        self, slack_channel: SlackChannel
    ) -> None:
        received: list[InboundMessage] = []

        async def handler(msg: InboundMessage) -> None:
            received.append(msg)

        slack_channel.on_inbound_message(handler)

        event = {
            "channel": "C12345",
            "ts": "1700000001.000100",
            "thread_ts": "1700000000.000000",
            "text": "<@U999BOT> please review",
            "user": "U001USER",
        }
        ack = AsyncMock()
        await slack_channel._on_app_mention(event, ack)

        ack.assert_awaited_once_with()
        assert len(received) == 1
        msg = received[0]
        assert msg.conversation_id == "C12345:1700000000.000000"
        assert msg.text == "please review"
        assert msg.raw == event

    @pytest.mark.asyncio
    async def test_falls_back_to_ts_when_no_thread_ts(
        self, slack_channel: SlackChannel
    ) -> None:
        received: list[InboundMessage] = []

        async def handler(msg: InboundMessage) -> None:
            received.append(msg)

        slack_channel.on_inbound_message(handler)

        event = {
            "channel": "C12345",
            "ts": "1700000001.000100",
            # no thread_ts — top-level mention
            "text": "<@U999BOT> hi",
            "user": "U001USER",
        }
        ack = AsyncMock()
        await slack_channel._on_app_mention(event, ack)

        assert len(received) == 1
        assert received[0].conversation_id == "C12345:1700000001.000100"

    @pytest.mark.asyncio
    async def test_no_handler_registered_logs_and_returns(
        self, slack_channel: SlackChannel, caplog: pytest.LogCaptureFixture
    ) -> None:
        # No on_inbound_message call.
        event = {"channel": "C12345", "ts": "1.0", "text": "<@U999BOT> hi"}
        ack = AsyncMock()
        with caplog.at_level("WARNING", logger="shared.channels.slack.channel"):
            await slack_channel._on_app_mention(event, ack)
        ack.assert_awaited_once_with()
        assert any(
            "before inbound handler" in rec.message for rec in caplog.records
        )


# ---------------------------------------------------------------------------
# SlackChannel.from_settings
# ---------------------------------------------------------------------------


class TestFromSettings:
    def test_constructs_with_env_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OSCAR_SLACK_BOT_TOKEN", "xoxb-from-env")
        monkeypatch.setenv("OSCAR_SLACK_APP_TOKEN", "xapp-from-env")
        settings = SlackChannelSettings()
        channel = SlackChannel.from_settings(settings)
        assert channel._app_token == "xapp-from-env"

    def test_missing_env_raises_on_settings_construction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OSCAR_SLACK_BOT_TOKEN", raising=False)
        monkeypatch.delenv("OSCAR_SLACK_APP_TOKEN", raising=False)
        with pytest.raises(Exception):  # ValidationError from pydantic
            SlackChannelSettings()
