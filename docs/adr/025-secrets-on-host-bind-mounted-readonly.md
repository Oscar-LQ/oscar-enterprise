# ADR 025 [Infrastructure] — Secrets on host, mounted as a Kubernetes Secret-volume into the sandbox

**Status:** Accepted (Sprint M2 Phase 2, 2026-04-26).

## Context

Sprint 3 established `.env` inside the sandbox as the canonical secrets carrier. Phase 0 addendum § 7.2 surfaced two facts that made this insufficient for the Slack + AgentMail tokens M2 introduces:

- The Sprint 3 `.env` lives in the sandbox's writable overlay — reachable to anything inside, with no separation between "secret" and "developer-local config".
- There is no host-side `OSCAR_*` secrets file today, and no systemd unit running Oscar Enterprise. OpenShell manages the sandbox lifecycle itself, so the "env-injected by main-VPS at sandbox startup" mechanism originally proposed in M2 § 6.4 has no concrete carrier.

A third fact surfaced during Phase 2 implementation: OpenShell's `FilesystemPolicy` schema (`crates/openshell-sandbox`, `architecture/sandbox.md`) has only `read_only` / `read_write` (Landlock allowlists) and `include_workdir`. **There is no `bind_mounts` field**; OpenShell does not mount filesystems, only restricts what the sandboxed process can read or write within its existing mount namespace. The mount must therefore be established at the Kubernetes layer, not in `policies/oscar-dev.yaml`.

The Phase 0 addendum's "bind-mount" terminology is now architectural shorthand. The actual mechanism is **Secret-as-volume**: a Kubernetes Secret synced from the host file by main-VPS Claude Code and mounted on the Sandbox CR's pod template.

## Decision

**Two-halves mechanism: host file → Kubernetes Secret → pod volume.**

- **Host file:** `/etc/oscar/oscar.env`. Root-owned, mode 0600. Owned (creation, write, rotation) by main-VPS Claude Code.
- **Format:** `KEY=VALUE` per line; `#` comments and blank lines ignored. A single matching pair of `'`/`"` quotes around the value is stripped.
- **Operator-side sync:** main-VPS Claude Code runs a sync script that materialises the host file as a Kubernetes Secret named `oscar-runtime-secrets` in namespace `openshell` with a single key `oscar.env` (the file contents).
- **Sandbox-side mount:** the Sandbox CR (`agents.x-k8s.io/v1alpha1`, name `oscar-dev`, namespace `openshell`) declares a `secret`-type volume `oscar-secrets` referencing `oscar-runtime-secrets`, mounted on the `agent` container at `/etc/oscar` read-only. The volume's `items: [{key: oscar.env, path: oscar.env}]` makes the key→filename mapping explicit; the file appears at `/etc/oscar/oscar.env` inside the sandbox. Kubelet refreshes the projected file within ~60s of any Secret change.
- **Manifest in version control:** the Sandbox CR lives at `deploy/kube/oscar-sandbox.yaml` on the M2 feature branch. The manifest deliberately omits three per-instance fields the agent-sandbox controller injects at create time: the `openshell.ai/sandbox-id` label, the `OPENSHELL_SANDBOX_ID` env var, and the `OPENSHELL_SSH_HANDSHAKE_SECRET` env var. Including any of these would couple the manifest to one specific sandbox instance and break fresh-create deployments.
- **Landlock allowlist:** `/etc/oscar/oscar.env` is added to `policies/oscar-dev.yaml` `filesystem_policy.read_only` as an explicit-intent entry. Technically redundant (since `/etc` is already in the allowlist), but it documents the intent and survives any future narrowing of the `/etc` allowlist.
- **Loader:** `src/shared/secrets.py:load_host_secrets()` reads the mounted file once at runtime startup and populates `os.environ`. Default behaviour does not override pre-set env vars — lets developer-local exports beat the mounted file for non-prod testing. Phase 3 runtime entry point calls this before instantiating any `Settings(BaseSettings)` class.

## Options considered

- **Keep Sprint 3 `.env`** — rejected per Phase 0 addendum: writable-overlay exposure plus no host-side rotation story.
- **Inject env vars from main-VPS at sandbox startup** — original § 6.4 framing; no concrete carrier in the OpenShell-managed deployment.
- **Add a bind-mount field to `policies/oscar-dev.yaml`** — rejected on inspection of OpenShell's schema (above); OpenShell does not mount, only restricts.
- **`hostPath` volume on the Sandbox pod (instead of Secret-as-volume)** — rejected; would couple the Sandbox to host filesystem layout and bypass Kubernetes' Secret rotation / RBAC story. Secret-as-volume gets kubelet auto-refresh, namespace-scoped RBAC, and standard rotation tooling for free.

## Consequences

- main-VPS Claude Code owns: creating `/etc/oscar/oscar.env`, writing token values, rotating, running the sync script that materialises the host file into the `oscar-runtime-secrets` Kubernetes Secret, and coordinating the `kubectl apply` of `deploy/kube/oscar-sandbox.yaml` plus the sandbox restart that picks the new mount up.
- Sandbox-Claude-Code owns: the Sandbox CR template (`deploy/kube/oscar-sandbox.yaml`), the Landlock allowlist entry, the `load_host_secrets()` loader, and the verification step at Phase 2 close (`test -n "$OSCAR_SLACK_BOT_TOKEN"` from inside the sandbox returns truthy + a live Slack `auth.test` succeeds).
- Sprint 3's `.env` pattern remains usable for developer-local non-secret configuration only.
- Putting the Sandbox CR in version control is a side-benefit beyond M2's Slack scope: future per-client deployments derive from a portable template, not from a per-instance `kubectl get -o yaml` snapshot.

## Future considerations

- **Per-client `metadata.name`.** The committed manifest hard-codes `name: oscar-dev` (the current sandbox's name). M3+ per-client deployments will need to either copy-and-rename the file or template it (e.g. via Kustomize or Helm). Out of M2 scope; flagged so the next sprint that touches deployment doesn't get surprised.
- **Secret rotation cadence.** Kubelet refreshes the projected Secret within ~60s; the runtime config loader reads only at startup. A token rotation therefore requires a sandbox restart to take effect inside the runtime process. M3+ may add a SIGHUP-style re-load if this becomes painful.
