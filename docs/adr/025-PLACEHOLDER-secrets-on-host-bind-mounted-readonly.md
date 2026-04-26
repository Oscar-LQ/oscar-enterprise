# ADR 025 [Infrastructure] — PLACEHOLDER — Secrets on host, bind-mounted read-only into the sandbox

**Status:** Reserved.

Reserved by Sprint M2 Phase 0 addendum (2026-04-26); decision content to follow in Phase 2. Documents the shift from Sprint 3's in-sandbox `.env` pattern (file lives in the sandbox's writable overlay) to a host-side secrets file at `/etc/oscar/oscar.env` (root-owned, mode 0600), bind-mounted read-only into the sandbox.

Driven by the Phase 0 addendum's discovery that there is no host-side `OSCAR_*` secrets file today and no systemd unit running Oscar Enterprise — OpenShell manages the sandbox lifecycle itself, and Sprint 3's `.env` is therefore reachable to anything inside the sandbox's overlay. The bind-mount removes that exposure surface and centralises secret rotation on the host (owned by main-VPS Claude Code).

Phase 2 work (sandbox-Claude-Code): bind-mount entry in `policies/oscar-dev.yaml`; runtime config loader reads env vars from the bind-mounted path. Out of scope here: creation and population of the host-side file (handled by main-VPS Claude Code).

See `docs/sprints/M2-preflight.md` § 7.2 for the addendum that established this decision.
