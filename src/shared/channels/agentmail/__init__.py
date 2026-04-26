"""AgentMail channel — official agentmail Python SDK over WebSocket + REST.

Phase 2B of Sprint M2. Implements the ``Channel`` Protocol via:

- **Inbound**: ``AsyncAgentMail.websockets.connect()`` — outbound WSS to
  ``wss://ws.agentmail.to/v0`` (no public endpoint required from the
  sandbox). Subscribes to ``message.received`` events for the configured
  inbox; iterates events with ``async for``.
- **Outbound**: ``AsyncAgentMail.inboxes.messages.reply(...)`` — REST call
  to ``https://api.agentmail.to``.

Both endpoints are enabled by the Phase 2 cross-cutting work in
``policies/oscar-dev.yaml``. Real ``OSCAR_AGENTMAIL_*`` values are sourced
from ``/etc/oscar/oscar.env`` on the host via read-only bind-mount
(ADR 025).

Conversation_id derivation: AgentMail's own ``thread_id`` is the stable
per-conversation identifier and maps directly to the dispatcher's
LangGraph ``thread_id`` (ADR 023, direct-mapping).
"""
