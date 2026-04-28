# ADR 029 [Infrastructure] — Agent harness layering (supersedes "Deep Agents Is Reference Material")

**Status:** Accepted (Sprint M3, 2026-04-28). **Supersedes** the CLAUDE.md banked rule "[Process] [Architecture] Deep Agents Is Reference Material, Not Runtime" (banked from Sprint 10Q Phase 0, 2026-04-21).

## Context

The 2026-04-21 banked rule was correct for the redline pipeline: Sprint 10I moved that pipeline from Deep Agents (top-level `create_deep_agent` with `MemoryMiddleware`) to direct `chat_model.invoke` with stdlib infrastructure, because Deep Agents' `MemoryMiddleware` would have violated the client-driven playbook constraint via its `edit_file` self-update prompt template.

The rule was over-broad as written. M2's General Counsel chain ran on Deep Agents in production. CoSec's drafter on its stale branch runs on Deep Agents. M3's architecture (this sprint) makes Oscar a LangChain agent at the front door but explicitly leaves room for Deep Agents at the practice-area-head layer (Head of Commercial first; others later). Three different harnesses are in play — and the right harness depends on the work the agent is doing, not on a blanket rule.

## Decision

Oscar's agent harness is **layered**. Three layers, three choices, one principle.

- **Front door — LangChain.** `langchain.agents.create_agent`. Oscar himself. Tool-calling orchestration: receive a partner request, decide whether to call a tool or reply with a routing message. ADR 026.
- **Practice-area heads — Deep Agents (per use-case).** `deepagents.create_deep_agent` with the `CompiledSubAgent` nesting pattern from ADR 014. Each head's structure is chosen for that practice area's work — no blanket rule that all heads use Deep Agents the same way. Head of Commercial first (later sprint); other heads slot in alongside without a refactor.
- **Long-running pipelines — direct `chat_model.invoke` with stdlib infrastructure.** The 10P planner-executor pipeline is the canonical example (ADR 019). Pipelines whose internal shape is "two LLM calls plus deterministic glue" should not be wrapped in an agent harness — the harness adds nothing and hides the structure.

The principle: **choose the harness that fits the work**. The practical rule of thumb:

- Tool-calling orchestration → LangChain agent.
- Judgement delegation with multi-level subagents → Deep Agents.
- Deterministic pipeline with embedded LLM calls → direct invocation with stdlib glue.

## Options considered

- **Amend CLAUDE.md only, no ADR.** Rejected — this is an architectural framing decision, not a coding-rule clarification. ADR is the right surface.
- **Supersede ADR 014 (CompiledSubAgent nesting).** Rejected — ADR 014's mechanism is still correct for practice-area heads when those land. It is just no longer relevant at the front door, where Oscar's orchestrator does not nest.
- **Mandate one harness across the project.** Rejected — the redline pipeline's evidence (10I-10P) shows direct invocation is the right shape for that work; Sprint 9's GC commercial-acceptreject pattern shows Deep Agents nesting works for judgement delegation. Forcing one harness everywhere would worsen the layer where it does not fit.

## Consequences

- CLAUDE.md banked rule lines 53-55 are replaced with `[Process] [Architecture] Agent Harness Per Use-Case`, referencing this ADR.
- CLAUDE.md Framework Stack section lines 19-21 are revised to describe the layered harness (LangChain front door / Deep Agents practice-area heads / direct invocation for pipelines).
- PROJECT.md Tech Stack table line 84 (`Agent harness | Deep Agents on LangGraph`) is replaced with the layered description.
- ADR 014 (three-level CompiledSubAgent delegation) is **not** superseded. It still applies when practice-area heads land. M3 just does not exercise it at the front door.
- Future research that surfaces an agent-harness primitive should evaluate which layer (front door / heads / pipelines) it fits, rather than asking the binary "Deep Agents or not".
- The 2026-04-21 rule's specific example (Deep Agents' `MemoryMiddleware` `edit_file` self-update prompt) is preserved as a reason to be cautious about Deep Agents middleware in particular contexts, not as a blanket rejection.
