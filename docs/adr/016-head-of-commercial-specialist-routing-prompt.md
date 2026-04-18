# ADR 016 — Head of Commercial's Specialist-Routing Prompt Pattern

- **Status:** Accepted
- **Date:** 2026-04-18
- **Scope:** Shape of the Head of Commercial's system prompt once it has functional specialists to route to
- **Supersedes:** amends Sprint 7's HOC prompt (no prior ADR)
- **Related:** ADR 010 (per-agent allocation), ADR 013 (structured output), ADR 014 (nested delegation), Sprint 7 HOC prompt, Sprint 9 brief

## Context

Sprint 7's Head of Commercial had no sub-agents — its prompt was a
short, directional "you are the Head of Commercial, describe what you
would do, do not perform the work." Sprint 9 introduces the first
functional specialist underneath (`accept-reject-reasoner`). HOC now
needs to:

1. Decide when an inbound commercial task is in the specialist's scope
   (single proposed markup + applicable playbook rule → accept/reject
   decision) and when it is not (all other commercial work).
2. Delegate cleanly to the specialist via the `task` tool when in scope.
3. Relay the specialist's structured JSON back to the General Counsel
   in a form GC can synthesise for the user.

Deep Agents' `SubAgentMiddleware` already injects an "Available
subagent types" block into the system prompt automatically
(`subagents.py:522-524`). The `TASK_SYSTEM_PROMPT` auto-appended by
middleware covers the generic when-to-use-task guidance. HOC's custom
prompt therefore does not need to re-explain what `task` is; it needs
to specify *which* specialist to pick for *which* shape of input — the
orchestrator-to-specialist mapping.

## Decision

**HOC's system prompt follows a three-part pattern**, matched to what
`SubAgentMiddleware` already provides:

1. **Role line** — one sentence naming the department and its scope.
2. **Routing table** — explicit mapping from input shape to specialist,
   phrased as "when X, delegate to Y via the task tool." Naming the
   specialist by its `name` field (not its description) because that is
   the exact string the `task` tool expects in `subagent_type`.
3. **Relay instructions** — how to reconstruct the specialist's
   structured JSON into a prose reply for the parent orchestrator.

The first version of this prompt, as built for Sprint 9:

```
You are the Head of Commercial in an in-house legal function. You are
responsible for commercial contract work — NDAs, MSAs, SaaS agreements,
procurement contracts, amendments, and similar.

Staffed specialists under you (subagent names to use with the `task`
tool):
  - accept-reject-reasoner: decides accept / reject / counter on a
    single proposed contract markup against a playbook rule. Use this
    when you receive a description of one markup plus the governing
    playbook rule and a decision is needed.

Routing rules:
  - If the task describes a single proposed contract markup and a
    playbook rule applies to it, delegate to accept-reject-reasoner.
    Pass the markup description and the rule to the specialist verbatim.
  - Otherwise, respond plainly (one or two sentences) describing what
    you would do. Do not attempt to perform the work itself. No other
    specialists are staffed for this sprint.

When accept-reject-reasoner returns a structured decision (JSON with
decision, reason, counter_language), relay the decision to the General
Counsel in plain English: state the decision, give the reason, and
include the counter_language verbatim when the decision is "counter".
```

Rejected:
- **Let HOC figure out routing from the specialist `description`
  alone** (what `SubAgentMiddleware` auto-injects). Works for simple
  single-specialist cases but does not say which *input shape* maps to
  which specialist — risks HOC under- or over-delegating. The cost of
  explicit routing rules is ten lines; the cost of wrong routing is a
  test failure.
- **Put the relay format in the specialist's description instead.** The
  specialist does not know what its *parent* will do with the decision;
  formatting for the parent is the parent's concern. Keeps schema
  evolution localised.
- **Carry the specialist's JSON straight up to GC by giving HOC its own
  `response_format`.** Technically clean (JSON preserved across three
  levels) but forecloses HOC's future role of composing decisions from
  multiple specialists. The prose-relay form lets HOC later say "the
  accept/reject reasoner decided X; the defined-terms auditor flagged
  Y; on balance we propose Z." Keep it prose.

## Consequences

- **Pro:** adding a second specialist (comment-responder, drafter,
  auditor) is one routing-rule addition plus one description line —
  same structural shape.
- **Pro:** the mapping from input to specialist is visible in one file.
  An operator debugging routing reads the prompt and knows the triage
  logic without having to inspect agent internals.
- **Pro:** the relay instruction treats the specialist's JSON as a
  contract — HOC parses `decision` / `reason` / `counter_language` by
  name, not by guessing the shape from prose.
- **Con:** the prompt must stay in sync with the specialist's
  `response_format` schema. If a future sprint renames or removes a
  field, the prompt update is in the same commit. Mitigated by keeping
  the schema and the prompt text in the same experiment module for now.
- **Con:** once HOC routes between multiple specialists AND handles
  freeform commercial questions, the prompt will grow past the "short
  and directional" size limit. Split-point is when the routing rules
  exceed ~5 items or when the pattern of "input shape → specialist"
  becomes a decision tree rather than a flat table. A new ADR will
  record that split.
