# ADR 018 — Facilitator vs. Wrapper Boundary for Adeu Tools

- **Status:** Accepted
- **Date:** 2026-04-19
- **Scope:** Principle governing when Oscar code is allowed to sit between an agent and Adeu's native surface. Applied first to the Sprint 10D `insert_text` tool.
- **Supersedes:** none
- **Related:** Sprint 10A (SDK-vs-wrapper decision), Sprint 10C idioms (pure-insertion via prefix-match), Sprint 10D brief

## Context

Sprint 10C's architectural stance (confirmed in the Sprint 10D brief) is
"expose Adeu's API, don't wrap it". The redline-specialist gets Adeu
operations as Deep Agents `@tool` functions mirroring Adeu's signatures
directly. The agent learns Adeu's idioms through prompting. No
intent-shaped abstractions. No translation layer.

This stance prevents the class of failure that broke Claude-Plugin-MCP
at Adeu's 0.9 → 1.0 bump (the wrapper shielded the agent from upstream
changes, then the wrapper itself broke). It also prevents semantic
drift (a wrapper's intent-shaped API can diverge from Adeu's actual
behaviour, so prompt guidance calibrated to the wrapper becomes
brittle).

But Sprint 10D surfaces a borderline case: pure insertion. Adeu 1.1.0
has no pure-insertion primitive; the SDK idiom is prefix-match
(`new_text.startswith(target_text)` — see Sprint 10B finding #1,
`adeu-idioms.md` §"How to insert new text"). The agent has to
construct `new_text = anchor + content` manually. A naive reading says
"teach the prompt"; a strict reading says "no wrapping, full stop".

The Sprint 10D brief splits the hair:

> `insert_text(anchor_text, new_text, author)` — uses Adeu's startswith
> idiom internally. Anchor is existing text; new_text begins with
> anchor, appends the insertion. **This is a minor facilitator (not a
> wrapper that changes semantics — just a convenience so the agent
> doesn't need to hand-construct the overlap).**

The brief asks: is this a wrapper in disguise? Decide and surface.

## Decision

**A function is a *facilitator* (permitted) if and only if:**

1. It exposes semantics Adeu already supports natively — nothing more,
   nothing less.
2. It removes only mechanical assembly steps, not judgement steps.
3. Its failure modes are a strict subset of the underlying Adeu
   operation's failure modes.
4. If Adeu's underlying operation changes, the facilitator is trivially
   rewritten — no stored intent to preserve.

**A function is a *wrapper* (disallowed without separate ADR) if any
of:**

1. It invents a new operation not in Adeu's API.
2. It makes a judgement call the agent should be making (e.g., picking
   an anchor automatically, choosing between insert and modify on the
   agent's behalf).
3. It handles errors in a way that hides information from the agent.
4. It accumulates state across calls beyond what Adeu's round-trip
   cycle already does.

**`insert_text` passes all four facilitator tests:**

- Semantics: `ModifyText(target_text=anchor, new_text=anchor +
  new_text)` — the exact prefix-match idiom Adeu supports at
  `engine.py:739-743`. No new behaviour.
- Mechanical only: it concatenates `anchor + new_text`; the agent
  specifies both. Judgement (which anchor, which content) stays with
  the agent.
- Failure modes: ambiguous anchor, unmatched anchor — both are
  Adeu's native `BatchValidationError`. The facilitator does not add
  new failure categories.
- Adeu-change resilience: if Adeu ever introduces a pure-insertion
  primitive, `insert_text` rewrites to call it directly. No stored
  intent to migrate.

**`insert_text` is therefore an accepted facilitator.** It is
implemented in Sprint 10D alongside `modify_text` and `add_comment`.

Rejected:

- **Teach the prompt to hand-construct the overlap.** Works, but every
  time the agent inserts text it has to assemble `anchor +
  new_text` correctly. MiniMax, per Sprint 9, is unreliable on
  mechanical output discipline — one-off concatenation bugs
  ("anchor_text" vs. "anchor" — the agent forgets the trailing space,
  forgets the trailing full stop, etc.) burn iterations. The
  facilitator removes a mechanical failure surface; the prompt is
  free to focus on judgement.
- **Introduce an `insert_after`-shaped tool with different semantics
  than prefix-match** (e.g., "anchor stays untouched; new text
  appears in a new paragraph after the anchor"). This would be a
  wrapper: it invents semantics Adeu doesn't have. If future sprints
  want cross-paragraph insertion with different anchoring, they write
  a separate ADR.

## Consequences

- **Pro:** The tool surface for Sprint 10D stays three functions, each
  aligned 1:1 with an Adeu capability. Prompt guidance maps cleanly:
  "to modify, call modify_text; to insert, call insert_text; to add a
  standalone comment, call add_comment".
- **Pro:** The facilitator-vs-wrapper distinction is now a rule, not a
  case-by-case judgement. Future sprints can apply the four tests
  without re-litigating the principle.
- **Pro:** Adeu version bumps that change the pure-insertion pathway
  require a one-line rewrite of `insert_text`, not a prompt rewrite.
- **Con:** The rule is a convention, not a compile-time check. A
  future sprint could add a tool that crosses the wrapper boundary
  (e.g., "smart_edit" that picks insert vs. modify on the agent's
  behalf) without tripping any guardrail. Discipline is human — the
  four tests must be applied when each new tool is proposed.
- **Con:** The four tests use the word "judgement", which is itself a
  judgement. If a future sprint disputes whether a proposed tool is
  doing "mechanical assembly" or "making a judgement call", that
  dispute is resolved by superseding this ADR, not by hand-waving.
