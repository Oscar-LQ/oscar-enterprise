# CLAUDE.md — AI-Coded Project Standards

> Drop this file into any project root. Claude Code, Cursor, and the Forge will follow it.
> Battle-tested on a 17K-line Node.js + Python codebase (April 2026).
> Evidence-based: patterns that survived ETH Zurich research on context files,
> Khalil Stemmler's 150K-line DI analysis, Pydantic benchmark data, and
> real production incident analysis. Ceremony that doesn't pay off is excluded.

## Who This Is For

AI-coded projects where Claude Code, Cursor, Copilot, or autonomous agents write most of the code. The AI reads these rules as a spec before generating. Every rule exists because the AI would get it wrong without being told — nothing here is inferable from reading the code itself.

## Project Specification

**Read PROJECT.md before writing any code.** It describes what this project builds, the technology stack, reference projects to survey, build phases, and functional requirements. This file (CLAUDE.md) governs how to write the code. PROJECT.md governs what code to write.

**PROJECT.md is paired with SPRINT_LOG.md.** PROJECT.md has two parts: a goal section describing what Oscar is, and a Sprint Index at the bottom — one-line summaries of every sprint, chronological. The full append-only detailed record of each sprint (goals, findings, surprises, ADRs, carry-forwards) lives in `SPRINT_LOG.md` at the repo root. Read PROJECT.md fully every time. Always read the most recent entry in SPRINT_LOG.md to know where the previous sprint left off. Use the Sprint Index to identify which older entries in SPRINT_LOG.md are relevant to the current task, and read those — how many depends on the task, use judgement. At the end of every sprint, append a new entry to SPRINT_LOG.md following the format of previous entries and add a matching one-line summary to the Sprint Index in PROJECT.md before committing.

## Framework Stack (Current)

This project uses **NVIDIA OpenShell** for sandbox runtime and governance, **LangGraph / LangChain** as the orchestration foundation, and a **layered agent harness** on top: **LangChain** at the front door (Oscar — see ADR 026), **Deep Agents** for practice-area heads where the work fits the subagent-delegation shape (see ADR 014), and **direct chat-model invocation** for long-running pipelines like the redline planner-executor (see ADR 019). Choose the harness that fits the work; do not reach for alternative agent frameworks (CrewAI, AutoGen, OpenAI Agents SDK, custom orchestrators) unless an ADR explicitly authorises it. The model layer underneath is dependency-injected — see PROJECT.md's LLM Policy section.

### Read OpenShell. Do Not Assume.

OpenShell is alpha software with behaviour that is sometimes surprising, often undocumented in tutorials, and changes between versions. **Always read the OpenShell repo at `/sandbox/reference/nvidia-openshell/` before acting on any OpenShell-related task.** This includes the docs, the source code, the agent skills in `.agents/skills/` (notably `generate-sandbox-policy`, `openshell-cli`, `debug-openshell-cluster`), and the deny logs from `openshell logs` when diagnosing failures. The clone is a shallow read-only reference — do not commit changes to it; to refresh, re-sync from the host copy at `/root/nvidia-openshell`.

When you don't know how a command behaves, what a flag does, or why something is being blocked — read first, act second. Do not infer from how similar tools work. Do not guess from past versions. Do not pattern-match from generic Kubernetes or Docker knowledge. The OpenShell behaviour is what matters, and the OpenShell repo is the source of truth.

**Code outranks docs.** OpenShell documentation sometimes lags the source across alpha releases — when they disagree, trust the code. Read the code path you're invoking, not just the reference page that describes it.

If the repo doesn't answer the question, say so explicitly and propose a small experiment to find out — don't proceed on a guess.

---

## Cross-Version Porting Research

When a sprint involves porting a pattern from another codebase that depends on a third-party library, Phase 1 research must identify the version of that library the source codebase was written against, compare it to the version currently in use, and verify contract compatibility (method signatures, return shapes, documented behaviour, deprecations). Reading the source codebase's current code is not sufficient — its code reflects the dependency contract at the time it was written, not the current state of those dependencies. A pattern that compiles against the old contract and silently malfunctions against the new one is the shape of failure to defend against.

