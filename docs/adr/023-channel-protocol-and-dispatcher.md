# ADR 023 [Infrastructure] — Channel Protocol and dispatcher

**Status:** Accepted (Sprint M2 Phase 1, 2026-04-26).

## Context

Sprint M2 introduces a generalised inbound-message framework so future channels (Slack, AgentMail, MCP, Discord, ...) can plug into the same General Counsel without each one re-inventing the wiring. Pre-flight § 1 row 4 confirmed no prior channel infrastructure exists in the repo. Two sub-decisions are bundled here: the Channel surface, and how the dispatcher derives a LangGraph `thread_id`.

## Decision

**1. Channel Protocol — minimum surface, async-first, grow sprint by sprint.** Four methods: `start()`, `stop()`, `post_message(*, conversation_id, text)`, `on_inbound_message(handler)`. `InboundMessage` is a frozen dataclass `(conversation_id, text, raw)`; `raw` carries the channel-specific payload for future enrichment that doesn't belong on the Protocol surface today. All methods are async because the Phase 2 channels (slack-bolt Socket Mode, AgentMail WebSocket) are async I/O — making the Protocol async-first avoids a sync→async bridge in Phase 2 and Phase 3.

**2. Thread-ID derivation — direct mapping, no hashing.** `Dispatcher.thread_id_for(conversation_id) := conversation_id` verbatim. The `conversation_id` is already a stable per-conversation identifier supplied by the channel (e.g. Slack `channel:thread_ts`, AgentMail thread/message-id chain). LangGraph imposes no length / character constraints on `thread_id`. Hashing would obfuscate logs without buying anything. The dispatcher passes `config={"configurable": {"thread_id": <conversation_id>}}` on every `gc_graph.ainvoke(...)`; the GC's MemorySaver (pre-flight § 6.2) keys state by `thread_id`, so same conversation_id → preserved memory and distinct conversation_ids → isolated state.

## Options considered

- **Larger Protocol surface** (typing indicators, presence, edits, reactions, attachments, channel-list discovery) — rejected as YAGNI; Phase 2A/2B add methods only when Slack or AgentMail surfaces a need.
- **SHA-256 hash of conversation_id** — rejected; opaque in logs, no benefit.
- **Per-channel namespace prefix** (e.g. `slack::C1:T1`) — rejected for Phase 1; Slack and AgentMail conversation_ids do not collide. Revisit in M3+ if a future channel emits IDs that could.

## Consequences

- Dispatcher unit tests are pure-Python (FakeChannel + stub Graph; no LLM, no network) — five tests landing in `tests/shared/test_dispatcher.py`.
- Phase 2A (Slack) and 2B (AgentMail) implement the Protocol independently with no shared files.
- The in-memory MemorySaver persists state only for the runtime's lifetime. M3+ may swap to a durable checkpointer (SqliteSaver / PostgresSaver / etc.) — `build_general_counsel(*, checkpointer=...)` accepts the override so the swap is one wire change at the runtime entry point.
- pytest + pytest-asyncio added to `requirements.txt` (Phase 1 first establishes a `tests/` directory; pre-flight § 1 row 14).
