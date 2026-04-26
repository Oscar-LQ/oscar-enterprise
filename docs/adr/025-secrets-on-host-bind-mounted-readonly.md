# ADR 025 [Infrastructure] — Secrets on host, bind-mounted read-only

**Status:** Accepted (Sprint M2 Phase 2, 2026-04-26).

## Context

Sprint 3 established `.env` inside the sandbox as the canonical secrets carrier. Phase 0 addendum § 7.2 surfaced two facts that made this insufficient for the Slack + AgentMail tokens M2 introduces:

- The Sprint 3 `.env` lives in the sandbox's writable overlay — reachable to anything inside, with no separation between "secret" and "developer-local config".
- There is no host-side `OSCAR_*` secrets file today, and no systemd unit running Oscar Enterprise. OpenShell manages the sandbox lifecycle itself, so the "env-injected by main-VPS at sandbox startup" mechanism originally proposed in M2 § 6.4 has no concrete carrier.

A third fact surfaced during Phase 2 implementation: OpenShell's `FilesystemPolicy` schema (`crates/openshell-sandbox`, `architecture/sandbox.md`) has only `read_only` / `read_write` (Landlock allowlists) and `include_workdir`. **There is no `bind_mounts` field**; OpenShell does not mount filesystems, only restricts what the sandboxed process can read or write within its existing mount namespace. The bind-mount must therefore be established at the launcher level (k3s pod spec, Docker `-v`, systemd `BindReadOnlyPaths=`), not in `policies/oscar-dev.yaml`.

## Decision

**Secrets live on the host, bind-mounted read-only into the sandbox.**

- **File:** `/etc/oscar/oscar.env`. Root-owned, mode 0600. Owned (creation, write, rotation) by main-VPS Claude Code.
- **Format:** `KEY=VALUE` per line; `#` comments and blank lines ignored. A single matching pair of `'`/`"` quotes around the value is stripped.
- **Bind-mount:** established by the **host launcher** (out-of-band from this repo). Concretely whichever of: a Kubernetes `hostPath` volume on the sandbox pod, a Docker `-v /etc/oscar/oscar.env:/etc/oscar/oscar.env:ro`, or a systemd `BindReadOnlyPaths=/etc/oscar/oscar.env` on the unit that spawns OpenShell.
- **Landlock allowlist:** `/etc/oscar/oscar.env` is added to `policies/oscar-dev.yaml` `filesystem_policy.read_only` as an explicit-intent entry. Technically redundant (since `/etc` is already in the allowlist), but it documents the intent and survives any future narrowing of the `/etc` allowlist.
- **Loader:** `src/shared/secrets.py:load_host_secrets()` reads the file once at runtime startup and populates `os.environ`. Default behaviour does not override pre-set env vars — lets developer-local exports beat the host file for non-prod testing. Phase 3 runtime entry point calls this before instantiating any `Settings(BaseSettings)` class.

## Options considered

- **Keep Sprint 3 `.env`** — rejected per Phase 0 addendum: writable-overlay exposure plus no host-side rotation story.
- **Inject env vars from main-VPS at sandbox startup** — original § 6.4 framing; no concrete carrier in the OpenShell-managed deployment.
- **Add a bind-mount to the policy YAML** — rejected on inspection of OpenShell's schema (above); OpenShell does not mount, only restricts.

## Consequences

- main-VPS Claude Code owns: creating `/etc/oscar/oscar.env`, writing token values, rotating, and adding the bind-mount to whatever launcher spawns the sandbox.
- Sandbox-Claude-Code owns: the Landlock allowlist entry, the `load_host_secrets()` loader, and the verification step at Phase 2 close (`test -n "$OSCAR_SLACK_BOT_TOKEN"` from inside the sandbox returns truthy + a live Slack `auth.test` succeeds).
- Sprint 3's `.env` pattern remains usable for developer-local non-secret configuration only.
