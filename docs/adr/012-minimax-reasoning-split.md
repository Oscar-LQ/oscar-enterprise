# ADR 012 — MiniMax `reasoning_split=True` via `extra_body`

- **Status:** Accepted
- **Date:** 2026-04-18
- **Scope:** `src/llm/chat_model.py` — MiniMax factory behaviour on reasoning-trace handling
- **Supersedes:** none; partially amends ADR 011 (see below)
- **Related:** ADR 011 (MiniMax via OpenAI-compat), Sprint 3 surprise 1, Sprint 7 surprise 3

## Context

MiniMax-M2.7 returns its chain-of-thought inline inside `<think>...</think>`
tags in `message.content` on the OpenAI-compatible endpoint (Sprint 3
surprise 1). Through the chat-model seam, that pollution surfaces in
sub-agent `AIMessage.content` and — because Deep Agents' `task` tool takes
`result["messages"][-1].text.rstrip()` as the parent's `ToolMessage.content`
(`deepagents/middleware/subagents.py:396`) — ends up verbatim in the
orchestrator's message history (Sprint 7 surprise 3).

MiniMax documents `reasoning_split=True` as the native knob that separates
thinking content into a distinct `message.reasoning_details` field, leaving
`message.content` clean. `langchain-openai`'s `ChatOpenAI` exposes
`extra_body` as the documented passthrough for provider-specific parameters
(`langchain_openai/chat_models/base.py:795,1128`). ADR 011's Con #2
incorrectly claimed `reasoning_split` was "not reachable through
`ChatOpenAI`"; empirical verification this sprint proved it is.

## Decision

**Pass `extra_body={"reasoning_split": True}` in the MiniMax factory.**
`_minimax_factory` in `src/llm/chat_model.py` now calls `init_chat_model`
with that kwarg. MiniMax returns `content` as the clean answer and
`reasoning_details` as a separate field. `ChatOpenAI._convert_dict_to_message`
(`langchain_openai/chat_models/base.py:188-228`) only extracts `content`,
`function_call`, `tool_calls`, `audio` — so `reasoning_details` is silently
dropped before the `AIMessage` is built. That is acceptable today.

Rejected alternatives:
- **Tag stripping at the seam** (regex on `<think>…</think>`) — works, but
  loses information the model emits natively and fights the API rather than
  using it. Kept as documented fallback if `extra_body` ever stops working.
- **LangChain output-parser middleware** — no such utility is installed in
  our venv (`langchain-perplexity` is not a dep). Writing one is
  out-of-scope while the native knob works.

## Non-decision (explicit)

**We are NOT preserving `reasoning_details` across turns this sprint.**

MiniMax's guidance is that in multi-turn conversations, prior turns'
reasoning should be re-sent in the `<think>reasoning_content</think>`
format to keep Interleaved Thinking coherent. Our current use case is
single-shot sub-agent invocations via Deep Agents' `task` tool: each
sub-agent run is a fresh `HumanMessage → AIMessage` exchange from the
specialist's perspective, so there is no multi-turn history for that
specialist to lose coherence over.

`reasoning_details` is dropped in three places today: (a) `ChatOpenAI`
drops it during message conversion; (b) even if preserved on `AIMessage`,
Deep Agents' task tool takes only `.text.rstrip()`; (c) the parent agent's
`ToolMessage` only carries the content string — not a structured field
map.

**If a future sprint introduces multi-turn specialist conversations** (e.g.
Head of Commercial maintains state across several exchanges before
returning to the GC), three changes are needed together:

1. Surface `reasoning_details` from the OpenAI-compat response into
   `AIMessage.additional_kwargs` — requires either a thin `ChatOpenAI`
   subclass override of `_convert_dict_to_message` or switching to a
   provider-specific LangChain integration if one exists by then.
2. Re-send prior `reasoning_details` on subsequent calls by formatting
   them back into `<think>...</think>` wrappers when constructing the
   outgoing messages payload (MiniMax expects the wrapper form, not the
   split form, on inbound).
3. Decide where in the Deep Agents / LangGraph pipeline that
   re-wrapping lives — middleware is the natural home.

None of this is built today.

## Consequences

- **Pro:** MiniMax sub-agent responses land clean in the orchestrator's
  `ToolMessage` history. Sprint 7's NDA test, re-run, has
  `<think>`-free ToolMessage content (verified).
- **Pro:** One-line change. No new dependencies. No middleware. No
  post-processing. The fix sits at the narrowest seam that catches all
  MiniMax traffic going through the chat-model DI.
- **Con:** Reasoning content is thrown away. For current use cases
  (single-shot sub-agents) this is fine. When multi-turn specialist work
  arrives, this ADR will be referenced and the three steps above will
  need to be built — not a retrofit of the fix, but new plumbing that
  did not previously exist.
- **Amends ADR 011:** the Con line "MiniMax-specific features only
  exposed on the native endpoint … not reachable through `ChatOpenAI`"
  is partially wrong. `extra_body` makes provider-specific request
  parameters reachable; what is not reachable is non-standard
  *response* fields, which `ChatOpenAI` drops by design.
