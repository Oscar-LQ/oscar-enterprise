"""Oscar Enterprise runtime entry point.

Wires the channel layer, the General Counsel Deep Agent, and the
dispatcher into a long-running async process. Started inside the
``oscar-dev`` OpenShell sandbox.

Order of operations is load-bearing:
  1. ``load_host_secrets()`` populates ``os.environ`` from
     ``/etc/oscar/oscar.env`` (ADR 025) BEFORE any
     ``BaseSettings`` / ``get_chat_model`` call reads from the
     environment. Any future caller that constructs settings at module
     import time would race the loader; ``run()`` therefore takes
     factories that defer construction until after the loader has run.
  2. Channel and GC graph are built. AgentMail is deferred — its
     credentials are not yet provisioned in ``/etc/oscar/oscar.env``,
     so constructing ``AgentMailChannelSettings()`` would raise
     ``ValidationError`` at startup. Re-enable in a future sprint
     once ``OSCAR_AGENTMAIL_API_KEY`` and ``OSCAR_AGENTMAIL_INBOX_ID``
     are populated; see the commented-out block below.
  3. Dispatcher is wired as the channel's inbound handler.
  4. Channel is started; the underlying transport runs on its own
     background task. The runtime then blocks on a stop event.
  5. SIGTERM / SIGINT set the stop event; the channel is stopped
     under a 25-second timeout (sized below the Kubernetes default
     ``terminationGracePeriodSeconds: 30`` to keep SIGKILL from racing
     the graceful path).
"""
from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable

from shared.agents.general_counsel import build_general_counsel
from shared.channels.base import Channel
from shared.channels.slack.channel import SlackChannel
from shared.channels.slack.config import SlackChannelSettings
from shared.dispatcher import Dispatcher, Graph
from shared.secrets import load_host_secrets

_logger = logging.getLogger(__name__)

# Sized below Kubernetes' default ``terminationGracePeriodSeconds: 30``
# so the graceful path completes before SIGKILL fires.
_DEFAULT_STOP_TIMEOUT_SECS = 25.0

ChannelFactory = Callable[[], Channel]
GraphFactory = Callable[[], Graph]
SecretsLoader = Callable[[], int]


def _build_slack_channel() -> Channel:
    """Construct ``SlackChannel`` from process environment.

    ``SlackChannelSettings()`` is what reads the ``OSCAR_SLACK_*`` env
    vars; ``load_host_secrets()`` must have run before this is called.
    """
    return SlackChannel.from_settings(SlackChannelSettings())


# AgentMail channel — DEFERRED to a future sprint.
#
# AgentMailChannelSettings() validates OSCAR_AGENTMAIL_API_KEY and
# OSCAR_AGENTMAIL_INBOX_ID at construction time. Those values are not
# yet present in /etc/oscar/oscar.env (per the M2 handover, AgentMail
# credential provisioning is post-M2 work). Constructing the channel
# here would crash the runtime at startup with a pydantic
# ValidationError before Slack ever connects.
#
# To re-enable: uncomment the imports + factory + the gather() entry in
# run() once the two env vars are populated on the host.
#
# from shared.channels.agentmail.channel import AgentMailChannel
# from shared.channels.agentmail.config import AgentMailChannelSettings
#
# def _build_agentmail_channel() -> Channel:
#     return AgentMailChannel.from_settings(AgentMailChannelSettings())


async def run(
    *,
    secrets_loader: SecretsLoader = load_host_secrets,
    channel_factory: ChannelFactory = _build_slack_channel,
    graph_factory: GraphFactory = build_general_counsel,
    stop_timeout_secs: float = _DEFAULT_STOP_TIMEOUT_SECS,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Runtime orchestration.

    Args:
        secrets_loader: Populates ``os.environ`` from the host secrets
            file. Invoked first; any subsequent ``BaseSettings``
            construction sees the populated environment.
        channel_factory: Constructs the inbound/outbound ``Channel``.
            Default builds ``SlackChannel`` from
            ``SlackChannelSettings()``. Tests inject a ``FakeChannel``.
        graph_factory: Constructs the GC graph. Default
            ``build_general_counsel()`` (env-driven model + in-process
            ``MemorySaver``).
        stop_timeout_secs: Upper bound on ``channel.stop()`` after a
            stop signal. If exceeded, the runtime exits with an error
            log rather than blocking past Kubernetes' grace period.
        stop_event: Test seam. Default ``None`` causes ``run()`` to
            create a fresh ``Event`` and wire SIGTERM + SIGINT to it.
            Tests pass a pre-created ``Event`` to drive the lifecycle
            without delivering real OS signals.
    """
    secrets_loader()

    channel = channel_factory()
    graph = graph_factory()
    dispatcher = Dispatcher(channel=channel, gc_graph=graph)
    channel.on_inbound_message(dispatcher.handle)

    if stop_event is None:
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)

    await channel.start()
    _logger.info(
        "oscar runtime: channel started, awaiting inbound messages"
    )

    try:
        await stop_event.wait()
    finally:
        _logger.info("oscar runtime: stop signal received, draining")
        try:
            await asyncio.wait_for(
                channel.stop(), timeout=stop_timeout_secs
            )
            _logger.info("oscar runtime: channel stopped cleanly")
        except asyncio.TimeoutError:
            _logger.error(
                "oscar runtime: channel.stop() exceeded %.1fs timeout; "
                "exiting without clean drain to avoid SIGKILL race",
                stop_timeout_secs,
            )


def main() -> None:
    """Synchronous entry point. Configures logging then runs the
    async orchestration."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()
