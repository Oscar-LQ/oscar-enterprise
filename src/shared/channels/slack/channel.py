"""SlackChannel — Channel Protocol over slack-bolt Socket Mode."""
from __future__ import annotations

import logging
import re
from typing import Any

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from shared.channels.base import Channel, InboundHandler, InboundMessage
from shared.channels.slack.config import SlackChannelSettings


_logger = logging.getLogger(__name__)

_CONVERSATION_ID_SEP = ":"
_BOT_MENTION_RE = re.compile(r"^<@[A-Z0-9]+>\s*")

# Slack hard-caps chat.postMessage at 40000 chars; readability suffers well
# below that. ~2500 chars is one comfortable mobile-screen scroll.
_LONG_MESSAGE_SOFT_LIMIT = 2500


class SlackChannel:
    """Channel implementation over slack-bolt's async API in Socket Mode.

    Subscribes to ``app_mention`` only. Posts replies via
    ``chat.postMessage`` with ``thread_ts`` so the conversation stays in
    the originating thread. Long replies are split on paragraph /
    sentence / word boundaries and posted as multiple messages in the
    same thread (Phase 1 review flag — readability degrades above ~2-3k
    chars).
    """

    def __init__(
        self,
        *,
        bot_token: str,
        app_token: str,
        client: AsyncWebClient | None = None,
    ) -> None:
        self._app_token = app_token
        self._app = AsyncApp(token=bot_token, signing_secret="unused-socket-mode")
        # Outbound posts go through `self._client`. Defaults to the
        # AsyncApp-managed AsyncWebClient (which uses `bot_token`); tests
        # inject an AsyncMock here. Kept separate from `self._app.client`
        # because AsyncApp validates `isinstance(client, AsyncWebClient)`
        # in its own __init__, which an AsyncMock fails.
        self._client = client if client is not None else self._app.client
        self._handler: AsyncSocketModeHandler | None = None
        self._inbound: InboundHandler | None = None
        self._app.event("app_mention")(self._on_app_mention)

    @classmethod
    def from_settings(cls, settings: SlackChannelSettings) -> "SlackChannel":
        return cls(
            bot_token=settings.bot_token,
            app_token=settings.app_token,
        )

    async def start(self) -> None:
        """Open the Socket Mode connection and return once connected.
        The underlying ``AsyncSocketModeHandler`` keeps the WebSocket
        running on its own background task."""
        self._handler = AsyncSocketModeHandler(self._app, self._app_token)
        await self._handler.connect_async()

    async def stop(self) -> None:
        """Close the Socket Mode connection. Idempotent."""
        if self._handler is None:
            return
        await self._handler.close_async()
        self._handler = None

    async def post_message(self, *, conversation_id: str, text: str) -> None:
        channel, thread_ts = parse_conversation_id(conversation_id)
        for chunk in split_for_slack(text):
            await self._client.chat_postMessage(
                channel=channel,
                text=chunk,
                thread_ts=thread_ts,
            )

    def on_inbound_message(self, handler: InboundHandler) -> None:
        self._inbound = handler

    async def _on_app_mention(
        self,
        event: dict[str, Any],
        ack: Any,
    ) -> None:
        """slack-bolt event handler — invoked by AsyncApp for each
        app_mention. Acknowledges immediately (Slack expects ack within 3
        seconds for Socket Mode events), then routes to the dispatcher's
        registered handler."""
        await ack()
        if self._inbound is None:
            _logger.warning(
                "slack: app_mention received before inbound handler "
                "registered; channel=%s ts=%s",
                event.get("channel"),
                event.get("ts"),
            )
            return
        text = strip_bot_mention(event.get("text", ""))
        channel = event["channel"]
        thread_ts = event.get("thread_ts") or event["ts"]
        message = InboundMessage(
            conversation_id=f"{channel}{_CONVERSATION_ID_SEP}{thread_ts}",
            text=text,
            raw=dict(event),
        )
        await self._inbound(message)


# ---------------------------------------------------------------------------
# Pure helpers (module-level for testability)
# ---------------------------------------------------------------------------


def parse_conversation_id(conversation_id: str) -> tuple[str, str]:
    """Split ``"<channel>:<thread_ts>"`` back into its parts.

    Raises:
        ValueError: if the id does not contain the separator. The
            dispatcher only ever sees conversation_ids constructed by
            this module, so a malformed id surfaces a wiring bug rather
            than user input.
    """
    parts = conversation_id.split(_CONVERSATION_ID_SEP, 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(
            f"slack: conversation_id {conversation_id!r} does not match "
            f"the expected 'channel:thread_ts' shape constructed by "
            f"SlackChannel from app_mention events."
        )
    return parts[0], parts[1]


def strip_bot_mention(text: str) -> str:
    """Remove a leading ``<@BOTID>`` prefix and any whitespace after it."""
    return _BOT_MENTION_RE.sub("", text, count=1)


def split_for_slack(
    text: str,
    *,
    soft_limit: int = _LONG_MESSAGE_SOFT_LIMIT,
) -> list[str]:
    """Split ``text`` so each chunk is at most ``soft_limit`` characters.

    Prefers paragraph breaks (``\\n\\n``), then sentence breaks
    (``". "``), then word boundaries (`` ``); falls back to a hard cut
    at the limit when no whitespace is reachable in the back half of the
    window.

    Returns ``[text]`` when ``len(text) <= soft_limit``.
    """
    if len(text) <= soft_limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > soft_limit:
        break_at = _find_break(remaining, soft_limit)
        chunks.append(remaining[:break_at].rstrip())
        remaining = remaining[break_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _find_break(text: str, soft_limit: int) -> int:
    """Locate the best break point at or before ``soft_limit``."""
    paragraph = text.rfind("\n\n", 0, soft_limit)
    if paragraph != -1:
        return paragraph
    sentence = text.rfind(". ", 0, soft_limit)
    if sentence != -1:
        return sentence + 1  # include the period
    word = text.rfind(" ", 0, soft_limit)
    if word != -1 and word >= soft_limit // 2:
        return word
    return soft_limit  # hard cut — preserves single very-long token
