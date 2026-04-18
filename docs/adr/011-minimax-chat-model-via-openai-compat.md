# ADR 011 — MiniMax in the BaseChatModel Seam via OpenAI-Compat `base_url` Override

- **Status:** Accepted
- **Date:** 2026-04-18
- **Scope:** `src/llm/chat_model.py` — how MiniMax is wired into the Deep-Agents BaseChatModel seam
- **Supersedes:** none
- **Related:** ADR 008 (string seam), ADR 009 (chat-model seam — deferred MiniMax), ADR 010 (per-agent allocation)

## Context

ADR 009 established a BaseChatModel-shaped seam for Deep Agents, wired for
OpenRouter only, deferring MiniMax: *"MiniMax via this seam needs another
factory and probably `langchain-openai` with a `base_url` override (no
native `langchain-minimax` package exists)."* Sprint 7 needs MiniMax for
Head of Commercial (ADR 010), so the deferred work lands now.

`langchain.chat_models.init_chat_model` supports ~20 providers natively
(see its docstring). MiniMax is not in the list. Two bridging options
remain: add the factory via `init_chat_model("openai:...", base_url=...)`
which delegates to `langchain-openai`'s `ChatOpenAI`, or construct
`ChatOpenAI` directly.

## Decision

**Option A: `init_chat_model("openai:<minimax-model>", base_url="https://api.minimax.io/v1", api_key=...)`.**

Wired as `_minimax_factory` in `src/llm/chat_model.py`, alongside
`_openrouter_factory`. The returned `ChatOpenAI` talks to MiniMax's
OpenAI-compatible endpoint — same wire shape as the raw-httpx
`MiniMaxClient` (ADR 008) uses, different layer.

Rejected:
- **Direct `ChatOpenAI(model=..., base_url=..., api_key=...)`** — works
  identically, but routes around `init_chat_model`, which is the
  consistent entry point used by the OpenRouter factory. Keeping both
  factories behind `init_chat_model` means future provider-string
  changes land in one place.
- **Subclassing `BaseChatModel` manually around the raw-httpx
  `MiniMaxClient`** — would reproduce tool-calling machinery that
  `ChatOpenAI` already gives us for free. No payoff.

## Consequences

- **Pro:** MiniMax tool calling works end-to-end through the chat-model
  seam. Verified Sprint 7 via the Head of Commercial round-trip.
- **Pro:** `init_chat_model` stays the single construction entry point,
  matching ADR 009's OpenRouter factory. New providers append one
  factory, same pattern.
- **Pro:** `<think>...</think>` inline reasoning (Sprint 3 surprise 1,
  Sprint 7 Head of Commercial output) continues to land inside
  `AIMessage.content`. It does not break tool calling — the
  OpenAI-compat response still carries `tool_calls` correctly when the
  model emits them. Downstream consumers that parse structured content
  still need to strip `<think>` blocks (deferred).
- **Con:** `langchain-openai` + `openai` + `tiktoken` + `regex` + `tqdm`
  are now permanent deps (Sprint 6 installed them transiently for
  diagnosis and uninstalled; Sprint 7 keeps them). `requirements.txt`
  updated.
- **Con:** MiniMax-specific features only exposed on the native endpoint
  (`reasoning_split`, MiniMax-native tool-call shape) are not reachable
  through `ChatOpenAI`. Same tradeoff as the string seam — acceptable
  until a sprint needs those features.
- **Sovereignty note:** MiniMax is Shanghai-operated; calls to
  `api.minimax.io` route to PRC infrastructure. The sovereignty profile
  is unchanged from ADR 008 / ADR 009 — only the client library shifted.
