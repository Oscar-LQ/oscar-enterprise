# ADR 015 — Playbook Rule Hardcoded in the Specialist's System Prompt (Sprint 9)

- **Status:** Accepted
- **Date:** 2026-04-18
- **Scope:** Where Rule GL-001 (and, by extension, future single-rule specialist prompts) lives until persistent playbook storage ships
- **Supersedes:** none
- **Related:** ADR 013 (structured output), PROJECT.md § What Oscar Does → Learning, Sprint 9 brief

## Context

Oscar's distinguishing feature (PROJECT.md) is a client-specific
playbook that the system learns over time. Sprint 9's accept/reject
specialist needs *one* rule to exercise the three decision paths
(Rule GL-001 — Governing Law: England and Wales, with Scotland/NI/IE as
counter-cases). Playbook persistence (database-backed, editable by the
human, versioned, audited) is a multi-sprint capability; Sprint 9 must
ship without it.

Options for where the rule lives:

1. Hardcoded in the specialist's system prompt.
2. A YAML/JSON file read at build time and interpolated into the prompt.
3. A placeholder database table with one row.
4. A "rule registry" module that future playbook storage replaces.

## Decision

**The rule text lives inline in the accept/reject specialist's system
prompt, inside `accept_reject_reasoner.py`.** No separate file, no
registry abstraction, no stub database table.

Rationale:

- Sprint 9 has exactly one rule. Building a registry for one rule is
  over-engineering per CLAUDE.md's "nothing here is inferable from
  reading the code itself" principle inverted: when the rule *is* the
  code, there's no abstraction worth the ceremony.
- The rule and the specialist's prompt are coupled — changing the rule
  changes the decision branches the prompt must handle. Keeping them in
  one file makes the coupling obvious.
- Playbook persistence is not a Sprint 9 deliverable. Writing a
  registry now commits us to interface decisions (rule id format,
  versioning, who can edit) that should emerge from the persistence
  sprint's requirements, not from an ad-hoc decision made under
  Sprint 9's scope.

Rejected:
- **YAML file loaded at build time.** One file for one string. Adds a
  read path and a parser; saves nothing.
- **Placeholder rule registry (`rules/gl_001.py`).** Premature
  abstraction. The registry shape has to match the playbook storage
  shape, and we don't know the storage shape yet.
- **Playbook table in Postgres.** The full path forward. Deferred
  pending a playbook sprint; a Postgres dependency is not on Sprint 9's
  critical path.

## Consequences

- **Pro:** adding the second rule is trivial (extend the specialist's
  prompt or fork a new specialist) — no abstraction to migrate around.
- **Pro:** the rule text sits next to the decision logic. Reviewing the
  specialist means reading one file.
- **Pro:** zero net-new infrastructure. The sprint's code footprint is
  the specialist's Python module plus the agent wiring.
- **Con:** multi-rule reasoning will need a shape change. When a
  specialist must apply two rules (e.g. governing law AND jurisdiction
  clauses jointly), stuffing both into one prompt's step-by-step block
  stops being clean; that is the trigger to introduce rule-as-data.
- **Con:** the rule is only discoverable by reading the specialist's
  source, not from a declared inventory. For an operator asking "what
  does Oscar know today?", the answer lives in code, not data. Fine
  for Sprint 9's single-rule scope, a problem by about rule five.
- **Forward trigger:** the first sprint that needs two rules in one
  specialist OR a rule shared across specialists OR human-editable
  rules is when this ADR is superseded. A new ADR will then record the
  playbook-storage decision (Postgres table? YAML in the repo? both?)
  and the migration of Rule GL-001 into that store.
