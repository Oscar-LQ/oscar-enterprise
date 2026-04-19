# PROJECT.md — Oscar Enterprise

> This file describes WHAT Oscar is. See CLAUDE.md for HOW to write the code.
> Read both files before writing any code.
>
> This is a goal document. It describes the destination, not the path.
> Build decisions emerge stage by stage and are captured in ADRs as they are made.

## What Oscar Is

Oscar is an AI agent that automates large parts of in-house legal work — commercial transactions, company secretarial, privacy compliance, and more. Oscar is delivered as a service by law firms to their clients, with a dedicated VPS per client, fully isolated, governed by NVIDIA OpenShell. Each client's Oscar learns the client's preferences and house positions over time and becomes increasingly tailored to how that client wants legal work done.

Oscar is multi-capability. Capabilities are added in stages. They share a common foundation: the same agent harness, the same governance discipline, the same memory and audit principles. New capabilities slot in alongside existing ones rather than as separate products.

Oscar's first capability is **contract redlining**. Oscar reads contracts the way a commercial lawyer would — clause by clause, against the client's playbook, with an eye to commercial substance — and returns marked-up versions with native track changes. Subsequent capabilities are added as the work matures.

---

## One VPS, One Client, No Multi-Tenancy

Each client gets their own VPS. There is no multi-tenant architecture. No row-level security. No tenant_id columns. One database, one Oscar instance, one client.

This means:

- No tenant isolation logic in the application code
- No tenant context middleware
- No RLS policies
- Simple, direct database queries
- Complete isolation by infrastructure, not by code

Client-specific configuration lives in `oscar_config.yaml`, not in a tenants table.

---

## What Oscar Does

Oscar is a working legal team in software. It does the kinds of things a junior to mid-level in-house lawyer would do — read documents, propose changes, ask questions, generate outputs, learn what the client wants — across a growing range of capability areas.

Oscar communicates in plain English. No legalese unless the output is itself a legal document. Oscar leads with materiality (what matters, why), gives opinions where asked, and flags uncertainty rather than papering over it.

### Human Authority

Humans are always the final authority on Oscar's output. Oscar proposes, humans confirm. Oscar's confidence in its own outputs is always provisional until a human signs off.

### Audit

Every action Oscar takes is recorded — what changed, from what source, when, by whom. Append-only. Oscar's behaviour is inspectable end to end.

### Learning

Oscar learns from its clients over time. Preferences, house positions, drafting styles, walk-away thresholds — these accumulate through the natural course of work. Oscar does not autonomously rewrite its own knowledge; updates flow through human approval. The learning loop is the substantive differentiation: each client's Oscar becomes that client's Oscar.

---

## What Oscar Does NOT Do

- Provide legal advice on its own authority — Oscar is a tool used by solicitors
- Delete data (soft delete only)
- Modify its own code, prompts, or knowledge autonomously
- Send communications outside configured channels
- Make external API calls to anything not declared in its sandbox network policy

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.13 |
| Sandbox | NVIDIA OpenShell |
| Agent harness | Deep Agents on LangGraph |
| Database | PostgreSQL |
| LLM (runtime) | Model-agnostic via dependency injection |
| LLM (build) | Claude Code |
| Observability | LangSmith + OpenTelemetry |

Specific libraries within these layers (memory tools, channel adapters, document processing engines, etc.) are chosen per capability stage and captured in ADRs.

### LLM Policy

Oscar's runtime LLM is model-agnostic by design. Model choice is a dependency injection at startup, not hardcoded in agent code. Clients with sovereignty concerns can configure their own provider.

The build-time agents (Claude Code) are exempt from this policy — they are tools for humans, not part of Oscar's runtime.

### Model Allocation

Model choice is dependency injection, not hardcoded. The architectural principle:

- The orchestrator (General Counsel) uses the strongest available frontier reasoning model. Today that might be GPT-5.4 or Opus 4.7; tomorrow it will be whatever has superseded them. Orchestration is reasoning-heavy and relatively low-volume — spend the tokens here.
- Specialist agents that do the substantive work run on capable-but-cheaper models. In DEV that is MiniMax. In PROD it might be Sonnet or similar. The right choice per specialist depends on per-agent evaluation — some will need more capable models, others won't.
- No agent hardcodes its own model. Allocation lives in configuration and is injected at startup.

---

## Sandbox

Oscar's runtime runs inside an OpenShell sandbox. This is foundational, not optional. Network policy is default-deny. Every external endpoint Oscar talks to is explicitly allowed in policy YAML, with method-level enforcement where it matters. Policy YAML is version-controlled in the repo.

---

## Capability Stages

