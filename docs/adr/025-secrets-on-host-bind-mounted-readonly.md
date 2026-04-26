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

## Lessons learned

Recorded after Sprint M2 Phase 2's recovery cascade — roughly three hours of "the mechanism reports success but the behaviour differs" failures against OpenShell v0.0.32. The findings below are the architectural lessons that future operators of Sandbox CRs, OPA policy enforcement, and Slack bot deployments will want before they start, not after. Grouped by category for readability; each entry stands on its own.

### OpenShell controller behaviour

- **Required env vars are injected at construction, not on update.** `apply_required_env` (`driver.rs:1272-1310`) runs only on pod-template construction at Sandbox-CR-create time. It does not re-fire on reconcile-from-update. Sandbox CR manifests must therefore declare every required env var explicitly via `valueFrom` references — relying on the controller to "fill in the rest" works on the create path and silently fails on every subsequent edit path.

- **Controller behaviour cannot be inferred from test or function names.** The OpenShell test `apply_required_env_always_injects_ssh_handshake_secret` describes a construction-path invariant only, despite the word "always" in its name. Verify against runtime evidence (pod spec, agent logs), not against source-name semantics. The same caution applies generally — read the code path you are invoking, not the name of the test that exercises it.

- **Pods do not auto-inherit Sandbox CR labels.** Labels on the CR's `metadata.labels` do not propagate to the pod. Anything the agent or its tooling reads via downward API (the canonical example is `openshell.ai/sandbox-id`, sourced from the label of the same name) must be mirrored explicitly onto `spec.podTemplate.metadata.labels` in the manifest. Without that mirror, downward API references resolve to empty and the agent fails to start with no clear error pointing at the missing label.

- **Sandbox CRs at v0.0.32 are effectively immutable in production.** A direct `kubectl apply` against an existing CR will succeed for spec changes, but it bypasses the controller's bootstrap path — meaning the construction-time injections (above) do not re-run, and the apparent change does not match runtime behaviour. The supported edit path is recreation via the `openshell sandbox` CLI, not direct `kubectl apply`. Treat the manifest in `deploy/kube/oscar-sandbox.yaml` as a template for fresh creates, not as a live-edit surface.

### OpenShell gateway and policy behaviour

- **Sandbox identity is keyed by UUID, not by name.** The gateway's compute store keys Sandbox records by `id` (UUID). Agent identity propagates via the `OPENSHELL_SANDBOX_ID` env var, sourced from the `openshell.ai/sandbox-id` label via downward API. The `OPENSHELL_SANDBOX` env var (the name) is for human-readable identity only — gateway lookups don't use it. Both env vars must be present for the agent to start; missing the ID-by-UUID one produces a NotFound at the gateway with no obvious connection back to the missing label.

- **Watch-stream flapping is baseline, not a fault.** The gateway's watch stream renews every ~30s with WARN-level reconnect logs. This is the documented v0.0.32 lifecycle, not a symptom of misconfiguration. Reconnects complete within ~2s and events are delivered between renewals. Ignore the noise; do not treat it as a recovery signal.

- **Policy redeploy is non-destructive and hot-reloads.** `openshell policy set --policy <file> --wait` reloads the running agent's OPA engine without a pod restart. The gateway's `policy_history` sqlite table is the **runtime source of truth**; the repo path under `policies/` is the template plus version-control trail. The two are reconciled only by operator-driven `openshell policy set` calls — there is no continuous reconciliation loop. A repo edit alone changes nothing at runtime.

### OpenShell policy file conventions

- **Binary identity is matched on the canonical path, not on symlinks.** The OPA engine determines binary identity by canonicalising `/proc/<pid>/exe` through symlink resolution. Symlink-only entries in `binaries:` lists do not match callers — the engine matches against the canonical target. The canonical path (or a covering glob such as `/sandbox/.uv/python/**`) must therefore be present alongside any symlink path. M2 hit this when adding the Slack and AgentMail egress blocks: only `/sandbox/.venv/bin/python` (a symlink to `/sandbox/.uv/python/cpython-3.13-…/bin/python3.13`) was listed. All Python-originated outbound was denied at the proxy until the canonical glob was added — fix at commit `2dc1a6b`. Mirror the pattern that already works in the established `minimax` block: list both the symlink and the canonical glob.

