"""Slack channel — slack-bolt AsyncApp + AsyncSocketModeHandler.

Phase 2A of Sprint M2. Implements the ``Channel`` Protocol via slack-bolt's
async API in Socket Mode (no public endpoint required from the sandbox).
Subscribes to ``app_mention`` only; constructs ``conversation_id`` as
``f"{channel}:{thread_ts or ts}"`` so the dispatcher's direct-mapping
``thread_id`` derivation (ADR 023) gives per-conversation memory.

Real tokens are sourced from ``/etc/oscar/oscar.env`` on the host via
read-only bind-mount (ADR 025). The ``SlackChannelSettings`` Pydantic-
settings class validates the env vars at construction time (CLAUDE.md
"Config Validation on Startup").
"""
