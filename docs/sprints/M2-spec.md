# Sprint M2 — GC answers a Slack message

Save as: `docs/sprints/M2-spec.md` once the pre-flight confirms the path.

## Goal

A user mentions the GC in a Slack channel. The General Counsel Deep Agent — whichever one already exists in the repo — receives the message, generates a reply, and posts it back into the same Slack thread. One channel, one agent, one round-trip. The framework spine for future channel work lands in this sprint, but the work plugs into what's there rather than replacing it.

## Critical constraint — parallel sessions are live

A separate sandbox-Claude-Code session is actively working the redline track. This session must:

- Never touch `src/redline/`, `docs/redline/`, or anything tagged `[10x]` in SPRINT_LOG without explicit reason and a documented coordination point.
- Use a feature branch from the start. Never commit to main directly.
- Pull from main immediately before starting and check whether anything new has landed since the last context — the redline session may have merged work overnight.
- Surface any cross-track touchpoint to Arturs before proceeding, not after.

If at any point this session would need to modify code the redline track owns, stop and surface for Arturs's adjudication. Do not assume which track wins.

## Phase 0 — Pre-flight investigation (do this before writing any code)

This is the most important phase. The output of Phase 0 is not code; it is a discovery document. Ship Phase 0 to Arturs for review before starting Phase 1. No code in Phase 0.

### What to investigate, and produce findings on

**1. The current GC.** Find it. Read it. Document:

- Where it lives in the repo (likely `src/agents/` or similar, but find out).
- How it's instantiated — is it `create_deep_agent(...)`, a custom subclass, or something else?
- What model it's pinned to.
- What its system prompt is and what behavioural assumptions are baked in.
- What tools, if any, it currently has.
- What subagents configuration it has (inline, async, or none).
- How it's currently invoked — is there an existing entry point, a script, an HTTP server? How is it tested today?
- What its checkpointer / memory backend is.

**2. The current deepagents and langgraph versions.** Read the lockfile / pyproject.toml / requirements. Note them precisely. The plan in this spec assumes Deep Agents v0.5+ with AsyncSubAgent available — if the repo is pinned to an earlier version, that's a Phase 0 finding to surface, not something to silently upgrade.

**3. Existing channel / messaging code.** Search the repo thoroughly for anything that already talks to Slack, Telegram, Discord, email, MCP servers acting as channels, or any other inbound-message infrastructure. Look in `src/`, in tests, in scripts, in config. Document what's there. If there's a half-built Slack integration or any prior attempt, that changes everything about this sprint.

**4. Existing inter-agent or sub-agent code.** Same search for any existing department-head agents (Commercial, CoSec) or for any code that delegates between agents. Document the names, locations, and current state. The handover context mentioned that the CoSec track has started with Sprint C1 — find what C1 actually built. Don't assume.

**5. The sandbox / OpenShell environment.** Confirm:

- Whether the OpenShell sandbox permits long-running outbound WebSocket connections from this process.
- If OpenShell has a policy file, identify which policy currently governs network egress and document it.
- Whether main-VPS Claude Code (outside the sandbox) has previously configured any Slack-related secrets or systemd services. If yes, document them; coordinate via Arturs.
- The Python version available in the sandbox.

**6. The per-tenant secrets pattern.** Find where existing secrets (LLM API keys per the `OSCAR_LLM_*` triple pattern) actually live and how they're loaded at runtime. Slack tokens will follow the same pattern; identifying it precisely matters for Phase 2.

**7. The SPRINT_LOG state.** Read the most recent entries on the redline track and the CoSec track. Note any in-flight work, any unmerged feature branches, any open questions tagged for Arturs. Identify whether anything in flight could collide with the channel work.

**8. The [M1] infrastructure.** What did M1 actually establish? Read the SPRINT_LOG entry, the directory structure it produced, and any ADRs it wrote. The M-series convention this sprint inherits is M1's; understand it before extending it.

### Deliverable from Phase 0

A document at `docs/sprints/M2-preflight.md` with:

