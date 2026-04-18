# ADR 007 — Broad Web-Fetch Access for Claude Code (DEV-only)

- **Status:** Accepted
- **Date:** 2026-04-18
- **Scope:** `policies/oscar-dev.yaml` (new `claude_web_fetch` block)
- **Supersedes:** none
- **Related:** ADR 002 (Claude Code network policy), ADR 003 (SSH egress), ADR 006 (DEV/SIT policy parity)

## Applicability

This sub-policy is explicitly **DEV-only**. Per ADR 006 (DEV/SIT policy
parity by subtraction), `claude_web_fetch` is one of the "build-time
egress" concessions that **must not carry into `policies/oscar-sit.yaml`**
when SIT is stood up. SIT has no Claude Code runtime and therefore no
WebFetch traffic to account for.

## Context

Claude Code inside the `oscar-dev` sandbox relies on two internet tools:

- **WebSearch** — executes server-side on Anthropic's infrastructure; results
  stream back through `api.anthropic.com`, which is already permitted by the
  `claude_code` sub-policy. Tested: works out of the box, no policy change
  needed.
- **WebFetch** — executes client-side; the Node runtime makes an outbound
  HTTPS request to an arbitrary URL through the sandbox's CONNECT proxy
  (`10.200.0.1:3128`). The proxy enforces per-binary, per-host policy.
  Without a matching allowlist entry, every fetch returns `403 Forbidden`.

The operator wanted Claude Code's standard "look things up on the internet"
behaviour — notably fetching package docs, reading GitHub READMEs, checking
Stack Overflow answers, and following linked articles.

## Decision

**Bare `*:443` is not an option.** OpenShell's policy validator rejects:

- Bare host wildcards `*` or `**` with message `host wildcard '*' matches
  all hosts; use specific patterns like '*.example.com'`
- TLD wildcards like `*.com` (test case
  `validate_policy_safety_rejects_tld_wildcard` in
  `crates/openshell-server/src/grpc/validation.rs:798`)
- Wildcards that don't start with `*.` or `**.`

Since unrestricted egress is architecturally disallowed, the decision is to
add a dedicated `claude_web_fetch` sub-policy with a **curated
domain-wildcard allowlist** covering the 95th-percentile of sites Claude
Code fetches during normal development work:

- Code hosting and raw content: `github.com`, `**.github.com`,
  `**.githubusercontent.com`, `**.github.io`
- Read-the-docs family: `**.readthedocs.io`, `**.readthedocs.org`,
  `**.rtfd.io`, `**.rtfd.org`
- Python: `python.org`, `**.python.org`, `pypi.org`, `**.pypi.org`,
  `**.pythonhosted.org`, `**.pydata.org`, FastAPI, Django docs
- Rust: `rust-lang.org`, `**.rust-lang.org`, `crates.io`, `**.crates.io`,
  `docs.rs`, `**.docs.rs`
- Node / npm: `npmjs.com`, `**.npmjs.com`, `npmjs.org`, `**.npmjs.org`,
  `nodejs.org`, `**.nodejs.org`
- Go: `go.dev`, `**.go.dev`, `golang.org`, `**.golang.org`, module proxy
- Community Q&A and technical blogs: Stack Exchange family, `dev.to`,
  `medium.com`, `**.substack.com`
- Web standards: `mozilla.org` / MDN, `w3.org`
- AI/ML ecosystem: `**.anthropic.com`, `**.openai.com`, `**.huggingface.co`,
  `**.langchain.com`, `**.langgraph.dev`, vector DB homes
- Search engine landing pages: DuckDuckGo, Google, Bing
- Cloud/infra docs: AWS, GCP, Azure, Cloudflare, Vercel, Netlify
- Misc OSS project homes: JetBrains, Apache, GNU, FreeBSD, Linux kernel

The allowlist is baseline-only — operators can extend it as Claude
encounters new domains. Each miss surfaces as a clear `403` at the proxy,
making the expansion decision explicit rather than silent.

**Binaries**: `/usr/local/bin/claude`,
`/sandbox/.local/share/claude/versions/**`, and `/usr/bin/node`. Node is
included because Claude Code is a Node process — the actual `connect()`
syscall during `fetch()` comes from `/usr/bin/node`. This does widen the
reach to any other Node process in the sandbox; no other Node workload
currently runs here.

Alternatives considered:

1. **Wildcard `*:443` on `claude_code`.** Rejected by the policy validator
   as documented above. Not an option.
2. **`enforcement: audit` on a broad rule.** `audit` relaxes L7 rule
   enforcement (allows traffic, just logs it) but still requires a valid
   host in the allowlist. It does not grant broad host reach.
3. **Local fetch gateway.** Spin up a tiny HTTP service in the sandbox
   that fetches on Claude's behalf, with its own allowlist enforced inside
   the sandbox. Rejected: more moving parts, introduces a service to
   maintain, duplicates the CONNECT-proxy enforcement already in place.
4. **Fine-grained per-domain sub-policies** (one per site). Rejected:
   creates dozens of near-identical blocks and makes the policy file
   unreadable. A single aggregated `claude_web_fetch` with a curated list
   is the better unit of audit.

## Consequences

- Claude Code gains WebFetch reach to ~80 domain patterns covering the
  major developer ecosystem. Day-to-day documentation lookups, package
  README reads, and Stack Overflow references all succeed without
  per-request policy churn.
- **Exfiltration surface widens**. Node inside the sandbox can POST to any
  of the allowed domains. Notably, `**.github.com` allows gist creation
  (`gist.github.com`) — a plausible exfil channel. `**.huggingface.co`,
  `**.substack.com`, and various paste-like sites are similar. The
  filesystem scope (`/sandbox`, `/tmp` read-write) bounds what Claude can
  read, but the deploy key at `/sandbox/.ssh/oscar_enterprise_deploy` is
  within that scope and is Claude-readable. Mitigation is at the
  prompt/agent-behaviour layer, not the network layer.
- **Cold domain friction**: every time Claude tries to fetch a domain
  outside the allowlist, it hits a `403`. Operators can triage by
  inspecting the sandbox egress log and adding the domain to this
  sub-policy. This is the designed-in "expand as you go" posture.
- `/usr/bin/node` is listed here in addition to `claude_code` and the
  existing `codex`/`opencode` sub-policies. Any future Node-based tooling
  inside the sandbox inherits this reach; ADR-follow-up if that becomes a
  problem.
- **Credential note**: public-site fetches do not require auth. WebFetch
  against authenticated endpoints (GitHub private repos, private APIs)
  would still fail unless the request carries proper credentials —
  something Claude Code does not do autonomously.
