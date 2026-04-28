# ADR 028 [Infrastructure] — Channel-level `post_progress` and tool-bound progress callback

**Status:** Accepted (Sprint M3, 2026-04-28).

## Context

The 10P pipeline takes 55-128 seconds against GPT-5.5 + MiniMax. Without progress narration the partner sees a Slack mention go silent for two minutes, which is unacceptable on multiple counts: Slack's user-perceived ack window is around 3 seconds, the partner has no visibility into whether work is happening, and a future practice-area-head delegation step (Head of Commercial returning a partner-quality redline) would compound the silence.

The orchestrator's first turn against `redline_nda` is an `AIMessage` carrying a tool call which the dispatcher's `_final_reply_text` discards (only AIMessages with content and no tool_calls are kept). Without explicit progress narration, the partner sees nothing until the orchestrator's second turn after the tool returns — well past the 3-second window.

Three options were considered for where progress narration lives:

- (a) `Channel.post_progress` method + a `progress_callback` parameter on the redline tool factory.
- (b) LangChain `AsyncCallbackHandler` with `on_tool_start` / `on_tool_end` hooks.
- (c) A custom LangGraph node between the agent and the tool that emits progress events.

## Decision

Option (a). Progress narration is a new optional method on the `Channel` Protocol (`post_progress`) plus an async `progress_callback` parameter on `build_redline_tool`. The dispatcher rebuilds the agent per inbound message so it can bind a conversation-scoped callback to the tool's closure.

- **Channel Protocol gains `post_progress(*, conversation_id, text)`.** Default for Slack and AgentMail is identical to `post_message` — a threaded reply. Future channels with a more idiomatic surface (Slack reactions, ephemeral messages) can override.
- **`FakeChannel` records progress separately.** `posted_progress: list[PostedMessage]` distinct from `posted_messages` so tests can assert on progress narration without conflating it with the final reply.
- **Tool-bound callback.** `build_redline_tool(progress_callback=...)` captures the callback in closure; `run_redline` awaits it at five well-defined milestones (extracting / thinking / drafting / applying / done).
- **Per-invocation agent rebuild.** Dispatcher field changes from `gc_graph: Graph` to `agent_factory: Callable[[ProgressCallback], Graph]`. Each `handle()` call constructs a fresh callback bound to the inbound's `conversation_id`, calls the factory, and invokes the returned agent. The shared `MemorySaver` is passed by the runtime so per-conversation memory persists across rebuilds.

## Options considered (and why (b) and (c) were rejected)

- **(b) LangChain callbacks.** The `AsyncCallbackHandler.on_tool_start` / `on_tool_end` events fire at the orchestrator's outer turns (call this tool / tool returned), not at the tool's *internal* milestones (extract → plan → draft → apply → done). The events the user wants to see live inside the tool, where the LLM-internal pipeline stages are. Routing through callbacks would either narrate the wrong things (orchestrator outer turns) or require the tool to fire its own callback events through the LangChain callback bus, which is more complex than the closure pattern.
- **(c) Custom LangGraph node.** Over-engineered for one tool. Doesn't scale to future tools without per-tool wiring. The closure pattern composes naturally — every tool that needs progress narration takes a `progress_callback` parameter, and the dispatcher's per-invocation factory binds it.

## Consequences

- The orchestrator stays Slack-unaware. It sees a generic LangChain agent with one tool; it has no concept of channels or progress.
- The tool owns its progress vocabulary (extracting / thinking / drafting / applying / done). This is the right place — the tool is the only authority on its own internal stages.
- Per-invocation agent rebuild adds ~10ms per inbound (graph compilation is millisecond-scale; the actual cost is the LLM call). Negligible. Memory pressure from allocating a fresh `CompiledStateGraph` per inbound — profile in M4 if visible.
- Future channels override `post_progress` for their own surface. M3's Slack and AgentMail implementations both delegate to `post_message` — change one method per channel to switch the surface.
- LangGraph singleton-agent issue (#2040) — same-thread concurrent inbounds step on the shared MemorySaver. Documented limit; per-conversation `asyncio.Lock` deferred to a follow-up sprint.
- Constraint accepted: M3 is one inbound at a time. The fixture-path single-user test does not hit concurrency.
