# Channel abstraction

The Channel framework lets Oscar's General Counsel receive inbound user messages and post replies through any external transport — Slack, AgentMail, MCP, future channels — without the GC knowing anything about the transport.

## Surface (Phase 1)

`src/shared/channels/base.py` defines the `Channel` Protocol and the `InboundMessage` dataclass. The Protocol has four methods:

- `async start()` — open the connection; return when ready to receive inbound messages and accept outbound posts. Implementations manage any background task they need to keep the connection alive.
- `async stop()` — close; idempotent.
- `async post_message(*, conversation_id, text)` — outbound. The channel parses `conversation_id` back into the shape its provider needs.
- `on_inbound_message(handler)` — register the dispatcher's handler. Called once before `start()`.

`InboundMessage(conversation_id, text, raw)` carries the user's text plus the unmodified channel-specific payload (`raw`) for future enrichment that doesn't belong on the Protocol surface today.

Dispatcher logic lives in `src/shared/dispatcher.py`; it derives a LangGraph `thread_id` from the channel's `conversation_id` (direct mapping; ADR 023) and round-trips the message through the GC graph.

## Why grow sprint by sprint

Speculative API design ages badly. The Phase 1 surface is the minimum required to round-trip a message; it is deliberately incomplete. Phase 2 adds methods only when Slack or AgentMail surface a need that the dispatcher cannot serve against the current four. This keeps the Protocol honest — any method on it is there because at least one production channel needs it.

Anticipated additions (not committed to):

- Typing / presence / read receipts, if a channel surfaces them.
- Attachments / file uploads (Slack and AgentMail both support this; M2 deliberately defers).
- Reactions / acknowledgement primitives (cheap-confirmation pattern).
- Channel-list / inbox-list discovery.

When a need surfaces, the spec for adding a method is: it goes on the Protocol only if the dispatcher (not just one channel implementation) needs it. Channel-specific affordances stay on the concrete class.

## Testing

`src/shared/channels/fake.py` ships `FakeChannel`: an in-memory implementation that records outbound posts and exposes `simulate_inbound()` to drive the registered handler. Used by:

- `tests/shared/test_dispatcher.py` — unit tests for the dispatcher.
- Future integration tests that need to swap a real channel out without changing the rest of the wiring (see `docs/operations/runbook-channel-switch.md`).

`FakeChannel` is `@runtime_checkable` Protocol-compliant — a load-time assertion in `fake.py` will fail import if a future Channel method isn't implemented.

## References

- ADR 023 — Channel Protocol and dispatcher.
- ADR 024 (placeholder) — Channel deployment topologies (Slack Socket Mode + AgentMail WebSocket); written in Phase 2.
- ADR 025 (placeholder) — Secrets on host, bind-mounted read-only into the sandbox; written in Phase 2.
- `docs/sprints/M2-preflight.md` — full Sprint M2 scope including the § 7 addendum that established the two-channel pattern.
