# ADR 024 [Infrastructure] — PLACEHOLDER — Channel deployment topologies

**Status:** Reserved.

Reserved by Sprint M2 Phase 0 (2026-04-26); decision content to follow in Phase 2. Renamed in the Phase 0 addendum (2026-04-26) from `slack-channel-deployment` to `channel-deployment-topologies` to reflect that M2 ships two channels in parallel. Scope:

- **Slack channel** — slack-bolt Socket Mode; outbound-only; runs inside the OpenShell sandbox alongside Deep Agents.
- **AgentMail channel** — WebSocket transport per https://docs.agentmail.to/websockets; outbound-only; runs inside the same sandbox.
- Sandbox-as-runtime-host topology (one perimeter, no main-VPS↔sandbox bridge).
- Token / API-key delivery via host bind-mount of `/etc/oscar/oscar.env` (read-only into the sandbox); see ADR 025.

See `docs/sprints/M2-preflight.md` § 7 for the addendum that established the two-channel scope.
