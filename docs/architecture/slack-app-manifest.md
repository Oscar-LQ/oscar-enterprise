# Slack app manifest — General Counsel bot

The manifest YAML is at [`src/shared/channels/slack/manifest.yaml`](../../src/shared/channels/slack/manifest.yaml). This doc covers loading it into a Slack workspace and provisioning the two tokens the SlackChannel reads from `OSCAR_SLACK_BOT_TOKEN` / `OSCAR_SLACK_APP_TOKEN`.

## Per-tenant model

Oscar is per-VPS, per-tenant — each client's deployment runs in its own OpenShell sandbox with its own credentials. Each client's Slack workspace gets its own app installation. There is no Slack app "distribution" / OAuth flow; a workspace admin loads the manifest, installs the app, and hands the resulting tokens to main-VPS Claude Code who writes them into `/etc/oscar/oscar.env` on the host.

## Loading the manifest

1. Workspace admin opens https://api.slack.com/apps → **Create New App** → **From a manifest**.
2. Select the destination workspace.
3. Paste the contents of `src/shared/channels/slack/manifest.yaml`. Review the bot scopes (`app_mentions:read`, `chat:write`) and the Socket Mode flag (enabled).
4. Create.

## Generating the two tokens

After app creation:

| Env var | Where it comes from | Slack admin step |
|---|---|---|
| `OSCAR_SLACK_BOT_TOKEN` | Bot token, prefix `xoxb-` | Settings → **Install App** → Install to Workspace; copy the bot token shown. |
| `OSCAR_SLACK_APP_TOKEN` | App-level token, prefix `xapp-` | Settings → **Basic Information** → Scroll to *App-Level Tokens* → **Generate Token and Scopes** → name "socket-mode", scope `connections:write`; copy the token shown. |

Hand both tokens to main-VPS Claude Code. Per ADR 025, main-VPS writes them to `/etc/oscar/oscar.env` (root-owned, mode 0600) on the host. The sandbox sees the file via read-only bind-mount; the runtime config loader sources `OSCAR_SLACK_*` env vars from the bind-mounted path; `SlackChannelSettings()` validates them at construction.

## Bot install + test channel

After installing the app to the workspace:

1. Add the bot to a test channel: `/invite @Oscar GC`.
2. Once the runtime is up and the bind-mount is in place (Phase 2 cross-cutting work), mention the bot: `@Oscar GC hello`.
3. Expect a coherent reply in-thread within ~30 seconds (Phase 3 integration test).

## Why Socket Mode

- **No public endpoint.** The sandbox makes outbound WSS to `wss-primary.slack.com` only — no inbound port required, no HTTPS request URL to register, no TLS termination concern.
- **Egress-only policy fit.** `policies/oscar-dev.yaml` adds a Slack block permitting outbound HTTPS/WSS:443 to `slack.com`, `wss-primary.slack.com`, `*.slack.com`, `files.slack.com`; no other policy change required.
- **Per-VPS tenancy fit.** No request URL means no DNS / TLS / load-balancer setup per tenant — a workspace admin just generates tokens and Oscar boots.

## Related

- `src/shared/channels/slack/channel.py` — SlackChannel implementation.
- `src/shared/channels/slack/config.py` — Pydantic-settings for the two env vars.
- ADR 023 — Channel Protocol and dispatcher.
- ADR 024 (placeholder, Phase 2 content TBD) — Channel deployment topologies (Slack Socket Mode + AgentMail WebSocket).
- ADR 025 (placeholder, Phase 2 content TBD) — Secrets on host, bind-mounted read-only into the sandbox.
