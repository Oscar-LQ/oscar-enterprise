# oscar-dev Sandbox Egress — What's Open and Why

One-page summary of every outbound capability granted to the `oscar-dev`
sandbox via `policies/oscar-dev.yaml`. All traffic funnels through an HTTP
CONNECT proxy at `10.200.0.1:3128`; the proxy enforces per-binary,
per-host rules and presents its own TLS cert (CA bundle at
`/etc/openshell-tls/ca-bundle.pem`).

**DEV vs SIT**: this document describes **DEV** (`oscar-dev` sandbox) only.
Per ADR 006, `policies/oscar-sit.yaml` derives from this file **by
subtraction** — the "DEV-only" column below flags which entries must be
stripped when SIT is authored.

## Filesystem, Process, Landlock

| Field | Value |
|---|---|
| Process identity | `run_as_user: sandbox`, `run_as_group: sandbox` |
| Read-only paths | `/usr`, `/lib`, `/proc`, `/dev/urandom`, `/app`, `/etc`, `/var/log` |
| Read-write paths | `/sandbox`, `/tmp`, `/dev/null` |
| Landlock | `best_effort` |

## Network Sub-Policies

"DEV-only" = per ADR 006, must be stripped from `oscar-sit.yaml`.

| Sub-policy | Hosts | Binaries | Purpose | DEV-only? | ADR |
|---|---|---|---|---|---|
| `claude_code` | `api.anthropic.com`, `statsig.anthropic.com`, `sentry.io`, `raw.githubusercontent.com`, `platform.claude.com`, `storage.googleapis.com` (read-only), `mcp-proxy.anthropic.com` | `/usr/local/bin/claude`, `/usr/bin/node`, `/sandbox/.local/share/claude/versions/**` | Claude Code control-plane, telemetry, self-update versions, MCP. Also the transport for server-side WebSearch — no separate policy needed. | **Yes** | 002 |
| `claude_web_fetch` | ~80 domain patterns spanning GitHub, read-the-docs, Python/Rust/Node/Go ecosystems, MDN, Stack Exchange, AI/ML ecosystem, major cloud docs, search engine landing pages | same as `claude_code` | Claude Code's WebFetch tool. Curated allowlist, extends on demand. | **Yes** | 007 |
| `codex` | `api.openai.com`, `auth.openai.com`, `chatgpt.com` | `/usr/bin/codex`, `/usr/bin/node`, `/usr/lib/node_modules/@openai/**` | OpenAI Codex CLI. Pre-existing (not used by Oscar). | **Yes** | — |
| `copilot` | `github.com`, `api.github.com`, `api.githubcopilot.com` + individual/business/enterprise variants, `copilot-proxy.githubusercontent.com`, telemetry endpoints | `/usr/bin/copilot`, Copilot Node modules | GitHub Copilot CLI. Pre-existing (not used by Oscar). | **Yes** | — |
| `cursor` | `cursor.blob.core.windows.net`, `api2.cursor.sh`, `repo.cursor.sh`, `download.cursor.sh`, Cursor download CDN | `/usr/bin/curl`, `/usr/bin/wget`, `/sandbox/.cursor-server/**` | Cursor IDE. Pre-existing (not used by Oscar). | **Yes** | — |
| `github_rest_api` | `api.github.com` (read-only REST) | `/usr/local/bin/claude`, `/usr/bin/gh` | Claude Code + `gh` CLI REST calls. | **Yes** | — |
| `github_ssh` | `github.com:22` | `/usr/bin/ssh`, `/usr/bin/nc.openbsd` | **SSH push/pull to Oscar-LQ repos** using the `oscar_enterprise_deploy` deploy key. SSH is tunnelled via `ProxyCommand` over the CONNECT proxy; `nc.openbsd` is the actual `connect()` binary. | Mixed — SIT needs `pull` but not `push`; the binary allowlist is the same but credentials differ | 003 |
| `github_ssh_over_https` | `github.com:443` (HTTP: `GET /**/info/refs*` + `POST /**/git-upload-pack`) | `/usr/bin/git` | Public-repo `git clone` / `fetch` / `pull` over HTTPS. Fetch-only (no `git-receive-pack`). | Mixed — retained for SIT (ADR 004 deploy trigger uses it) | — |
| `nvidia_inference` | `integrate.api.nvidia.com` | `/usr/bin/curl`, `/bin/bash`, `/usr/local/bin/opencode` | NVIDIA NIM inference. Pre-existing. | **Yes** | — |
| `opencode` | `registry.npmjs.org`, `opencode.ai`, `integrate.api.nvidia.com` | opencode Node bins, `/usr/bin/node`, `/usr/local/bin/opencode` | opencode CLI. Pre-existing. | **Yes** | — |
| `pypi` | `pypi.org`, `files.pythonhosted.org`, `github.com`, `objects.githubusercontent.com`, `api.github.com`, `downloads.python.org` | `/sandbox/.venv/bin/python(3)`, `pip`, `/usr/local/bin/uv`, `/sandbox/.uv/python/**`, `/app/.venv/bin/*` | `pip install` / `uv pip install` from PyPI and git+https. | **Yes** in this breadth; SIT keeps only what Oscar's runtime imports at startup | — |
| `vscode` | VS Code update + marketplace hosts | `/usr/bin/curl`, `/usr/bin/wget`, `/sandbox/.vscode-server/**`, `/sandbox/.vscode-remote-containers/**` | VS Code Remote server. Pre-existing. | **Yes** | — |

