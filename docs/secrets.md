# Secrets Inventory

Metadata for every environment variable the project currently expects. Not
the values — that's what `.env` (git-ignored, VPS-local, per ADR 005) is
for. This file is the authoritative list of *what* must be provisioned for
Oscar to start, alongside `.env.example`.

## Why this file exists

Sprint 6 flagged that `.env` state drifts silently between sprints — a key
swap between providers (MiniMax → OpenRouter) left a later sprint running
against the wrong credential with no git trail. `.env.example` tells you
*what* keys exist; this file adds *when* and *why*, and is the checklist
an operator walks when provisioning a new VPS.

## Maintenance rule

Every sprint that adds, removes, or materially changes an env var updates
the table below in the same commit. The "last touched" date answers
"is this variable still in use?" for future-us.

## Environment variables

| Name | Purpose | Required for | Introduced | Last touched |
|---|---|---|---|---|
| `OSCAR_LLM_PROVIDER` | DI seam: which provider the default chat/LLM client dispatches to (`minimax`, `openrouter`). Default `env_prefix` for both seams. | Sprint 3's `hello_llm.py`, Sprint 6's `hello_deep_agent.py`. | Sprint 3 | Sprint 3 |
| `OSCAR_LLM_MODEL` | DI seam: provider-specific model id (e.g. `MiniMax-M2.7`, `openai/gpt-5.4`). | As `OSCAR_LLM_PROVIDER`. | Sprint 3 | Sprint 3 |
| `OSCAR_LLM_API_KEY` | DI seam: API key for the provider. | As `OSCAR_LLM_PROVIDER`. | Sprint 3 | Sprint 6 (key value swapped between providers; shape unchanged) |
| `OSCAR_LLM_GENERAL_COUNSEL_PROVIDER` | Per-role DI slot (ADR 010): which provider General Counsel uses. Read by `get_chat_model(env_prefix="OSCAR_LLM_GENERAL_COUNSEL")`. | Sprint 7's GC scaffolding. | Sprint 7 | Sprint 7 |
| `OSCAR_LLM_GENERAL_COUNSEL_MODEL` | Per-role DI slot: model id for General Counsel (frontier reasoning; this sprint `openai/gpt-5.4`). | Sprint 7 GC. | Sprint 7 | Sprint 7 |
| `OSCAR_LLM_GENERAL_COUNSEL_API_KEY` | Per-role DI slot: API key for General Counsel's provider. | Sprint 7 GC. | Sprint 7 | Sprint 7 |
| `OSCAR_LLM_HEAD_OF_COMMERCIAL_PROVIDER` | Per-role DI slot (ADR 010): which provider Head of Commercial uses. Read by `get_chat_model(env_prefix="OSCAR_LLM_HEAD_OF_COMMERCIAL")`. | Sprint 7 Head-of-Commercial subagent. | Sprint 7 | Sprint 7 |
| `OSCAR_LLM_HEAD_OF_COMMERCIAL_MODEL` | Per-role DI slot: specialist model id (this sprint `MiniMax-M2.7`). | Sprint 7 Head-of-Commercial. | Sprint 7 | Sprint 7 |
| `OSCAR_LLM_HEAD_OF_COMMERCIAL_API_KEY` | Per-role DI slot: API key for Head of Commercial's provider. | Sprint 7 Head-of-Commercial. | Sprint 7 | Sprint 7 |
| `OSCAR_LLM_ACCEPT_REJECT_REASONER_PROVIDER` | Per-role DI slot (ADR 010): provider for the accept/reject functional specialist. Read by `get_chat_model(env_prefix="OSCAR_LLM_ACCEPT_REJECT_REASONER")`. | Sprint 9 accept-reject-reasoner specialist. | Sprint 9 | Sprint 9 |
| `OSCAR_LLM_ACCEPT_REJECT_REASONER_MODEL` | Per-role DI slot: specialist model id for accept/reject reasoning (this sprint `MiniMax-M2.7`). | Sprint 9 accept-reject-reasoner. | Sprint 9 | Sprint 9 |
| `OSCAR_LLM_ACCEPT_REJECT_REASONER_API_KEY` | Per-role DI slot: API key for the accept/reject specialist's provider. Typically matches the Head of Commercial key when both run on MiniMax. | Sprint 9 accept-reject-reasoner. | Sprint 9 | Sprint 9 |
| `OSCAR_LLM_REDLINE_SPECIALIST_PROVIDER` | Per-role DI slot (ADR 010): provider for the redline specialist (document-level Adeu-driven redlining). Read by `get_chat_model(env_prefix="OSCAR_LLM_REDLINE_SPECIALIST")`. | Sprint 10D redline-specialist. | Sprint 10D | Sprint 10D |
| `OSCAR_LLM_REDLINE_SPECIALIST_MODEL` | Per-role DI slot: specialist model id for redlining (Sprint 10D: `MiniMax-M2.7`). | Sprint 10D redline-specialist. | Sprint 10D | Sprint 10D |
| `OSCAR_LLM_REDLINE_SPECIALIST_API_KEY` | Per-role DI slot: API key for the redline specialist's provider. Typically matches the Head of Commercial key when both run on MiniMax. | Sprint 10D redline-specialist. | Sprint 10D | Sprint 10D |

## Declared but not yet used

| Name | Purpose | Status |
|---|---|---|
| `OSCAR_ENV` | Selects which `policies/oscar-<env>.yaml` loads and which `oscar_config.yaml` section applies (ADR 005). | Declared in ADR 005; no runtime code reads it yet. |
| `LANGSMITH_API_KEY` | Enables LangSmith tracing if set. Sprint 6 confirmed `langsmith` silently no-ops when unset. | Not required; would also need a `smith.langchain.com` policy block if used. |
| `LANGCHAIN_TRACING_V2` | LangChain's alternative tracing switch. Only relevant with `LANGSMITH_API_KEY`. | Not required; same gating as above. |

## Non-env secrets

| Name | Purpose | Location | Introduced |
|---|---|---|---|
| SSH deploy key | Git push to `Oscar-LQ/oscar-enterprise` from the sandbox (ADR 003). | VPS filesystem (not in repo, not in env). | Sprint 0 |

## Policy-allowed endpoints (for the curious)

Current `policies/oscar-dev.yaml` allows (by service block) PyPI (+github /
pythonhosted), api.minimax.io, openrouter.ai, integrate.api.nvidia.com,
docs.claude.com (ADR 007), GitHub SSH via ProxyCommand, and a handful of
Claude Code endpoints. `smith.langchain.com` and any future provider host
would need a new block before use.