**Phase 1 (current): Contract redlining.** Oscar reads commercial contracts and returns redlined versions reflecting the client's playbook. Edits are returned as native Word track changes. The playbook learns from client conversations.

**Future phases** will be specified in this file as they are approached. Likely areas:

- Company secretarial
- Privacy compliance
- Transactional support (M&A, due diligence)
- Further areas as the in-house legal capability surface expands

The order in which future phases are tackled depends on what we learn from earlier ones, on commercial priorities, and on what client demand looks like as Oscar reaches market.

---

## Files in Project Root

| File | Purpose |
|------|---------|
| README.md | Brief project description |
| PROJECT.md | This file — what Oscar is; includes the Sprint Index |
| SPRINT_LOG.md | Append-only detailed record of every sprint (paired with the Sprint Index in PROJECT.md) |
| CLAUDE.md | Coding standards — governs how Oscar's code is written |
| oscar_config.yaml | Runtime configuration |
| .env.example | Template for required environment variables |
| policies/ | OpenShell policy YAMLs |
| docs/adr/ | Architecture Decision Records |
| src/ | Application source |
| tests/ | Test source |

Deployment-time exclusion of non-runtime files (PROJECT.md, CLAUDE.md, docs/adr/) is a build/package-time concern — handled via a deployignore or equivalent when SIT is stood up — not a reason to keep files outside git. Git is the durability mechanism; what ships to SIT is a later, separate concern.

---

## Sprint Index

> One-line summaries of each sprint, chronological. The full append-only record — goals, findings, surprises, ADRs, carry-forwards — lives in `SPRINT_LOG.md`. Read the most recent entry there to know where work picks up; use this index to identify which older entries are worth reading for the task at hand.

