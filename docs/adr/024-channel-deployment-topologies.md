# ADR 024 [Infrastructure] — Channel deployment topologies

**Status:** Accepted (Sprint M2 Phase 2, 2026-04-26).

## Context

M2 ships two channels in parallel — Slack and AgentMail. Both must surface inbound user messages to the General Counsel and post outbound replies, without requiring the per-tenant OpenShell sandbox to expose a public endpoint. This ADR records the deployment topology for both channels and the transport rationale.

## Decision

**Slack — slack-bolt Socket Mode.**

- The sandbox runs `AsyncApp` + `AsyncSocketModeHandler` and makes outbound WSS:443 to `wss-primary.slack.com`. Socket Mode multiplexes inbound events over the same WebSocket — no inbound port, no HTTPS request URL, no TLS termination concern.
- Subscribed events: `app_mention` only. No DMs, no `message.channels` — keeps the bot's surface tight.
- Tokens: bot token (`xoxb-`) for `chat.postMessage`; app-level token (`xapp-`, scope `connections:write`) for the Socket Mode handshake.

**AgentMail — official `agentmail` SDK over WebSocket + REST.**

- Inbound: `client.websockets.connect()` opens an outbound WSS to `wss://ws.agentmail.to/v0`, sends `Subscribe(event_types=["message.received"], inbox_ids=[<our inbox>])`, and iterates events.
- Outbound: `client.inboxes.messages.reply(...)` over REST against `https://api.agentmail.to`. AgentMail's server populates RFC 5322 `In-Reply-To` / `References` headers so email clients thread correctly.
- Reconnection on disconnect: implemented in `AgentMailChannel._listen_loop` with 5s backoff (the SDK does not auto-reconnect).
- Credentials: a single workspace-scoped API key plus the inbox id of the GC's dedicated inbox.

**Common topology.**

- Both channels run **inside the OpenShell sandbox** alongside Deep Agents (one perimeter, no main-VPS↔sandbox bridge).
- Both are **outbound-only** — the sandbox initiates all connections; the underlying transport handles inbound multiplexing without an exposed listener.
- `policies/oscar-dev.yaml` adds `slack` and `agentmail` egress blocks (HTTPS/WSS:443 to the documented hosts; Python interpreters as the binary identity for OPA).
- Token / API-key delivery is via host bind-mount of `/etc/oscar/oscar.env` (ADR 025).

## Options considered

- **Slack Events API over HTTPS** — rejected; requires a public request URL per tenant, breaking the per-VPS ergonomics.
- **AgentMail SMTP/IMAP polling** — rejected; would require either inbound SMTP (public endpoint) or constant polling cost. WebSocket is the SDK's first-class inbound path.
- **AgentMail long-poll / SSE** — not offered by the SDK.
- **Channel runtime split out of the sandbox** (sidecar process on main-VPS bridging into sandbox) — rejected; doubles the perimeter and the secrets-handling surface.

## Consequences

- One sandbox per tenant runs two channel handlers concurrently (Phase 3 wiring).
- Two new policy egress blocks; review when adding M3+ channels (Discord, MCP, Teams).
- Disconnects: Slack-bolt's Socket Mode auto-reconnects; AgentMail reconnects via our explicit loop. Both surface failures to logs (`shared.channels.slack.channel`, `shared.channels.agentmail.channel`).