## What This Enables in Practice (for Claude Code)

- **Reach Anthropic** (control plane, Messages API, MCP).
- **WebSearch** (server-side; no extra policy).
- **WebFetch** across ~80 curated dev/docs/AI domains (`claude_web_fetch`).
- **`git clone`/`pull` from any public GitHub repo** over HTTPS
  (`github_ssh_over_https`). Requires `http.sslCAInfo` pointing at the
  sandbox CA (already set in `/sandbox/.gitconfig`).
- **`git push`/`pull` to `Oscar-LQ/oscar-enterprise`** via SSH +
  `oscar_enterprise_deploy` (`github_ssh`).
- **`pip install` / `uv pip install`** from PyPI and from
  `git+https://github.com/...` URLs (`pypi`).

## What's NOT Enabled

- **Bare `*:443`** — rejected by the policy validator. No "allow the
  internet" flag exists.
- **`npm install`** for arbitrary packages (only `registry.npmjs.org` is
  allowed, and only for `opencode`'s binaries).
- **`cargo add` / crates.io downloads** during build. The `claude_web_fetch`
  entries for `crates.io` cover HTTP fetches (reading docs pages) but the
  Cargo binary is not on any policy's binary list.
- **`go get` / Go module proxy** for `/usr/bin/go`. Proxy hosts are in
  `claude_web_fetch` but the `go` binary isn't whitelisted.
- **Non-GitHub Git hosts** (GitLab, Bitbucket, Codeberg, …).
- **Private GitHub repos other than `oscar-enterprise`**. Would need
  another deploy key or a PAT.
- **Arbitrary paste sites, personal blogs, gaming/shopping/social sites,
  etc.** Intentionally out of scope.

## Expansion Workflow

When Claude hits a `403 Forbidden` for a domain you actually want reachable:

1. Confirm the domain via the proxy log (`openshell logs oscar-dev`).
2. Decide which sub-policy it logically belongs to — usually
   `claude_web_fetch` for reference material.
3. Edit `policies/oscar-dev.yaml`, add the host entry (exact host and/or
   `**.<domain>` wildcard).
4. `openshell policy set oscar-dev --policy policies/oscar-dev.yaml --wait`
   applies live. Commit the YAML change from the sandbox, authored as Oscar
   (see ADR 003 for the commit-from-sandbox workflow).

## Quirks Worth Remembering

- **Git needs an explicit CA**: set `http.sslCAInfo =
  /etc/openshell-tls/ca-bundle.pem` in the sandbox's `~/.gitconfig` — git
  ignores `CURL_CA_BUNDLE` / `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE`.
- **DNS is per-binary**: a binary can only resolve hostnames reachable in
  its policy. Direct `nslookup`/`host` will fail for everything because
  those tools aren't in any sub-policy.
- **SSH needs `ProxyCommand`**: port 22 is not transparent-forwarded; SSH
  goes through the CONNECT proxy via `nc -X connect -x 10.200.0.1:3128`.
- **Upload tool gotcha**: `openshell sandbox upload <name> <src> <dst>`
  treats `<dst>` as a parent directory for directory sources, but varies
  for file sources. Always verify `ls -la` after upload.

## Policy File Location

- **Source of truth**: `policies/oscar-dev.yaml` (this repo).
- **Live application**: `openshell policy set oscar-dev --policy
  policies/oscar-dev.yaml --wait`.
- **Drift check**: `openshell policy get oscar-dev --full` vs the file.

## ADR Index

- [ADR 002](adr/002-sandbox-claude-code-network-policy.md) — Claude Code
  self-update + Anthropic endpoints
- [ADR 003](adr/003-sandbox-git-ssh-egress.md) — SSH egress for
  `oscar-enterprise` pushes
- [ADR 004](adr/004-sit-deploy-trigger.md) — SIT deployment trigger
  (manual pull, defer CI)
- [ADR 005](adr/005-secrets-vs-config-split.md) — Secrets vs. config split
  (`.env` on VPS, policy in repo)
- [ADR 006](adr/006-dev-sit-policy-parity.md) — DEV/SIT policy parity by
  subtraction
- [ADR 007](adr/007-sandbox-claude-web-fetch.md) — Broad WebFetch
  allowlist for Claude Code (DEV-only)
