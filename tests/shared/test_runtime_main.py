"""Runtime entry-point wiring tests against ``FakeChannel`` + a stub Graph.

Covers the directives the M2 spec / handover lists for Phase 3:

  1. ``load_host_secrets()`` is called before any factory that constructs
     a ``BaseSettings`` (i.e. before channel/graph construction).
  2. The dispatcher is registered as the channel's inbound handler and
     the channel is started.
  3. A real round-trip happens through the dispatcher when an inbound
     message arrives after the runtime is up.
  4. Setting the stop event causes ``channel.stop()`` to be called and
     ``run()`` to return cleanly.
  5. A hung ``channel.stop()`` does not block past the configured
     timeout — the runtime logs and exits so SIGKILL doesn't race the
     graceful path.

No live Slack, no live LLM, no signal handlers (tests pass a pre-created
``stop_event`` to bypass the OS-signal wiring).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from shared.channels.base import InboundMessage
from shared.channels.fake import FakeChannel
from shared.runtime.main import run


@dataclass
class StubGraph:
    """Minimal Graph stand-in. Returns a canned AIMessage on ``ainvoke``.

    Mirrors the StubGraph in ``test_dispatcher.py`` so the runtime test
    exercises the same dispatcher contract.
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
        return {"messages": [AIMessage(self.reply)]}


@pytest.mark.asyncio
async def test_run_loads_secrets_before_constructing_factories() -> None:
    """Directive 1: secrets loader runs before channel factory.

    Settings classes (``SlackChannelSettings``, ``AgentMailChannelSettings``,
    and any future ``OSCAR_*`` ``BaseSettings``) read env vars at
    instance construction time. If a factory ran before the loader, it
    would see the un-populated environment and raise ``ValidationError``.

    Note (M3 reshape, ADR 028): the agent factory is now per-invocation,
    not constructed at startup, so it is not part of the startup call
    order. Its env-var reads happen on ``dispatcher.handle()`` —
    whenever the secrets loader has long since run.
    """
    call_order: list[str] = []

    def secrets_loader() -> int:
        call_order.append("secrets")
        return 0

    def channel_factory() -> FakeChannel:
        call_order.append("channel")
        return FakeChannel()

    stop_event = asyncio.Event()
    stop_event.set()  # exit immediately after start

    await run(
        secrets_loader=secrets_loader,
        channel_factory=channel_factory,
        agent_factory=lambda _cb: StubGraph(),
        stop_event=stop_event,
    )

    assert call_order == ["secrets", "channel"], (
        f"expected secrets→channel, got {call_order!r}"
    )


@pytest.mark.asyncio
async def test_run_registers_dispatcher_and_starts_channel() -> None:
    """Directive 2: after run() reaches the wait, the channel has been
    started and an inbound handler is registered."""
    channel = FakeChannel()
    stop_event = asyncio.Event()

    async def driver() -> None:
        # Wait until run() has called channel.start()
        while not channel._started:
            await asyncio.sleep(0)
        # Channel is up — handler must be registered for the dispatcher
        # to route messages
        assert channel._handler is not None
        stop_event.set()

    await asyncio.gather(
        run(
            secrets_loader=lambda: 0,
            channel_factory=lambda: channel,
            agent_factory=lambda _cb: StubGraph(),
            stop_event=stop_event,
        ),
        driver(),
    )


@pytest.mark.asyncio
async def test_run_round_trips_inbound_message_through_dispatcher() -> None:
    """Directive 3: a message simulated on the channel after start
    flows through the dispatcher to the graph and the reply lands back
    on the originating conversation_id."""
    channel = FakeChannel()
    graph = StubGraph(reply="hello back")
    stop_event = asyncio.Event()

    async def driver() -> None:
        while not channel._started:
            await asyncio.sleep(0)
        await channel.simulate_inbound(
            InboundMessage(conversation_id="C1:T1", text="hi")
        )
        stop_event.set()

    await asyncio.gather(
        run(
            secrets_loader=lambda: 0,
            channel_factory=lambda: channel,
            agent_factory=lambda _cb: graph,
            stop_event=stop_event,
        ),
        driver(),
    )

    assert len(graph.calls) == 1
    assert len(channel.posted_messages) == 1
    assert channel.posted_messages[0].conversation_id == "C1:T1"
    assert channel.posted_messages[0].text == "hello back"


@pytest.mark.asyncio
async def test_run_stops_channel_on_stop_event() -> None:
    """Directive 4: setting the stop event causes channel.stop() and a
    clean ``run()`` return."""
    channel = FakeChannel()
    stop_event = asyncio.Event()
    stop_event.set()

    await run(
        secrets_loader=lambda: 0,
        channel_factory=lambda: channel,
        agent_factory=lambda _cb: StubGraph(),
        stop_event=stop_event,
    )

    # FakeChannel.stop() flips _started back to False
    assert channel._started is False


@pytest.mark.asyncio
async def test_run_does_not_hang_when_stop_exceeds_timeout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Directive 5: a hung channel.stop() does not block past the
    configured timeout; the runtime logs and returns. Sized below
    Kubernetes' 30s grace period in production; here we use 0.05s for
    fast tests."""

    class HangingChannel:
        """Channel whose stop() blocks indefinitely. Conforms to the
        Channel Protocol surface."""

        def __init__(self) -> None:
            self._handler = None

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            await asyncio.Event().wait()  # forever

        async def post_message(
            self, *, conversation_id: str, text: str
        ) -> None:
            return None

        def on_inbound_message(self, handler: Any) -> None:
            self._handler = handler

    stop_event = asyncio.Event()
    stop_event.set()

    with caplog.at_level(logging.ERROR, logger="shared.runtime.main"):
        # If the timeout is not respected, this awaitable hangs. Wrap
        # in a generous outer wait_for so a regression fails the test
        # within the test process rather than wedging pytest.
        await asyncio.wait_for(
            run(
                secrets_loader=lambda: 0,
                channel_factory=lambda: HangingChannel(),
                agent_factory=lambda _cb: StubGraph(),
                stop_timeout_secs=0.05,
                stop_event=stop_event,
            ),
            timeout=2.0,
        )

    assert any(
        "exceeded" in record.message and "timeout" in record.message
        for record in caplog.records
    ), f"expected timeout-exceeded log, got {[r.message for r in caplog.records]!r}"
