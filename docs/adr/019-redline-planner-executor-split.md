# ADR 019 [Redline] — Planner / Executor Split Pattern

**Status:** Accepted (Sprint M3, 2026-04-28; promoted from PLACEHOLDER reserved by Sprint 10P).

## Context

Across redline-track sprints 10F through 10M the empirical evidence was consistent: a single LLM asked to read tracked changes, decide a position per change, and produce byte-precise output bundles into wholesale rewrites. The model conflates the *judgement* problem (does this change deserve accept / counter / comment?) with the *drafting* problem (what should the replacement text say?). Wholesale rewrites lose the surgical-shape signal Adeu's MCP tooling depends on — the OOXML layered structure that survives a counterparty round-trip.

10G/10H proposed a planner-executor split: one LLM emits structured per-change decisions, a separate executor (LLM or code) produces the byte-precise text. 10L explored an LLM planner with a code executor (Vibe-style word-diff via `diff_cleanupSemantic`); rejected because diff_cleanupSemantic collapses short shared runs and produces wholesale shapes for narrow word-swaps. 10O committed to LLM planner + LLM executor and shipped the first working separation. 10P validated the pattern at scale (18 changes, 16 accept + 2 counter-propose, all comments landed, partner-shape across decisions).

M3 carries the pattern forward by wrapping 10P's pipeline as a LangChain tool. The ADR exists because the pattern is now load-bearing across multiple call sites and needs a written architectural decision rather than implicit precedent.

## Decision

Two-LLM split for any redline pipeline that decides per-change positions against a brief.

- **Planner.** Reads the brief, the state-of-play (the counterparty's tracked changes, structured), and the original document text. Emits a JSON list of `NegotiationDecision` objects — one per pending change — with explicit fields naming the action (accept / counter_propose / comment / reply / no_action), the tactical position, the drafting instruction (for counter_propose), and any preserve-list phrases the executor must keep verbatim. Frontier reasoning model.
- **Executor.** Receives one decision plus its matching state-of-play entry. Emits one JSON object with `new_text` and `comment`. Capable-but-cheaper model. Called only for `counter_propose` decisions; mechanical actions (accept, no_action, comment, reply) skip the executor.

The data contract between them is fixed (ADR 020). Stage A/B/C application is orchestrated by `pipeline.apply_decisions` and is independent of the LLM split.

## Options considered

- **Single-LLM end-to-end.** Rejected by 10F-10M evidence (wholesale rewrites lose surgical shape).
- **LLM planner + code executor (Vibe-style).** Rejected by 10L: `diff_cleanupSemantic` collapses short shared runs, producing wholesale OOXML for narrow word-swaps.
- **LLM planner + LLM executor.** Chosen — 10O/10P validated.

## Consequences

- The planner prompt carries the strategic frame; the executor prompt carries the byte-precision frame. Each prompt iterates independently against its own evaluation surface. Conflating the two slows iteration on either.
- Per-role model allocation (ADR 010) follows the split: `OSCAR_LLM_REDLINE_PLANNER_*` for the planner, `OSCAR_LLM_REDLINE_EXECUTOR_*` for the executor. M3 promotes both env-var triples to `.env.example` on `main` (they previously lived only on feature branches).
- The pattern is reusable. Any future "decide-per-unit then draft-per-unit" pipeline (e.g. responding to comment threads, reviewing playbook adherence, composing partner emails) can adopt the same split.
- Carries forward into M3's redline tool wrapper unchanged — `run_redline` is a thin wrapper over the existing 10P pipeline; the split is not re-litigated at the tool boundary.