---

## [Redline] [Process] Re-derive Phase 0 Findings Against New Behavioural Rules

When behavioural rules are added to a sprint after Phase 0 research is written, re-derive the research's implications against the new rules — don't assume equivalent. Phase 0 finds hold to the rules they were written under; new rules may demand new port surface. (Banked from 10P Phase 0: rule 4 added ~700 LoC of port surface that the feasibility note predated.)

---

## [Redline] MCP Dual-ID Pattern: ooxml_id for Adeu Wiring, Chg:N for Display

MCP's dual-ID pattern (Chg:N for LLM display, ooxml_id for Adeu wiring) is load-bearing. Anywhere Oscar passes change identifiers between planner output and Adeu calls, use ooxml_id. Chg:N is display-only and renumbers across operations. (Banked from 10P Phase 2: silent failure mode caught at smoke-test.)

---

## [Process] [Architecture] Agent Harness Per Use-Case

Oscar's agent harness is layered. **LangChain** at the front door (Oscar's orchestrator — see ADR 026). **Deep Agents** per practice-area head where the work fits the subagent-delegation shape (Sprint 9 GC commercial-acceptreject is the canonical reference, ADR 014). **Direct `chat_model.invoke`** with stdlib infrastructure for long-running pipelines (10P redline; ADR 019). Choose the harness that fits the work; ADR 029 records the layering principle and supersedes the prior "Deep Agents is reference material" framing. The 2026-04-21 specific finding (Deep Agents' `MemoryMiddleware` `edit_file` self-update would have violated the client-driven playbook constraint) is preserved as a reason to be cautious about Deep Agents middleware in particular contexts, not as a blanket rejection.

---

## Multi-Track Discipline

Oscar is developed across multiple parallel tracks. Current: **Redline** (10-series sprints) and **CoSec** (C-series). Infrastructure sprints spanning tracks use the **M-series**. The Sprint Index in `PROJECT.md` shows all three. Established by Sprint M1.

- **Pull before push, always.** `git pull --rebase origin main` before `git push`. Both tracks write to `main`; a missed pull silently overwrites the other track's governance updates.
- **At sprint start, check the most recent `SPRINT_LOG.md` entry on each other track.** Note what is in flight and which feature branches might land during your sprint.
- **SPRINT_LOG headings lead with the sprint number and a track tag**, e.g. `### Sprint 10K — [Redline] — <date> — <title>`.
- **TODO entries are tagged `[Redline]`, `[CoSec]`, or `[Infrastructure]` at item start**, before the bold title. Numbering is one sequence across all tracks.
- **ADRs use one numbering sequence across tracks.** From 019 onwards, titles carry a track tag, e.g. `ADR 019 [Redline] — <title>`. ADRs 002-018 predate the convention and stay untagged.
- **When plan mode identifies likely ADRs, reserve the numbers with placeholder files** at `docs/adr/NNN-PLACEHOLDER-*.md`. Other tracks see the reservation and reach past it; an unused reservation is cheaper than a numbering collision.
- **Track-specific architectural principles live in `docs/{track}/`, not `PROJECT.md`.** PROJECT.md carries only cross-track principles.
- **Track-specific code lives under `src/{track}/`.** Cross-track utilities live under `src/shared/` and require both-track-awareness when modified.

---

## Redline Track Discipline

- **Surface output artefacts at sprint end.** Commit and push the produced `.docx` (and any other reviewable output) to the sprint's feature branch and include the GitHub download URLs in the SPRINT_LOG entry. The lawyer reviews the document, not the metrics — span counts, diff widths, and acceptance rates do not substitute for reading the actual redline.

- **[Redline] [Infrastructure] Verify model routing against LangChain reply metadata, not env vars.** When a sprint result depends on which model served which call, verify against the LangChain reply's `response_metadata.model_name` (and `additional_kwargs` for upstream model strings via routing layers like OpenRouter), not against the env var or the assumed routing. The metadata capture helper at `src/shared/llm/metadata_capture.py` writes `llm-meta-{role}-{N}.json` alongside the `.content` output for every call — experiment harnesses must call it after each `chat_model.invoke()`. Sprints that don't capture metadata cannot make routing claims with API-envelope provenance; their routing assertions are indirect inference (output character + provider-routing tightness + transcript env values), which is sufficient for most purposes but not for any sprint where the routing question is itself the experimental variable. Established by Sprint 10O's verification audit; rule applies to the Redline track and to any cross-track sprint that exercises the chat-model seam.

---

## Architecture & Design

### Classes for Stateful Services
If a module has module-level `let` variables or mutable state, it should be a class. Pure utility functions stay as functions. Router, memory client, LLM service, HTTP client, tool handler — these own state and belong in classes.

### Manual Dependency Injection
Classes receive dependencies via constructor params — never import singletons directly for services they depend on. **No DI container.** Factory functions create configured instances. This is for testability, not ceremony. A 150K-line Node.js codebase doesn't need InversifyJS; neither does yours.

### Facade Pattern for Migration
When extracting a class from an existing module, re-export all original function signatures as thin wrappers around a singleton instance. Zero breaking changes for consumers:
```javascript
export class RouterService { classify(text) { ... } }
const _instance = new RouterService(config, evoClient);
export const classifyMessage = (...args) => _instance.classify(...args);
```

### Single Entrypoint Per Feature
Each service class has one main public method orchestrating the workflow. Supporting logic in private methods or composed helpers. Outside code calls the entrypoint only.

### Dispatch Over If/Else Chains
Use Map/object lookup, polymorphism, or registry patterns for branching on type or value. If you're writing `if (type === 'A') ... else if (type === 'B')`, refactor to a dispatch table.

### Repository Pattern for I/O
Business logic never touches files, APIs, or external services directly. All I/O through service classes passed as dependencies. Memory access through MemoryClient, LLM calls through LLMService, etc.

### Modularity
Every class and function must have a single responsibility. If something is doing two things, split it. Maximum file size: 300 lines. If you need "and" in the description, split the file.

---

## Type Safety

### TypeScript for AI-Coded Projects (Node.js)
Rename `.js` → `.ts` when refactoring a module. Use `tsx` for execution (zero-config, no explicit compile step). Strict mode, no `any`. **This is an AI-coded project — types are the spec the AI reads before generating.** Without types, the AI is guessing. With types, it's reading a spec.

If TypeScript adds too much migration cost for an existing project, use `// @ts-check` + JSDoc on critical modules as a stepping stone. But for new code, always TypeScript.

### Pydantic at API Boundaries Only (Python)
Request/response validation on FastAPI/Flask endpoints. **Dataclasses internally.** Pydantic adds 6.5x instantiation overhead and 2.5x memory — don't use it where it doesn't guard an external boundary.

### Enums for Fixed Values
Status codes, categories, routing decisions, modes — all frozen objects (JS/TS) or Enums (Python). No raw strings for values with defined meanings.

### Full Annotation Coverage
Every function, method, parameter, and return type annotated. Code readable from signatures alone. In Python, use keyword-only parameters (`*`) on public methods to prevent positional argument bugs.

---

## Error Handling

### No Silent Failures — Strictly Enforced
Every catch/except block either:
- (a) Handles with explicit recovery logic
- (b) Logs with context (`logger.error({ err, query, context })`) and re-raises or returns error
- (c) Has `// intentional: [reason]` comment explaining why swallowing is safe

Bare `catch {}` and `except: pass` are **banned**.

### Log Errors With Context, Not Exception Types
What failed, what the input was, why it matters. A `catch (err) { logger.error('memory search failed', { query, err }) }` is more useful for debugging than a custom exception hierarchy. Context in the log beats `instanceof` checks.

**Skip custom exception hierarchies** for single-developer and AI-coded projects. They add no debugging value when you already know the call stack. The ROI is near zero. (If callers genuinely need to branch on error type, then add typed exceptions — but most catch blocks do the same thing: log + return fallback.)

### No Magic Numbers or Strings
Every value with meaning gets a name — constant, enum, or config value. Hardcoded thresholds, timeouts, and budgets belong in a constants file or validated config.

---

## Configuration

### Config Validation on Startup
**Node.js:** Zod schema that validates all env vars at import time. Fast-fail with clear error messages if required keys are missing or values are malformed (e.g. invalid URLs).

**Python:** Pydantic `BaseSettings` class that validates at import time.

Bad config caught at startup prevents 3 AM surprises when a code path finally hits it.

### Zero process.env Outside Config
All environment variable access goes through a single config module. Business logic receives config through dependency injection or import — never reads `process.env` directly.

---

## Resources & Async

### Context Managers for Resources (Python)
HTTP sessions, file handles, DB connections → `async with` / `with`. Wrap in dedicated classes. Node.js equivalent: explicit cleanup in `finally` blocks or AbortController patterns.

### Concurrent Operations Where Independent
`Promise.all` (JS) / `asyncio.gather` (Python) for independent tasks. Never await sequentially when tasks don't depend on each other.

### Semaphores Require Justification
Before adding concurrency limiters, document: what the bottleneck is, risk of unlimited concurrency, and recommended limit. No silent semaphores.

---

## Logging

### Errors + Diagnostics Only
Log errors with full context. Keep structured diagnostic logs that feed analysis (routing decisions, plan outcomes, timing). Remove routine info noise: startup confirmations, cache hits, per-request success messages. Every log line must be actionable or analytically useful.

---

## Testing

### Unit Tests for All New Code
**Node.js:** `node:test` with `mock.fn()` / `mock.method()` for spies/stubs. Use `esmock` for ESM module mocking (`mock.module()` is still experimental with known bugs as of Node 22/23). No sinon needed.

**Python:** pytest + pytest-mock.

If something is hard to test, the design needs to change — not the test. Tests use mocks and injected dependencies — never real databases, APIs, or file systems.

### Docstrings/JSDoc on All Public Methods
One line: what it does and why. Type annotations handle the contract, the docstring handles the intent.

### No Cheating on Pipeline Tests
Unit tests use mocks — that's normal. Pipeline tests must not.

When testing Oscar's actual pipeline (extraction, chat responses, assessments, document generation, agent behaviour), invoke the real configured LLMs. Do not simulate, paraphrase, or describe what the LLM would say.

This matters because the human currently has no way to test Oscar directly — no UI, no channels, no independent verification path. Every pipeline test you run is the only test that happens. If you substitute your own intelligence for a real invocation, the test is worthless and the human has no way to know.

If the actual output isn't what was expected, that's the test result — report it.

---

## Objectivity

### Flag What Doesn't Add Up
If something in PROJECT.md is wrong, contradictory, unclear, or will cause problems downstream — say so before building it. If the survey reveals that a planned approach won't work with what's actually on the VPS — say so. If a phase checkpoint is impossible to meet with the current architecture — say so. Do not silently work around bad instructions. Do not invent workarounds that hide a design flaw. Raise the issue, explain why, propose an alternative, and wait for the human to decide.

### Architecture Decision Records (ADRs)

**ADRs are the system of record for architectural and technology decisions.** When a significant decision is made — choosing a library, settling a design pattern, accepting a tradeoff, deferring a problem — an ADR captures it. Write the ADR **at the moment the decision is made**, not retrospectively. A decision that isn't written down within the same working session is effectively undocumented.

ADRs live in the `docs/adr/` directory. Use the format `NNN-short-title.md` (e.g. `001-openshell-governance.md`). Each ADR contains: the decision, the context (why it came up), the options considered, the choice made, and the consequences. ADRs are append-only — when a decision is superseded, write a new ADR that references the old one. Never delete or edit a past ADR. Keep each ADR under 50 lines.

If you find yourself making an architectural choice mid-task without writing an ADR, stop and write the ADR first.

---

## Git Discipline

- **Commit at logical checkpoints.** Every sprint closes with a commit that includes its PROJECT.md sprint-log entry. Every ADR is committed alongside (or immediately before) the change it documents — an ADR that sits uncommitted is not a decision of record.
- **Cross-sprint context files go to main directly.** PROJECT.md, SPRINT_LOG.md, CLAUDE.md, TODO.md, ADRs, and `docs/` do not ride on sprint feature branches. Only sprint-specific code and experiments land on feature branches and wait for sprint-outcome discipline to merge.
- **Push after every commit** to `Oscar-LQ/oscar-enterprise`. The remote is the only audit trail that survives a sandbox reset — do not accumulate local commits.
- **Commit messages state the why**, and reference the sprint number and ADR ID when relevant (e.g. `sprint-3: extract MemoryClient facade (ADR 007)`).

---

## CLAUDE.md Hygiene (Meta-Rules)

> Based on ETH Zurich study (Feb 2026): detailed context files increase agent costs 19-20% for only 4% success improvement. LLM-generated context files reduced success rates by 3%.

### Only Non-Inferable Constraints
This file should contain ONLY things the AI would get wrong without being told. Implementation details that live in code (thresholds, port numbers, file paths, function names) create **context rot** — stale descriptions of a codebase that has moved on.

### Target Under 200 Lines
Every line in this file competes for context window space. If it can be inferred from reading the code, delete it from here.

### Never Let the AI Generate This File
`/init`-generated CLAUDE.md files reduced task success rates by 0.5-2% in the ETH study. Write this file yourself. Keep it to constraints and invariants.

### Update In Real-Time
When a decision is made during a session, add it immediately — not at end of session. Delete decisions that are now baked into code.

---

## Refactoring Playbook (How to Apply These Rules to an Existing Codebase)

### Phase 0: Foundation (1-2 days, zero risk)
- Add `tsconfig.json` (strict, noEmit), `tsx`, `@types/node`
- Create `src/types/index.ts` with core interfaces (service contracts for DI)
- Purely additive — no existing files change

### Phase 1: Config Validation (1 day, low risk)
- Add Zod schema to config module. Fast-fail on bad env vars.
- Python: Pydantic BaseSettings with enums for fixed categories.
- Same exported config shape — zero breaking changes.

### Phase 2: Core Service Classes (3-5 days per module, medium risk)
- Pick stateful modules (ones with module-level `let` variables)
- Extract class with constructor-injected dependencies
- **Facade pattern**: re-export all original function names as wrappers around singleton
- Deploy and test each module independently before moving to the next

### Phase 3: Silent Catch Sweep (1-2 days, low risk)
- `grep -rn "catch\s*{}" src/` to find all bare catches
- Categorise: (a) legitimate fire-and-forget → annotate, (b) should log → add logger.warn, (c) hiding real failures → fix
- Most changes are adding one line of logging. Low risk, high diagnostic payoff.

### Phase 4: File Splits (as needed, low risk)
- Any file over 300 lines gets split along responsibility boundaries
- Do this when the file is next touched, not as a dedicated pass

### Verification at Every Phase
1. Run existing test suite — pass count should not decrease
2. Deploy to production, restart service
3. Exercise critical paths (send test messages, trigger overnight jobs)
4. Monitor for 24h before proceeding to next phase

### What NOT to Do (Over-Engineering That Doesn't Pay Off)
- **DI containers** (InversifyJS, Awilix, tsyringe) — manual injection is sufficient for any project under ~100K lines
- **Custom exception hierarchies** — logging with context beats `instanceof` checks for debugging
- **Zod without TypeScript** — Zod's killer feature is type inference, which does nothing without TS
- **Pydantic throughout Python internals** — 6.5x slower than dataclasses, use only at API boundaries
- **Full TypeScript migration as a big bang** — migrate file-by-file when each module is touched

---

## Framework Documentation Discipline

Read the framework's own documentation and skills before assuming how it behaves. OpenShell ships agent skills in its repository (`.agents/skills/` in the cloned repo, or fetched directly from github.com/NVIDIA/OpenShell); LangGraph, LangChain, and Deep Agents have current documentation at docs.langchain.com. When something fails or behaves unexpectedly, the first move is to read the relevant skill or documentation, not to guess. When proposing a fix, the proposed mechanism should be traceable back to documented behaviour. If the documentation is silent or contradicts what you observe, say so explicitly rather than papering over it with assumptions.