- **Wildcard syntax is `*.<domain>` for subdomains.** The single-asterisk form `*.<domain>` matches subdomains and is validated by `validate_accepts_subdomain_wildcard`. The double-asterisk form `**.<domain>` is also accepted for non-TLD domains, but `**.<tld>` (e.g. `**.org`) is explicitly rejected. M2's first attempt used `*.slack.com`, which works; commit `0f6b93e` switched to `**.slack.com` for consistency with the WSS-host shape. Either is correct for `.slack.com`; choose one and apply it consistently.

- **The policy loader fails silently on malformed entries.** The loader drops or normalises entries it cannot parse, without surfacing the error on any operator-visible surface. The gateway returns a `Loaded` status to `openshell policy set` even when the policy is effectively degraded. Pre-deploy validation against OpenShell's conventions, **and** post-deploy enforcement testing (e.g. `curl` through the proxy to a known-allowed and a known-denied host), are both required. Trusting the `Loaded` status alone has caused real Phase 2 time loss.

### Operational discipline

- **Sandbox state is cache; only committed git state is durable.** Sandbox sessions are ephemeral. Sandbox-Claude-Code's working memory, in-flight uncommitted edits, and any local debug artefacts are lost when the sandbox crashes or its SSH session drops. The discipline that follows is: commit early, commit often, push to the remote on every commit, and treat anything outside `git push origin <branch>` as work that has not yet happened.

- **Operational policy must be on the feature branch HEAD before any deploy or runtime test.** Cross-sprint policy changes that affect runtime behaviour — egress rules, secrets paths, security-sensitive config — live on `main` per governance discipline (CLAUDE.md § Git Discipline), but the deploy or runtime test reads from the feature branch's working tree. Forgetting to pull `main` into the feature branch before deploy is the shape of a Phase 2 stall: the policy change exists in the repo but does not reach the running gateway. The "pull main into feature branch before deploy" step belongs in the runbook for any sprint that modifies operational policy.

- **Sprint 3's in-sandbox `.env` is not the right pattern for production credentials.** The `.env` carrier served prototype work — it lives in the sandbox writable overlay, with no separation between "secret" and "developer-local config", and no host-side rotation story. M2's secrets-on-host pattern subsumes it: LLM credentials migrated from `/sandbox/oscar-enterprise/.env` to `/etc/oscar/oscar.env` at the end of Phase 2 to maintain a single secrets source of truth. Future sprints should migrate the redline and CoSec entry points to `load_host_secrets()` as well, completing the pattern.

### Slack-app provisioning checklist

For future bot deployments. Slack's app-creation UX is shaped around the listener's request URL flow; Socket Mode plus `app_mention`-only requires a few steps that the default flow does not produce.

- **Bot Token Scopes must include both `app_mentions:read` and `chat:write`.** Slack adds `app_mentions:read` automatically when the app is configured to receive `app_mention` events but does **not** add `chat:write` by default — an app that can hear mentions but cannot reply to them is a common provisioning miss. Add `chat:write` explicitly.

- **The app-level token (`xapp-`) is separate from the bot user token (`xoxb-`).** Socket Mode's handshake uses the app-level token (scope `connections:write`); `chat.postMessage` uses the bot user token. They are issued and rotated independently. OAuth scope changes affect the bot user token; the app-level token is unaffected.

- **Reinstall does not always rotate `xoxb-`.** Slack preserves the existing bot user token across reinstalls when the scope change is purely additive — the existing token stays valid and gains the new server-side permissions. A scope reduction or other non-additive change does rotate. The implication for ops: do not assume a reinstall produces a fresh token to copy into `/etc/oscar/oscar.env`; check whether the token actually changed before triggering a sandbox restart for the rotation.
