# ADR 009 — Bridging Oscar's LLM DI Seam to Deep Agents' BaseChatModel Requirement

- **Status:** Accepted
- **Date:** 2026-04-18
- **Scope:** `src/llm/` — adds a parallel BaseChatModel-shaped accessor alongside the existing string seam
- **Supersedes:** none
- **Related:** ADR 008 (LLM provider client shape — string-in/string-out), PROJECT.md § LLM Policy

## Context

Sprint 6 wires Deep Agents end-to-end. `deepagents.create_deep_agent` expects a
tool-calling chat model — `BaseChatModel | str | None` (see
`deepagents/graph.py` line 219, the model resolver at `deepagents/_models.py`,
and the explicit warning "Deep Agents require a LLM that supports tool calling").
ADR 008's existing seam returns a `Callable[[str], str]` (`LLMClient`) — string
in, string out, no tool calling. The two shapes do not meet.

Three options to bridge:

1. **Wrap the existing `LLMClient` as a `BaseChatModel` subclass.** Preserves
   one seam. But our raw httpx clients (`MiniMaxClient`, `OpenRouterClient`)
   only emit single-message completions — wrapping a string-in/string-out
   callable as a `BaseChatModel` would lose the very capability Deep Agents
   requires (tool calling, multi-turn message threading, provider-native tool
   schemas).
2. **`langchain-openai`'s `ChatOpenAI` with `base_url` pointed at
   OpenRouter/MiniMax.** Works against any OpenAI-compatible endpoint, but does
   not trigger Deep Agents' built-in OpenRouter profile
   (`deepagents/profiles/_openrouter.py`) which auto-injects app-attribution
   headers (`HTTP-Referer`, `X-Title`).
3. **`init_chat_model("openrouter:...")` via `langchain-openrouter`.** Fully
   native to Deep Agents — `langchain-openrouter`'s `ChatOpenRouter` supports
   tool calling, and Deep Agents' OpenRouter profile applies attribution
   kwargs automatically.

## Decision

**Option 3.** Add a parallel BaseChatModel-shaped seam at
`src/llm/chat_model.py` exposing `get_chat_model() -> BaseChatModel`, dispatched
through a `_FACTORIES: dict[str, factory]` mirroring the string seam in
`src/llm/__init__.py`. For `OSCAR_LLM_PROVIDER=openrouter` the factory calls
`init_chat_model("openrouter:<model>", api_key=<key>)`. The string seam is
unchanged — both seams coexist, each fits its consumer.

## Consequences

- **Pro:** Deep Agents gets a native, tool-calling chat model with the
  built-in OpenRouter profile applied. No subclassing; no loss of tool
  calling support.
- **Pro:** Same env vars (`OSCAR_LLM_PROVIDER`, `OSCAR_LLM_MODEL`,
  `OSCAR_LLM_API_KEY`) drive both seams. Configuration parity preserved;
  providers added by env-var swap, not code.
- **Pro:** New providers extend the chat seam by adding one factory entry
  — mirrors the string seam's extension pattern (ADR 008's "one dict entry
  plus one small factory function").
- **Con:** Two seams instead of one. Acceptable because they serve
  fundamentally different consumers — string-in/string-out integration tests
  vs. tool-calling Deep Agents.
- **Con:** Sprint 6's chat seam only wires OpenRouter. MiniMax via this
  seam needs another factory and probably `langchain-openai` with a
  `base_url` override (no native `langchain-minimax` package exists).
  Deferred until a sprint requires MiniMax for tool-calling work.
- **Sovereignty note:** Inherits ADR 008's note — OpenRouter is a US broker;
  data-residency decisions live at model selection time
  (e.g. `openai/*` vs. `anthropic/*`), not provider selection.
