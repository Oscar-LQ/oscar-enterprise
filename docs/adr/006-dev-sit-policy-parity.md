# ADR 006 — DEV and SIT OpenShell Policy Parity

- **Status:** Accepted
- **Date:** 2026-04-18
- **Scope:** Relationship between `policies/oscar-dev.yaml` and the to-be-written `policies/oscar-sit.yaml`
- **Supersedes:** none
- **Related:** ADR 002 (Claude Code allowances — build-time only), ADR 003 (SSH egress — mixed), ADR 004 (deploy trigger), ADR 005 (secrets/config split)

## Context

OpenShell enforces a default-deny network policy on every binary in the
sandbox. Egress bugs manifest as denied requests — sometimes obvious
(HTTP 403 from the proxy), sometimes subtle (a client library retries
silently and then times out). Such bugs are cheap to find in DEV and
expensive to find in SIT.

If DEV is materially more permissive than SIT, a whole class of bug will
not surface until SIT. If DEV is materially more restrictive, DEV
development stalls on allow-rules SIT doesn't care about. Either way,
DEV stops being a useful proxy for SIT.

The invariant that matters is **runtime parity**, not file-level
identity. DEV legitimately needs build-time egress (Claude Code reaching
Anthropic, git pushing to GitHub) that SIT must not have.

## Decision

**`policies/oscar-sit.yaml` is derived from `policies/oscar-dev.yaml` by
subtraction, not rebuilt from scratch.** The rules:

1. **Start from the DEV file** when writing the SIT file.
2. **Strip DEV-only build-time blocks.** The `claude_code` block (ADR
   002) is build-time-only and must not appear in SIT. The `github_ssh`
   block (ADR 003) is build-time for Oscar source; keep it in SIT only if
   the deploy trigger (ADR 004) needs it at runtime.
3. **Runtime allow-rules must exist in both files or neither.** If Oscar
   needs to reach `api.<llm-provider>.com` at runtime in SIT, DEV must
   allow the same endpoint. If DEV doesn't need it, SIT shouldn't
   either.
4. **Deviations require an ADR.** A runtime allow-rule present in only
   one environment must be justified in a new ADR explaining why the
   bug-surfacing cost of the asymmetry is accepted.

Rejected:

- **Identical files.** Not workable — DEV needs build-time rules (Claude
  Code, GitHub SSH for source push) that SIT must not have.
- **SIT as the source of truth, DEV derives by addition.** Formally
  equivalent but inverts the workflow — every runtime change would be
  authored in SIT first. Rejected because iteration happens in DEV.

## Consequences

- **Pro:** the "works in DEV, fails in SIT" failure mode is preempted.
  Denials surface in DEV where they're cheap to fix.
- **Pro:** the two policy files become a diffable audit artefact. `diff
  oscar-dev.yaml oscar-sit.yaml` reveals exactly which rules are DEV-only
  (and which, rarely, are SIT-only) at a glance.
- **Con:** DEV carries SIT's runtime rules even when DEV doesn't need
  them for experimentation. Mitigated by the rule applying only to
  *runtime* traffic; build-time DEV allowances (Claude Code, GitHub SSH)
  remain permissive.
- **Con:** a new runtime capability must land in both files in the same
  PR, or parity is temporarily broken. Accepted as the cost of the
  invariant.
- **Follow-up:** once `policies/oscar-sit.yaml` exists, add a
  pre-commit or CI check that fails when the two files diverge on rules
  not explicitly tagged as build-time. Tagging mechanism TBD — likely a
  YAML comment convention checked by a small script. Capture in its own
  ADR when implemented.
