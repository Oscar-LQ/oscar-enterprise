# ADR 010 — Per-Agent Model Allocation: Frontier at the Top, Capable-but-Cheaper Below

- **Status:** Accepted
- **Date:** 2026-04-18
- **Scope:** How Oscar allocates LLMs across its agent org chart — which role gets which model, by what mechanism
- **Supersedes:** none
- **Related:** ADR 008 (string seam), ADR 009 (chat-model seam), PROJECT.md § LLM Policy / § Model Allocation

## Context

Sprint 7 begins populating Oscar's in-house legal org chart: a General
Counsel orchestrator, department heads below (Head of Commercial is the
first staffed head), and eventually functional agents within each
department. The first concrete allocation decision is: which model serves
which role, and how is that decision expressed in code and configuration?

PROJECT.md § Model Allocation already states the principle —
orchestrator = frontier reasoning model, specialist = capable-but-cheaper,
no hardcoding, per-agent evaluation. This ADR records the first concrete
application of that principle and the DI mechanism that carries it.

## Decision

**One model per agent, chosen per role, injected at build time.**

- *General Counsel* (orchestrator): a frontier reasoning model. This
  sprint: `openai/gpt-5.4` via OpenRouter. Rationale: orchestration is
  reasoning-heavy, relatively low volume; spend tokens here.
- *Head of Commercial* (specialist): a capable-but-cheaper model. This
  sprint: `MiniMax-M2.7` direct. Rationale: specialist execution is
  higher-volume and narrower-scope; cheaper models hold up at per-role
  evaluation time. Per-agent evaluation decides cheaper-vs-stronger on a
  role-by-role basis — this is not a blanket policy.
- *No agent hardcodes its own model.* Each agent receives a
  `BaseChatModel` instance (or equivalent spec) built by the chat-model
  seam (`src/llm/chat_model.py`, ADR 009) from configuration.

Mechanism: per-role env-var triples read through
`get_chat_model(env_prefix=...)`. Sprint 7 introduces two concrete
prefixes — `OSCAR_LLM_GENERAL_COUNSEL_*` and
`OSCAR_LLM_HEAD_OF_COMMERCIAL_*`. Future roles extend the pattern with
new prefixes; no code changes required to swap a role's model.

Rejected:
- **Single `OSCAR_LLM_*` triple for all agents.** Breaks the brief's
  explicit requirement that GC and Head of Commercial run different
  models, and structurally forecloses per-role evaluation.
- **A single `models.yaml` config file.** Right answer once role count
  grows past ~5 or when model selection needs richer attributes
  (temperature, max_tokens, rate-limit kwargs). Overkill for two roles;
  revisit when config sprawl becomes real.

## Consequences

- **Pro:** swapping any role's model is env-var-only; code is untouched.
- **Pro:** different providers coexist in one agent graph — GC can run
  frontier-via-OpenRouter while Commercial runs specialist-via-MiniMax
  (or vice versa) with no seam changes.
- **Pro:** the per-role evaluation principle has a concrete DI shape to
  plug into; each role's evaluation drives its own env-var triple.
- **Con:** `.env` grows one triple per staffed role. At two roles it is
  six vars; at ten roles it is thirty. Mitigation: `docs/secrets.md`
  tracks them with provenance; `.env.example` stays the authoritative
  template. Revisit consolidation when ten+ roles exist.
- **Con:** per-role model bills and usage dashboards fan out — one
  OpenRouter dashboard per OpenRouter-using role, one MiniMax dashboard
  per MiniMax-using role. Operator concern, not a code concern.
