# Runbook: rotating `/etc/oscar/oscar.env` secrets

Per ADR 025 the runtime sources `OSCAR_*` secrets from `/etc/oscar/oscar.env`
on the host (root, mode 0600), surfaced to the sandbox via the
`oscar-runtime-secrets` Kubernetes Secret in namespace `openshell`. Operator
is main-VPS Claude Code (or the human with root on the host); all steps
run host-side — the bind-mount is read-only inside the sandbox and
`kubectl` is not policy-allowed for sandbox-Claude-Code.

## Tool boundary

- **`kubectl`** refreshes the contents of `oscar-runtime-secrets` (key
  `oscar.env`). The Sandbox CR at `deploy/kube/oscar-sandbox.yaml` is also
  `kubectl apply`-d (ADR 025), but only when the volume topology changes
  — Secret name, mount path, or item key. Routine rotation does not.
- **`openshell sandbox` CLI** is sandbox lifecycle only (`delete`,
  `create`, `connect`, `get`); there is no `openshell sandbox apply -f`
  for CR yaml. Use it to restart the sandbox, not to edit the CR.

## Propagation: file refresh vs running process

The M2 lesson worth internalising: only one of two layers auto-refreshes.

- **Projected file in the pod** — kubelet refreshes the Secret-volume file
  within ~60s of a Secret change (ADR 025 § Future considerations). No
  pod restart needed for the on-disk file to update.
- **Running runtime process** — `src/shared/secrets.py:load_host_secrets()`
  reads the file once at startup and populates `os.environ`; it does not
  re-read on its own. Every rotation therefore requires a sandbox restart.
  ADR 025 flagged SIGHUP reload as a follow-up; not implemented as of M3.

## Worked example: adding `OSCAR_LLM_OSCAR_*` (M3 carry-forward (i))

```bash
# A1 — Edit the host file (preserve root-owned, mode 0600).
sudo $EDITOR /etc/oscar/oscar.env
# Append, per M3 SPRINT_LOG recommendation:
#   OSCAR_LLM_OSCAR_PROVIDER=openrouter
#   OSCAR_LLM_OSCAR_MODEL=openai/gpt-5.5
#   OSCAR_LLM_OSCAR_API_KEY=<the OpenRouter key already on the host>

# A2 — Refresh the Kubernetes Secret from the host file.
kubectl create secret generic oscar-runtime-secrets \
  --namespace openshell \
  --from-file=oscar.env=/etc/oscar/oscar.env \
  --dry-run=client -o yaml \
  | kubectl apply -f -

# B — Restart the sandbox so the runtime re-reads the file.
openshell sandbox delete oscar-dev
kubectl apply -f deploy/kube/oscar-sandbox.yaml   # controller recreates pod

# C — Verify inside the new sandbox.
openshell sandbox connect oscar-dev
#   $ test -n "$OSCAR_LLM_OSCAR_API_KEY" && echo OK
```

Removing or rotating an existing key follows the same shape: edit, re-apply
the Secret, restart.
