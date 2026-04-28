# ADR 020 [Redline] — Plan Data Contract

**Status:** Accepted (Sprint M3, 2026-04-28; promoted from PLACEHOLDER reserved by Sprint 10P).

## Context

ADR 019 establishes that the redline pipeline runs an LLM planner and an LLM executor. The two are coupled by a data contract: the planner emits, the executor consumes (for counter-propose), and `pipeline.apply_decisions` orchestrates the rest. The contract was implicit across 10G/10H/10O/10P — encoded in `planner_prompt.txt`, `executor_prompt.txt`, and `response_parser.py`'s parser logic, but never written down as a decision of record. M3 lifts the pipeline to a first-class tool callable from Oscar; the contract therefore needs an explicit ADR so changes are deliberate rather than incidental.

## Decision

The planner emits a single JSON object with two keys:

- `decisions: list[NegotiationDecision]` — one entry per pending tracked change in the state-of-play. Each entry carries:
  - `change_id: str` — `"Chg:N"` or `"Com:N"` from the state-of-play. Display-only; Adeu wiring uses the matching `ooxml_id` (CLAUDE.md banked rule from 10P Phase 2).
  - `action: Literal["accept", "counter_propose", "comment", "reply", "no_action"]`. `RejectChange` is structurally excluded — disagreement is `counter_propose` (rule 3, planner_prompt.txt).
  - For `accept`: `comment_text: str` (mandatory non-empty per rule 4 — every accept carries a paragraph-anchored comment).
  - For `counter_propose`: `position: str` (one-line tactical position), `instruction: str` (drafting direction for the executor), `preserve: list[str]` (phrases the executor's `new_text` must contain verbatim), `comment_text: str` (optional).
  - For `comment` (standalone): `anchor_change_id: str`, `comment_text: str`.
  - For `reply`: `comment_id: str`, `reply_text: str`.
  - For `no_action`: `reasoning: str` (audit trail one-liner).
- `cross_clause_notes: list[str]` — observations spanning multiple decisions (e.g. why a broadening in §3 is countered while a related change in §7 is accepted).

The executor receives one decision plus its matching state-of-play entry and emits a single JSON object: `{"new_text": str, "comment": str, "parse_method": str}`. The `parse_method` is a diagnostic field naming which fallback layer parsed the response (direct, fenced-block, or repair).

Parsing has three layers in `response_parser.parse_decisions_response` and `parse_single_edit_response`:
1. Direct JSON parse of the raw response.
2. Fenced-block extraction — pull JSON out of a ```json ... ``` block when the model wraps despite instruction.
3. Repair — minimal cleanup (trailing comma removal, obvious whitespace fixes) followed by re-parse.

Failures cascade through the layers; a parse failure at all three layers raises `ValueError` and the pipeline reports an early-exit.

## Options considered

- **Free-form prose decisions.** Rejected — bundles judgement and drafting; impossible to dispatch on action types without re-parsing.
- **Pydantic-typed schema with strict validation.** Rejected — model output drifts; strict validation produces brittle pipelines. The three-layer parser tolerates light drift while still catching structural errors.
- **Per-decision separate planner calls (one LLM call per change).** Rejected — destroys the cross-clause reasoning the planner uses to coordinate decisions across related changes (e.g. counter §3, accept §7 because the cross-reference resolves).

## Consequences

- The data contract is the integration boundary between the planner prompt, the executor prompt, the dispatcher (in `pipeline.apply_decisions`), and the M3 tool wrapper. Changes propagate to all four; an ADR amendment is required when the schema changes.
- Future playbook-aware planners (later sprint) must conform to this schema. The four-context-layer planner prompt restructure on the paused 10Q branch (`bd1f236`) was developed against this contract and would carry forward unchanged at the data-contract layer.
- Adding a new action type (e.g. `escalate_to_partner`) requires (a) updating the schema in `planner_prompt.txt`, (b) adding a dispatch branch in `pipeline.apply_decisions`, (c) updating `response_parser` if a new field shape is needed, and (d) amending this ADR.
