# ADR 008 — LLM Provider Client: raw httpx against OpenAI-compatible endpoint

- **Status:** Accepted
- **Date:** 2026-04-18
- **Scope:** `src/llm/` — how Oscar's runtime LLM calls are dispatched
- **Supersedes:** none
- **Related:** ADR 005 (secrets vs. config split), PROJECT.md § LLM Policy

## Context

PROJECT.md § LLM Policy: Oscar's runtime LLM is model-agnostic via dependency
injection. Sprint 3 built the first concrete integration (MiniMax-M2.7) and had
to decide (a) which client library, (b) which MiniMax endpoint, and (c) what
shape the DI contract returns.

Client options: `langchain-community.MiniMaxChat` (documented stale defaults —
issue [#29278](https://github.com/langchain-ai/langchain/issues/29278), closed
as *not planned*; default host `api.minimax.chat`, default model
`abab6.5-chat`); the official `minimax` PyPI package (sparse docs,
provider-specific dep); raw `httpx` (already installed as a langgraph transitive).

Endpoint options: native `/v1/text/chatcompletion_v2` (requires `GroupId` query
param; exposes native fields such as `reasoning_split`) versus OpenAI-compatible
`/v1/chat/completions` (no GroupId; canonical OpenAI shape).

## Decision

**Raw `httpx` against MiniMax's OpenAI-compatible endpoint.** The DI contract
returned by `get_llm_client()` is a plain `Callable[[str], str]` — prompt in,
completion out. Provider richness (tool calls, streaming, structured reasoning)
is intentionally not in the seam.

Dispatch is a `dict[str, factory]` in `src/llm/__init__.py`. Adding a provider
is one dict entry plus one small factory function; callers unchanged.

## Consequences

- **Pro:** zero new dependencies; integration reviewable as ~50 lines
  (`src/llm/minimax.py`).
- **Pro:** OpenAI-compat means future providers (OpenRouter, OpenAI-direct,
  vLLM-behind-OpenAI-compat) drop into the same shape — same wire, different host.
- **Pro:** string-in/string-out is the smallest thing that composes with
  LangGraph nodes; richer surface can land in a parallel seam when a use case
  requires it.
- **Con:** MiniMax-native features only exposed on the native endpoint
  (`reasoning_split`, MiniMax-specific tool-call shape) are out of reach here.
  Mitigation: add a provider-specific richer client alongside the string seam
  when a sprint needs it — do not retrofit the seam to a richest-common-subset.
- **Con:** raw httpx means we hand-write JSON payloads and response parsing.
  Acceptable at one provider; if the list grows past three, revisit.
- **Sovereignty note:** MiniMax is a Shanghai-operated provider. This ADR makes
  no commitment that MiniMax is the production LLM for any client; MiniMax is
  the first concrete plug for an explicitly model-agnostic seam. Clients with
  PRC-exposure constraints change three env vars — not code — once a second
  provider is wired (future sprint).
