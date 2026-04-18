# ADR 005 — Secrets vs. Config Split

- **Status:** Accepted
- **Date:** 2026-04-18
- **Scope:** Where configuration and credentials live across DEV, SIT, and future client VPS environments; how environment selection happens at startup
- **Supersedes:** none
- **Related:** ADR 003 (sandbox deploy key — a canonical secret), ADR 004 (deploy trigger)

## Context

PROJECT.md establishes two things relevant here: OpenShell policy YAMLs
are version-controlled in the repo, and client-specific configuration
lives in `oscar_config.yaml` (not in a tenants table). It does not say
where **secrets** (LLM API keys, deploy keys, database passwords,
third-party tokens) live, nor how environment-specific config (DEV vs.
SIT vs. client-N) is selected at startup.

Without a rule, secrets will leak into `oscar_config.yaml` and into git
history, environment divergence will happen by accident, and the eventual
migration to multi-client will force a retrofit.

## Decision

A three-layer split:

**1. In the repo (version-controlled):**

- `oscar_config.yaml` — default, non-secret runtime configuration. One
  file, with environment-scoped overrides inside it if needed.
- `policies/` — all OpenShell policy YAMLs. One file per environment
  (e.g. `oscar-dev.yaml`, `oscar-sit.yaml`, `oscar-client-N.yaml`).
- `.env.example` — template enumerating every required environment
  variable with a safe placeholder and a one-line description.

**2. On each VPS filesystem (not in repo, not in any image):**

- `.env` — populated by the VPS operator at provisioning. Contains every
  secret: LLM API keys, database password, third-party tokens. Readable
  only by the Oscar service user.
- The SSH deploy key (per ADR 003) follows the same model — present on
  each VPS, never in git.

**3. Environment selection at startup:**

- A single `OSCAR_ENV` variable (values: `dev`, `sit`, `client-<name>`)
  selects which `policies/` file loads and which section of
  `oscar_config.yaml` applies.
- The config layer validates at startup (Zod or Pydantic per CLAUDE.md)
  and fails fast on missing secrets or unknown environments.

Rejected:

- **Secrets in `oscar_config.yaml` with a gitignored overrides file.**
  Overrides drift silently across environments because there is no
  authoritative list. `.env.example` makes required keys explicit and
  reviewable in PRs.
- **Vault / HashiCorp Vault / cloud KMS.** Right answer for multi-client
  at scale with operator-less rotation. Overkill at DEV/SIT/first-client
  cost. Revisit when secret count per environment crosses ~20 or when
  audit rotation becomes a compliance requirement.
- **One policy YAML that branches on `OSCAR_ENV` internally.** Policy is
  the security boundary; reviewing it must not require reading
  conditional logic. One file per environment, diffable against the
  others.

## Consequences

- **Pro:** zero secrets in git history, ever. `.env.example` tells a new
  operator exactly what to provision without leaking values.
- **Pro:** PROJECT.md's one-VPS-one-client isolation extends cleanly —
  each client gets its own `.env` and its own `policies/` file, no
  cross-contamination possible through repo state.
- **Con:** operator error on first provisioning yields an Oscar that
  doesn't start. Mitigated by fast-fail startup validation.
- **Con:** rotating a secret is a per-VPS manual step. Acceptable at
  current scale; revisit when fleet size or rotation cadence changes.
- **Follow-up:** `policies/oscar-sit.yaml` is written at SIT provisioning
  using `policies/oscar-dev.yaml` as the starting point (per ADR 006).