- A table mapping every assumption in this spec to either "confirmed: <evidence>" or "contradicted: <evidence>" or "not applicable: <reason>".
- A list of files this sprint expects to create, each marked as new or modifying-existing with paths.
- A list of files this sprint expects to read but not modify.
- An explicit "no clash with redline track" statement, with evidence — what files redline currently owns, what files this sprint touches, why those don't overlap.
- A list of open questions that need Arturs's input before Phase 1 starts.
- A revised sprint plan if any pre-flight finding contradicts the assumptions below. Don't soldier on with a broken plan; surface the contradiction.

Stop after Phase 0. Wait for Arturs's review. Do not proceed to Phase 1 until the pre-flight is approved.

## Phase 1 — Framework spine (after pre-flight approved)

The intent of Phase 1 is to add the channel framework as new code that the existing GC plugs into, without modifying the existing GC's behaviour or interface beyond what's strictly required. The GC should not need to know anything about Slack — it should keep being a Deep Agent, invoked the same way the rest of Oscar invokes it.

### What to build

**The Channel abstraction (`src/shared/channels/base.py`).** As described — minimal: `start`, `stop`, `post_message`, `on_inbound_message`. Grow sprint by sprint, not upfront. If pre-flight found existing channel code, this abstraction must be designed to accommodate it cleanly, not in opposition to it.

**The FakeChannel for tests (`src/shared/channels/fake.py`).** No external dependencies. Stores posted messages in a list, exposes `simulate_inbound()`. Used in unit tests for this sprint and every future channel sprint.

**The dispatcher (`src/shared/dispatcher.py`).** Receives `InboundMessage`. Resolves a deterministic LangGraph thread ID from `conversation_id`. Calls the existing GC's invocation path — whatever Phase 0 documented as the way Oscar invokes the GC today. Posts the GC's reply back via `channel.post_message`. The dispatcher is new; the GC invocation path is not.

If the existing GC invocation path is awkward to plug into the dispatcher, that is a Phase 0 finding that should have been surfaced. If it surfaces in Phase 1, stop and surface it then. Do not silently rewrite the GC's interface to fit the dispatcher.

### What deliberately does not change in Phase 1

- The GC's system prompt.
- The GC's model configuration.
- The GC's tool list (empty or otherwise).
- The GC's subagent configuration.
- Anything in `src/redline/` or `src/cosec/`.
- Any redline or CoSec track sprint tagging.

If Phase 1 finds it needs to change one of these — for example, the GC's invocation path doesn't expose a way to pass a thread ID and a user message — surface it as a question, do not change it.

## Phase 2 — Slack channel implementation

The Slack channel (`src/shared/channels/slack/`). Folder structure:

```
src/shared/channels/slack/
├── __init__.py
├── channel.py
├── config.py
└── manifest.yaml
```

Implementation: slack-bolt Python SDK in Socket Mode. Pin to the latest stable version after sandbox-Claude-Code checks PyPI. Subscribe only to `app_mention`. Construct `InboundMessage` with `conversation_id = f"{channel}:{thread_ts or ts}"`, strip the leading `<@BOTID>` from text, pass the full event payload as `raw`. `post_message` parses the conversation ID back into channel and `thread_ts`, calls `chat.postMessage` with `thread_ts` set.

Configuration via env vars following the pattern Phase 0 documented (likely `OSCAR_SLACK_BOT_TOKEN` and `OSCAR_SLACK_APP_TOKEN`, but match whatever per-tenant convention already exists).

## Phase 3 — Wire it all together

The runtime entry point. Where this lives depends on Phase 0:

- If Oscar already has a runtime entry point (a `main.py`, a CLI, a server), extend it to optionally start the channel layer. Don't replace what's there.
- If Oscar's GC is currently invoked ad-hoc (scripts, notebooks), this sprint introduces a runtime — but as `src/shared/runtime/` or similar, not as an opinionated rewrite of how Oscar starts.

The runtime: load config, construct `SlackChannel`, find the existing GC and construct an invoker that wraps its existing invocation path, construct `Dispatcher` wiring them together, register the dispatcher as the channel's inbound handler, call `channel.start()`, run forever, handle SIGTERM gracefully.

## Tests

Unit tests against `FakeChannel` covering:

