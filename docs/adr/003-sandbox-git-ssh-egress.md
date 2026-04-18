# ADR 003 — SSH Egress for Sandbox Git Operations

- **Status:** Accepted
- **Date:** 2026-04-18
- **Scope:** `policies/oscar-dev.yaml` (new `github_ssh` block)
- **Supersedes:** none
- **Related:** ADR 002 (Claude Code network policy)

## Context

The `oscar-dev` sandbox must be able to clone, pull, and push to
`Oscar-LQ/oscar-enterprise` so that Claude Code running inside it can
contribute back to this repository (policy changes, ADRs, documentation).
Neither existing network policy permitted this:

- `github_ssh_over_https` allows `/usr/bin/git` to hit `github.com:443` but
  is restricted to `GET /**/info/refs*` and `POST /**/git-upload-pack` —
  fetch-only, no `git-receive-pack`, so push is blocked.
- HTTPS push would also require a PAT or GitHub App installation token;
  deploy keys are SSH-only by design.
- SSH egress was not permitted at all (no port-22 host, `/usr/bin/ssh` not
  allowlisted anywhere).

The existing host-side workflow uses an ed25519 deploy key
(`oscar_enterprise_deploy`) registered on the `Oscar-LQ/oscar-enterprise`
repository. Copying that credential into the sandbox is the
least-invasive way to grant write access: the key is repo-scoped at
GitHub, so the sandbox gains no reach beyond this one repository.

## Decision

Add a `github_ssh` sub-policy allowing `/usr/bin/ssh` and
`/usr/bin/nc.openbsd` to reach `github.com:22`:

```yaml
github_ssh:
  name: github-ssh
  endpoints:
  - host: github.com
    port: 22
  binaries:
  - path: /usr/bin/ssh
  - path: /usr/bin/nc.openbsd
```

The sandbox has no direct outbound network path — all egress is funnelled
through an HTTP CONNECT proxy at `10.200.0.1:3128`, which enforces the
policy per-binary. The proxy does not transparently forward port-22
traffic, so the SSH client needs an explicit `ProxyCommand`; that in turn
means the process making the actual `connect()` syscall is `nc.openbsd`,
not `ssh`, which is why both binaries appear in the allowlist.

The sandbox receives a copy of the deploy key and an SSH config entry
(`github-oscar-enterprise` → `github.com`) with `IdentityFile`,
`IdentitiesOnly yes`, and:

```
ProxyCommand /usr/bin/nc.openbsd -X connect -x 10.200.0.1:3128 %h %p
```

Repo-local git identity inside the sandbox is set to
`Oscar <271598430+Oscar-LQ@users.noreply.github.com>`, distinct from the
host's committer identity.

Alternatives considered:

1. **HTTPS + fine-grained PAT.** Would require extending
   `github_ssh_over_https` with a `POST /**/git-receive-pack` rule and
   provisioning a PAT. Pros: the TLS-terminating proxy can enforce on URL
   path, giving inspection at the network layer. Cons: PATs are
   user-scoped bearer tokens (broader than a deploy key), introduce a
   credential rotation lifecycle, and must be stored inline in a URL or
   `.netrc`. Rejected as higher operational cost for equivalent scope.
2. **GitHub App with short-lived installation tokens.** The right
   primitive for a multi-engineer or compliance-driven setup (1-hour
   tokens, per-repo granular permissions, cryptographic audit trail).
   Rejected as over-engineered for the current single-operator sandbox.

## Consequences

- `oscar-dev` gains outbound TCP to `github.com:22`. Unlike HTTPS, the
  proxy cannot inspect payloads on this connection. Defence-in-depth is
  provided at the credential layer: the deploy key is repo-scoped at
  GitHub, `IdentitiesOnly yes` prevents key enumeration, and only the
  fixed, root-owned `/usr/bin/ssh` binary is allowed to initiate the
  connection.
- Push access to `oscar-enterprise` means the sandbox can edit its own
  policy file. This is an accepted trust position — the operator of the
  sandbox is also the owner of the repository.
- Credential lifecycle: rotating the deploy key requires updating both
  `/root/.ssh/oscar_enterprise_deploy` on the host and
  `/sandbox/.ssh/oscar_enterprise_deploy` inside the sandbox, plus
  replacing the public-key entry in the GitHub repository's Deploy Keys
  list. No token-refresh machinery required.
- **Follow-up:** once the BYOC sandbox image lands (tracked under ADR
  002's follow-up), the deploy key should be baked into the image at a
  root-owned, sandbox-user-readable path (e.g. `/opt/oscar/ssh/`) rather
  than uploaded at runtime.
