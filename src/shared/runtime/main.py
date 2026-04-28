"""Oscar Enterprise runtime entry point.

Wires the channel layer, the LangChain orchestrator (Oscar — ADR 026),
the redline tool (ADR 027), and the dispatcher (ADR 023, reshape per
ADR 028) into a long-running async process. Started inside the
``oscar-dev`` OpenShell sandbox.

Order of operations is load-bearing:
  1. ``load_host_secrets()`` populates ``os.environ`` from
     ``/etc/oscar/oscar.env`` (ADR 025) BEFORE any
     ``BaseSettings`` / ``get_chat_model`` call reads from the
     environment. Any future caller that constructs settings at module
     import time would race the loader; ``run()`` therefore takes
     factories that defer construction until after the loader has run.
  2. Channel and the agent factory are built. AgentMail is deferred
     pending credentials in ``/etc/oscar/oscar.env``; see commented-
     out block below.
  3. Dispatcher is wired as the channel's inbound handler. The
     dispatcher rebuilds the agent per-invocation by calling the
     supplied factory with a Slack-thread-scoped progress callback —
     this is the M3 reshape from a static ``gc_graph`` to a
     ``agent_factory`` closure (ADR 028).
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

from langgraph.checkpoint.memory import MemorySaver

from redline.tools._paths import (
    DEFAULT_NDA_INPUT,
    DEFAULT_NDA_ORIGINAL,
    DEFAULT_NDA_OUTPUT,
)
from redline.tools.redline import build_redline_tool
from shared.agents.orchestrator import build_orchestrator
from shared.channels.base import Channel
from shared.channels.slack.channel import SlackChannel
from shared.channels.slack.config import SlackChannelSettings
from shared.dispatcher import AgentFactory, Dispatcher, Graph, ProgressCallback
from shared.secrets import load_host_secrets

_logger = logging.getLogger(__name__)

# Sized below Kubernetes' default ``terminationGracePeriodSeconds: 30``
# so the graceful path completes before SIGKILL fires.
_DEFAULT_STOP_TIMEOUT_SECS = 25.0

ChannelFactory = Callable[[], Channel]
SecretsLoader = Callable[[], int]


def _build_slack_channel() -> Channel:
    """Construct ``SlackChannel`` from process environment.

    ``SlackChannelSettings()`` is what reads the ``OSCAR_SLACK_*`` env
    vars; ``load_host_secrets()`` must have run before this is called.
    """
    return SlackChannel.from_settings(SlackChannelSettings())


def _build_default_agent_factory() -> AgentFactory:
    """Construct the M3 default agent factory.

    Closes over a single shared :class:`MemorySaver` so per-conversation
    memory persists across the per-invocation agent rebuilds the
    dispatcher does (ADR 028). Returns a callable the dispatcher invokes
    with a Slack-thread-scoped progress callback to produce a fresh
    orchestrator+tool for each inbound message.
    """
    shared_checkpointer = MemorySaver()

    def _factory(progress_callback: ProgressCallback) -> Graph:
        redline_tool = build_redline_tool(
            default_input_path=DEFAULT_NDA_INPUT,
            default_original_path=DEFAULT_NDA_ORIGINAL,
            default_output_path=DEFAULT_NDA_OUTPUT,
            progress_callback=progress_callback,
        )
        return build_orchestrator(
            redline_tool=redline_tool,
            checkpointer=shared_checkpointer,
        )

    return _factory


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
    agent_factory: AgentFactory | None = None,
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
        agent_factory: Constructs the per-invocation agent. Default
            builds Oscar (the LangChain orchestrator) wrapping the
            redline tool, with a shared ``MemorySaver`` so per-
            conversation memory persists across rebuilds. Tests inject
            a stub-returning lambda.
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
    if agent_factory is None:
        agent_factory = _build_default_agent_factory()
    dispatcher = Dispatcher(channel=channel, agent_factory=agent_factory)
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
