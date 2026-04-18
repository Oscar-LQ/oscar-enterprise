# ADR 002 — Claude Code Network Policy for oscar-dev Sandbox

- **Status:** Accepted
- **Date:** 2026-04-18
- **Scope:** `policies/oscar-dev.yaml` (`claude_code` block)
- **Supersedes:** none
- **Related:** ADR 001 (OpenShell foundation — pending)

## Context

Claude Code 2.1.113 self-updates into `/sandbox/.local/share/claude/versions/<version>/`,
outside the `/usr/local/bin/claude` path pinned in the original policy. OPA falls back
to matching versioned traffic against the `codex` policy (shared `/usr/bin/node` binary),
which denies every Anthropic endpoint. While fixing the binary-path issue, further
denies surfaced for `mcp-proxy.anthropic.com`, `downloads.claude.ai`, and
`http-intake.logs.us5.datadoghq.com`. Each needed an explicit allow/deny decision.

## Decision

1. **Allow** `mcp-proxy.anthropic.com:443` (read-write) — first-party Anthropic
   infrastructure, required for MCP.
2. **Allow** `/sandbox/.local/share/claude/versions/**` as a `claude_code` binary path —
   unblocks 2.1.113 and future self-extracted versions.
3. **Deny** `downloads.claude.ai` — version control happens through sandbox image
   rebuilds, not agent self-patching. A legal product requires explicit control over
   which version is running; self-update is an ungoverned code path.
4. **Deny** `http-intake.logs.us5.datadoghq.com` — all outbound flows in Oscar's
   eventual production sandboxes must be auditable and justifiable. Third-party
   telemetry to Datadog is neither.

## Consequences

- 2.1.113 reaches `api.anthropic.com`, `raw.githubusercontent.com`,
  `storage.googleapis.com`, `platform.claude.com`, and `mcp-proxy.anthropic.com`.
- Version upgrades require rebuilding the sandbox image with a pinned Claude Code
  version. Ad-hoc `claude update` inside the sandbox will fail fast (by design).
- The `/sandbox/.local/share/claude/versions/**` glob is a known DEV breadth
  concession: any binary written under that user-writable path inherits the
  `claude_code` policy. Mitigated by the filesystem and container boundary but not
  eliminated.
- **Follow-up (deferred to Stage 1 closure):** replace this glob with a BYOC sandbox
  image shipping Claude Code at a fixed, root-owned path (e.g. `/opt/claude/bin/claude`)
  that the sandbox user cannot write to. Then the binary allowlist returns to a single
  explicit path.
- Datadog and self-update blocks may need revisiting if Anthropic makes either
  load-bearing for a feature we depend on; revisit at each Claude Code major upgrade.