- Dispatcher forwards inbound messages to the GC invoker.
- Dispatcher posts replies back to the originating `conversation_id`.
- The same Slack conversation produces the same LangGraph thread ID across invocations.
- Different Slack conversations produce different thread IDs.

Integration test (manual, at sprint review): real Slack tokens, real workspace, send `@oscar-gc hello`, see a coherent reply appear in the same thread within 30 seconds, send a follow-up in the same thread, see the GC remember the previous turn.

## Coordination protocol with the redline track

Before merging Phase 0:

- Push the M2 feature branch to the remote.
- Open a draft pull request titled `[M2] Channel framework + Slack integration — pre-flight`.
- The pull request description references that the redline track is parallel and lists the files this sprint expects to touch. This serves as a visible coordination point that the redline session can see.

Before merging any phase to main:

- Pull from main to catch any redline-track merges since the branch was created.
- Re-run the no-clash check from pre-flight against the updated main.
- If a clash has emerged (a file this sprint expected to be new now exists, or a file this sprint reads has changed shape), stop and surface to Arturs.

## Documentation deliverables

- `docs/sprints/M2-preflight.md` — the Phase 0 discovery document.
- `docs/sprints/M2-spec.md` — this spec, committed for posterity.
- `docs/architecture/channel-abstraction.md` — short ADR explaining the Channel Protocol and the deliberate decision to grow it sprint by sprint.
- `docs/architecture/slack-app-manifest.md` — the manifest YAML and instructions for loading it into Slack's app dashboard.
- `docs/operations/runbook-channel-switch.md` — seeded version, documenting the FakeChannel-as-substitute pattern for tests and any future swap.
- A SPRINT_LOG entry tagged `[M2]` with what landed, what was deferred, what the next sprint should pick up, and a cross-reference to any redline or CoSec coordination points encountered.

## Done when

Arturs can @-mention the GC bot in a test Slack channel, get a coherent English reply in the same thread, send a follow-up message in the same thread, and see the GC remember the previous turn — and the redline track session has continued working unimpeded throughout the sprint, with no merge conflicts at integration time, and the Phase 0 pre-flight document is in the repo as a record of what existed before this sprint started.

That last condition matters as much as the first. The pre-flight document is what allows future sprints (M3 onward) and future Claude Code sessions to know what they inherited.

---

## Addendum (2026-04-26 — post Phase 0 review)

Three Phase 0 decisions adopted after the original spec was committed; full text in `docs/sprints/M2-preflight.md` § 7.

1. **Second channel: AgentMail (WebSocket).** M2 ships two channels in parallel — Slack (Socket Mode) and AgentMail (WebSocket per https://docs.agentmail.to/websockets), both outbound-only, no public endpoint required from the sandbox. Phase 1 unchanged. Phase 2 splits into **2A** (Slack channel under `src/shared/channels/slack/`) and **2B** (AgentMail channel under `src/shared/channels/agentmail/`) — sequence either way; no shared implementation files between them. Shared files (`requirements.txt`, `policies/oscar-dev.yaml`, `.env.example`, `docs/secrets.md`) get append-only additions for both channels in one pass. Phase 3 starts both channels concurrently in the runtime; the integration test covers both — an `@oscar-gc` Slack mention AND an inbound email to the GC's AgentMail inbox each yield a coherent reply within 30 seconds, with thread-memory preserved across follow-ups.

2. **Secrets via host bind-mount.** Sprint 3's in-sandbox `.env` is replaced by `/etc/oscar/oscar.env` on the host (root-owned, mode 0600), exposed to the sandbox via a read-only bind-mount. Main-VPS Claude Code owns the host-side file (creation + token writes); this session adds the bind-mount entry to `policies/oscar-dev.yaml` and updates the runtime config loader in Phase 2. ADR 025 reserved for the decision content. Verification at end of Phase 2: `test -n "$OSCAR_SLACK_BOT_TOKEN"` from inside the sandbox returns truthy, and a live Slack `auth.test` succeeds.

3. **ADR 024 placeholder rename.** `024-PLACEHOLDER-slack-channel-deployment.md` → `024-PLACEHOLDER-channel-deployment-topologies.md` — the ADR now covers both Slack Socket Mode and AgentMail WebSocket deployment topologies.
