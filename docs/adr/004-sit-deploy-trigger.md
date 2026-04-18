# ADR 004 — SIT Deployment Trigger

- **Status:** Accepted
- **Date:** 2026-04-18
- **Scope:** Mechanism that moves code from `Oscar-LQ/oscar-enterprise` `main` onto the SIT VPS
- **Supersedes:** none
- **Related:** ADR 002 (Claude Code allowances — DEV-only), ADR 003 (SSH egress)

## Context

The agreed topology is DEV (this sandbox) → GitHub `main` → SIT VPS, with
GitHub as the sole artefact-transfer medium between environments. No
artefact registry, no container image pipeline, no external CI cluster.
The SIT VPS runs the same OpenShell governance as DEV but with
SIT-specific configuration.

A deployment trigger is needed — a mechanism that pulls `main` onto the
SIT VPS and restarts the Oscar process. Options range from a human
running `git pull && restart` to GitHub Actions SSHing in, to ArgoCD-style
continuous reconciliation.

## Decision

**Phase A (current, until SIT is stable):** manual deploy. An operator on
the SIT VPS runs:

```
git -C /opt/oscar pull && systemctl restart oscar
```

(Exact paths TBD at SIT provisioning.)

**Phase B (when manual friction bites):** webhook-triggered pull. A
GitHub `push` webhook on `main` hits a small listener on the SIT VPS that
runs the same two commands. The listener lives in this repo and runs
inside the same OpenShell sandbox as Oscar itself.

Phase B is triggered by any of: more than one manual deploy per day, OR
the SIT operator is not the DEV author, OR a second client VPS comes
online.

Rejected:

1. **GitHub Actions SSHing into SIT for every merge.** Adds a fourth
   credential surface (CI runner → SIT), new OpenShell policy work for
   inbound SSH, and a deployment path that is not the same command a
   human would type to debug. Rejected as premature for one-VPS-per-client.
2. **Container-registry / image-based deploys.** The unit of deployment
   is currently a source tree, not an image. Revisit when multi-client
   deployment is active or when BYOC sandbox images (ADR 002 follow-up)
   ship.

## Consequences

- **Pro:** zero new infrastructure, zero new credentials beyond the
  deploy key ADR 003 already delivered — the SIT VPS reuses the same
  mechanism.
- **Pro:** the deploy command is the same command an operator would type
  to debug. No opaque pipeline between merge and running code.
- **Con:** a merged commit on `main` does not reach SIT automatically.
  Acceptable while DEV and SIT are operated by the same person.
- **Con:** rollback is `git reset --hard <sha> && restart`, executed by a
  human. Mitigated by PROJECT.md's append-only audit discipline; not
  mitigated for speed of rollback.
- **Follow-up (defer to Phase B trigger):** design the webhook listener
  as its own `policies/` sub-policy and capture in a new ADR.