- **Sprint 0 (2026-04-18) — Establish workflow.** Sprint log bootstrapped in PROJECT.md; sandbox ready for repo clone. No technical artefacts.
- **Sprint 1 (2026-04-18) — Install LangGraph core.** `langgraph 1.1.8` installed into `/sandbox/.venv`; `pip install langgraph` pulls `langchain-core`, `langgraph-prebuilt`, `langgraph-sdk`, `langsmith`, and the in-memory `langgraph-checkpoint` as hard deps. Version lives at `langgraph.version.__version__` — langgraph is a PEP 420 namespace package with no top-level `__version__`. PyPI egress was already open; no policy widening needed.
- **Sprint 2 (2026-04-18) — Minimal LangGraph runs.** Smallest 2-node graph (`START → append_hello → append_world → END`) runs end-to-end with a TypedDict state. `docs.langchain.com` is policy-blocked, so worked from installed source per "code outranks docs." Node returns overwrite state by default — reducers are needed for accumulation. `StateGraph(config_schema=...)` is soft-deprecated in 1.1.8 in favour of `context_schema`.
- **Sprint 3 (2026-04-18) — MiniMax LLM round-trip.** `MiniMax-M2.7` round-trips through a 2-node graph via raw `httpx`; DI seam built at `src/llm/` with `_FACTORIES` dispatch (adding a provider is one dict entry + one factory). `langchain-community.MiniMaxChat` rejected as stale (issue #29278, wrong host/default). MiniMax's OpenAI-compat endpoint returns chain-of-thought inline in `<think>...</think>` tags (deferred to Sprint 8). ADR 008.
- **Sprint 4 (2026-04-18) — OpenRouter as a second provider.** OpenRouter plugs into the DI seam with zero graph-code changes — validates ADR 008's "provider is one branch, not a rewrite" claim. `openai/gpt-5.4` returns clean text with no `<think>` wrapper, so MiniMax's reasoning-trace behaviour is provider-specific, not OpenAI-compat-general. OpenRouter is a US broker fronting many upstreams — sovereignty decisions move from provider-choice to model-slug-choice.
- **Sprint 6 (2026-04-18) — Deep Agents runs end-to-end.** `deepagents 0.5.3` runs a smallest-meaningful agent with a `slugify` tool + filesystem + planning against `openai/gpt-5.4` on OpenRouter. Parallel `BaseChatModel` seam added at `src/llm/chat_model.py` because the Sprint-3 string seam can't do tool-calling. Every Deep Agent gets a latent `general-purpose` subagent — `SubAgentMiddleware` is unconditional, so single-agent postures are prompt-level only. `requirements.txt` frozen at 54 pinned packages. ADR 009.
- **Sprint 7 (2026-04-18) — General Counsel + Head of Commercial routing scaffolding.** Two-role GC-over-HOC org chart routes correctly on two test invocations (NDA delegates to HOC via `task`; Companies House declined without delegation). MiniMax factory added to chat-model seam via `init_chat_model("openai:MiniMax-M2.7", base_url=...)`. Per-role env-var triples (`OSCAR_LLM_GENERAL_COUNSEL_*`, `OSCAR_LLM_HEAD_OF_COMMERCIAL_*`) are the DI mechanism. `tools=[]` on `SubAgent` inherits default middleware tools — "toolless" is prompt-level, not framework-level. `docs/secrets.md` seeded. ADRs 010, 011.
- **Sprint 8 (2026-04-18) — Resolve MiniMax `<think>` pollution flagged in Sprint 3.** One-line fix: `extra_body={"reasoning_split": True}` in `_minimax_factory`. MiniMax splits reasoning into a separate `reasoning_details` field, which LangChain's `_convert_dict_to_message` drops by design — `AIMessage.content` arrives clean. Amends ADR 011's "`reasoning_split` not reachable" claim: provider-specific *request* parameters ARE reachable via `extra_body`; only non-standard *response* fields are dropped. Lesson: prefer the native knob before reaching for post-processing. ADR 012.
- **Sprint 9 (2026-04-18) — Accept/reject reasoner (first functional specialist under Head of Commercial).** Three-level delegation GC → HOC → `accept-reject-reasoner` works end-to-end on three test invocations (accept unchanged, reject Delaware, counter Scotland). `with_structured_output(method="json_schema")` fails against MiniMax's OpenAI-compat shim — `AutoStrategy` auto-falls-back to `ToolStrategy` which works reliably. `CompiledSubAgent` is the documented nesting pattern (`SubAgent` TypedDict has no `subagents` field). MiniMax tool-call discipline was ~67% on first prompt, 100% with an explicit output-discipline preamble. `structured_response` doesn't propagate up through the `task` tool. ADRs 013, 014, 015, 016.
- **Sprint 10A (2026-04-19) — Adeu integration research (plan only, no code).** `docs/research/sprint-10-adeu-integration.md` reads Adeu 1.1.0 and Claude-Plugin-MCP from source. Proposes SDK integration (not CLI or MCP server), a new `redline-specialist` under HOC via `CompiledSubAgent`, a three-sprint split (10B substrate / 10C wiring / 10D verification). Prior-art discipline distilled to three lawyer-shape rules. Adeu's `RejectChange` only cancels own prior edits; counterparty-text deletion is only reachable via over-broad `ModifyText`. 10 risks surfaced.
- **Sprint 10B (2026-04-19) — Install Adeu 1.1.0 and prove SDK works mechanically (substrate only).** `adeu==1.1.0` installed into `/sandbox/.venv` (59 new transitives; `requirements.txt` 59→119). `src/experiments/sprint-10b-adeu-bare-bones/run.py` generates a synthetic `.docx`, applies three hardcoded `ModifyText` edits via `RedlineEngine.process_batch`, and verifies structurally correct OOXML: each modification produces `w:del`+`w:ins` with `w:author="Oscar"` and original text preserved in `<w:delText>`; insertion produces a single `w:ins`. Pure insertion is NOT a first-class SDK primitive — 10A's "empty target_text" recipe is rejected by the engine; the supported idiom is prefix-match (`new_text.startswith(target_text)` is synthesised as INSERTION internally). `CommentsManager` eagerly creates four comments-related parts even when unused. Each modification emits two tracked change IDs, not one. Adeu ready for 10C agent integration.
- **Sprint 10C (2026-04-19) — Adeu API reference, test battery, idioms, and lawyer-shape criteria (research only).** Four artefacts committed: `docs/reference/adeu-api-reference.md` (~750 lines, exhaustive operation inventory covering every `adeu.__all__` symbol + `adeu.sanitize` + `BatchValidationError`), `src/experiments/sprint-10c-adeu-reference/` (5 themed suites + harness + runner; 82/82 passing on adeu==1.1.0), `docs/reference/adeu-idioms.md` (intent-organised usage guide — phrased to be quoted into Sprint 10D's prompt), `docs/reference/adeu-lawyer-shape-criteria.md` (DRAFT success criteria per NDA transformation; awaits Arturs's review). Ten new findings not in 10A/10B — notably: fuzzy regex matches `\n\n` as `\s+` (cross-paragraph targets succeed); `trim_common_context` narrows full-sentence mods to word-level diff (does 80% of lawyer-shape work automatically); comments on pure deletions silently dropped; non-owning author CAN reject by id (qualifies 10A #6 — audit-trail protection must live above Adeu); `ReplyComment` on missing parent silently adds stray comment; `comment` field on Accept/RejectChange is vestigial. 10B follow-up (b) solved: structlog WARNING-routing pattern reusable. Four questions flagged for Arturs's human decision before 10D begins. No ADRs; no requirements.txt changes; no egress changes.

