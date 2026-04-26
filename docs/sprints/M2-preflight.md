# Sprint M2 — Phase 0 pre-flight

**Sprint:** M2 — [Infrastructure] — Channel framework + Slack integration
**Pre-flight date:** 2026-04-26
**Author:** sandbox-Claude-Code session (M2 worktree at `/sandbox/oscar-m2/`)
**Reviewer:** Arturs
**Status:** Phase 0 deliverable. Phase 1 starts once decisions in § 6 are absorbed and the Step 0 untracked-files gate (item 7) has cleared. Both conditions met as of the original Phase 0 commit. **A 2026-04-26 addendum (§ 7 below) adds three further decisions before Phase 1 begins:** AgentMail as a second channel (parallel to Slack), secrets via host bind-mount of `/etc/oscar/oscar.env` (replacing Sprint 3's in-sandbox `.env` and the env-injection-at-startup mechanism in § 6.4), and the rename of ADR 024 to cover both channels' deployment topologies. Where the addendum revises an item below, the addendum entry takes precedence; original items are retained for the historical record.

This document is the discovery output that the M2 spec mandates before any code is written. It records what existed in the repo on 2026-04-26 against every assumption the spec embeds, lists the file footprint M2 will produce, captures the decisions Arturs has adopted on every open question raised during planning, and serves as the visible coordination point with the parallel **Redline** session (active on `sprint-10P-counterparty-response`) and the **CoSec** session (active on `sprint-c1-cosec-drafter`, worktree at `/sandbox/oscar-cosec/`).

---

## 1. Spec-assumption verification table

| # | Spec assumption | Status | Evidence |
|---|-----------------|--------|----------|
| 1 | "Whichever GC already exists in the repo" can be invoked unchanged | **Contradicted as stated** | The only GC implementations are experimental harnesses under `src/redline/experiments/sprint-07-gc-commercial-routing/gc_and_commercial.py:100-108` (two-level: GC → Head of Commercial) and `src/redline/experiments/sprint-09-accept-reject-specialist/gc_commercial_acceptreject.py:186-193` (three-level: GC → HOC → accept-reject-reasoner). Both are pure `create_deep_agent(model=..., tools=[], system_prompt=GC_SYSTEM_PROMPT, subagents=[...])`; no checkpointer; no production entry point. Invoking the existing GC requires either touching `src/redline/` (against spec) or copying the pattern into a non-redline location. Resolved by decision § 6.1. |
| 2 | Deep Agents v0.5+ available, with AsyncSubAgent | **Confirmed** | `requirements.txt:18` pins `deepagents==0.5.3`. AsyncSubAgent imports cleanly: `python -c "from deepagents import AsyncSubAgent; print(AsyncSubAgent)"` → `<class 'deepagents.middleware.async_subagents.AsyncSubAgent'>`. |
| 3 | LangGraph + checkpointer available for multi-turn memory | **Confirmed** | `requirements.txt:58` pins `langgraph==1.1.8`, `requirements.txt:59` pins `langgraph-checkpoint==4.0.2`. `from langgraph.checkpoint.memory import MemorySaver` resolves to `<class 'langgraph.checkpoint.memory.InMemorySaver'>` (MemorySaver is an alias for InMemorySaver in this version — record this for Phase 1). |
| 4 | Existing channel / messaging code may already be present | **Contradicted (none exists)** | Repo-wide search found zero Slack / Telegram / Discord / email / Teams / WhatsApp imports. `slack-bolt` is **not** in `requirements.txt`. `uvicorn==0.44.0`, `starlette==1.0.0`, `websockets==16.0` are transitive deps only (likely pulled in by `sse-starlette==3.3.4`). M2 builds on a clean slate. |
| 5 | MCP-as-channel infrastructure may already exist | **Contradicted (none exists)** | `mcp==1.27.0` and `fastmcp==3.2.4` are in `requirements.txt` but unused in `src/`. All in-repo "MCP" references are to "Model Contract Processor" (Adeu's predecessor for redlining), not Model Context Protocol. No inbound-channel use. |
| 6 | Existing inter-agent / department-head / sub-agent code may exist | **Confirmed (limited)** | Redline track has the GC → HOC → accept-reject-reasoner three-level chain (Sprint 9, redline experiment file). CoSec track has the single-agent drafter at `src/cosec/agents/drafter.py` (Sprint C1, currently on `sprint-c1-cosec-drafter` worktree at `/sandbox/oscar-cosec/`, head SHA `00ec758`; mirrored as untracked files in `/sandbox/oscar-enterprise/`). No production-located GC or HoC. |
| 7 | OpenShell sandbox permits long-running outbound WebSocket connections | **Contradicted — mandatory policy change required** | `policies/oscar-dev.yaml` enumerates 14 sub-policies (`claude_code`, `claude_web_fetch`, `codex`, `copilot`, `cursor`, `github_*`, `minimax`, `openrouter`, `nvidia_inference`, `opencode`, `pypi`, `vscode`); none mention Slack hosts and none specify a WebSocket protocol. Every endpoint defaults to HTTPS REST. Phase 2 must add a `slack` sub-policy permitting HTTPS/WSS:443 to `slack.com`, `wss-primary.slack.com`, `*.slack.com`, `files.slack.com`. Resolved by decision § 6.4. **Addendum § 7.1 extends this:** Phase 2 must additionally add an `agentmail` sub-policy permitting outbound WSS to AgentMail's WebSocket edge (host(s) TBD on AgentMail-docs read in Phase 2B; see https://docs.agentmail.to/websockets). |
| 8 | Per-tenant secrets pattern is consistent | **Confirmed (with naming caveat)** | `OSCAR_LLM_<ROLE>_{PROVIDER, MODEL, API_KEY}` triple is established in `.env.example:22-43` (active for GENERAL_COUNSEL, HEAD_OF_COMMERCIAL, ACCEPT_REJECT_REASONER, REDLINE_SPECIALIST) and documented in `docs/secrets.md`. ADR 005 governs secrets-vs-config split. New `OSCAR_SLACK_BOT_TOKEN`, `OSCAR_SLACK_APP_TOKEN`, `OSCAR_AGENTMAIL_API_KEY`, and `OSCAR_AGENTMAIL_INBOX_ID` follow the same prefix convention; values stay placeholder in `.env.example` and (per Addendum § 7.2) are sourced from `/etc/oscar/oscar.env` on the host, exposed read-only to the sandbox via bind-mount. **The env-injection-at-sandbox-startup mechanism in decision § 6.4 is superseded by the bind-mount approach in Addendum § 7.2.** |
| 9 | Python version | **Confirmed** | `python --version` → `Python 3.13.12` in the M2 worktree's `.venv`. |
| 10 | Main-VPS Claude Code may have prior Slack secrets / systemd services | **N/A here — Arturs handles** | Out of sandbox-Claude-Code's reach. Per decision § 6.4, Arturs creates the Slack app and generates `xoxb-` / `xapp-` tokens; per Addendum § 7.1, Arturs also provisions a dedicated AgentMail inbox and supplies its API key + inbox id. **Addendum § 7.2 supersedes the "env-inject at sandbox startup" mechanism:** main-VPS Claude Code now writes the values into `/etc/oscar/oscar.env` on the host (root-owned 0600); the sandbox sees the file via read-only bind-mount, not via env vars set at startup. Main-VPS Claude Code's discovery (recorded in Addendum § 7.2) confirmed there is no host-side `OSCAR_*` secrets file today and no systemd unit running Oscar Enterprise — OpenShell manages the sandbox lifecycle itself. |
| 11 | M1 infrastructure is in place (track-tagging convention, `src/{track}/` layout) | **Confirmed** | M1 entry at `SPRINT_LOG.md:2048` (Sprint M1 — [Infrastructure] — 2026-04-21 — Multi-track discipline infrastructure). Track tags applied retroactively to Sprints 0–10J; Sprints 10K onward and C1 land with track tags from start. ADRs 019–022 are placeholder reservations. The convention "ADRs from 019 onwards carry a track tag in the title, e.g. ADR 019 [Redline] — <title>" is now in CLAUDE.md (Multi-Track Discipline section). |
| 12 | No prior M2 entry exists | **Confirmed** | `grep -n "Sprint M2" SPRINT_LOG.md` returns no SPRINT_LOG matches. M2 is a blank slate. |
| 13 | SPRINT_LOG state on parallel tracks at pre-flight time | **Documented** | Most recent Redline: `### Sprint 10P` work in progress on branch `sprint-10P-counterparty-response` (head `566347a`, untracked artefacts `llm-{input,output,meta}-*`, `parsed-{plan,edits}.json`, `state-of-play.json`, `transcript.txt`, `nda-output-minimal.docx`). Most recent CoSec: Sprint C1 committed on `sprint-c1-cosec-drafter` (head `00ec758`); same files mirror as untracked in oscar-enterprise's working tree (confirmed by Arturs as the expected mirror, not a divergence). |
| 14 | `tests/` directory exists for Phase 1 unit tests | **Contradicted (none exists)** | `find . -type d -name tests` returns no matches. Phase 1 must establish a test layout convention. Recommendation: `tests/shared/{channels,agents,test_dispatcher.py}` mirroring `src/shared/`. Decision deferred to Phase 1 ADR 023; not blocking. |

### Evidence column — version + SHA snapshot

- **Python:** 3.13.12
- **deepagents:** 0.5.3
- **langgraph:** 1.1.8
- **langgraph-checkpoint:** 4.0.2
- **langchain:** 1.2.15
- **langchain-core:** 1.3.0
- **AsyncSubAgent class:** importable from `deepagents` (confirmed)
- **MemorySaver:** importable from `langgraph.checkpoint.memory` (alias for InMemorySaver in this version)
- **`origin/main` SHA at plan-time (initial Phase 0 exploration):** `a5a7646` (`CLAUDE.md: re-derive Phase 0 findings against new behavioural rules`)
- **`origin/main` SHA at M2 worktree creation:** `1789c8e` (`CLAUDE.md: bank MCP dual-ID rule ([Redline], from 10P Phase 2 smoke-test)`). One redline-track commit landed on main during planning; rebase was clean.
- **`origin/main` SHA at Phase 0 commit time (post-second-rebase):** `5ab6043` (`sprint-10P: SPRINT_LOG entry-in-progress (Outcome B mechanical; substantive verdict TBD) + matching one-line PROJECT.md Sprint Index`). Three further redline-track commits landed during pre-flight authoring (`566347a`, `8b76eae`, `5ab6043` — Sprint 10P Phase 2.1/2.3 prompts and run artefacts plus SPRINT_LOG draft); fast-forward was clean. The redline session is actively iterating on Sprint 10P; this pre-flight commit lands on top of `5ab6043`.
- **`sprint-c1-cosec-drafter` head:** `00ec758`
- **`sprint-10P-counterparty-response` head at pre-flight time:** `566347a` (note: this was the branch head at planning; the redline session has since pushed Phase 2.x commits to `main` directly, so `566347a` is now in main's history — the redline branch may have moved further by now).

---

## 2. Files M2 expects to CREATE (new)

| Path | Phase | Notes |
|------|-------|-------|
| `docs/sprints/M2-preflight.md` | Phase 0 | This file. |
| `docs/sprints/M2-spec.md` | Phase 0 | Verbatim copy of the user-supplied M2 spec, lightly cleaned for the "and and" typo near the end. Committed for posterity per CLAUDE.md § Git Discipline (cross-sprint context to main directly). |
| `docs/adr/023-PLACEHOLDER-channel-protocol-and-dispatcher.md` | Phase 0 reservation; written in Phase 1 | ADR title will carry the `[Infrastructure]` track tag per CLAUDE.md § Multi-Track Discipline. |
| `docs/adr/024-PLACEHOLDER-channel-deployment-topologies.md` | Phase 0 reservation; written in Phase 2 | **Renamed in Addendum § 7.3** from `024-PLACEHOLDER-slack-channel-deployment.md`. ADR scope (revised): Socket Mode (Slack) + WebSocket (AgentMail) deployment topologies + sandbox-as-runtime-host + bind-mount-at-startup decisions for token delivery. |
| `docs/adr/025-PLACEHOLDER-secrets-on-host-bind-mounted-readonly.md` | Phase 0 addendum reservation; written in Phase 2 | **Reserved in Addendum § 7.2.** ADR scope: shift from Sprint 3's in-sandbox `.env` to host `/etc/oscar/oscar.env` (root-owned 0600) exposed read-only via bind-mount; runtime config loader reads from the bind-mounted path. |
| `docs/architecture/channel-abstraction.md` | Phase 1 | Short note explaining the Channel Protocol's deliberate grow-by-sprint design. |
| `docs/architecture/slack-app-manifest.md` | Phase 2 | Manifest YAML + load instructions. |
| `docs/operations/runbook-channel-switch.md` | Phase 1+ | FakeChannel-as-substitute pattern docs. Seeded version in Phase 1; expanded in Phase 3. |
| `src/shared/channels/__init__.py` | Phase 1 | Package marker. |
| `src/shared/channels/base.py` | Phase 1 | `Channel` Protocol + `InboundMessage` dataclass (start, stop, post_message, on_inbound_message). |
| `src/shared/channels/fake.py` | Phase 1 | `FakeChannel` for tests; stores posted messages; `simulate_inbound()` to trigger handlers. |
| `src/shared/channels/slack/__init__.py` | Phase 2A | Package marker. (Phase split per Addendum § 7.1.) |
| `src/shared/channels/slack/channel.py` | Phase 2A | slack-bolt Socket Mode implementation; `app_mention` only; `conversation_id = f"{channel}:{thread_ts or ts}"`. |
| `src/shared/channels/slack/config.py` | Phase 2A | Pydantic-settings `BaseSettings` for `OSCAR_SLACK_*` (boundary validation only, per CLAUDE.md). |
| `src/shared/channels/slack/manifest.yaml` | Phase 2A | Slack app manifest. |
| `src/shared/channels/agentmail/__init__.py` | Phase 2B | **Added in Addendum § 7.1.** Package marker. |
| `src/shared/channels/agentmail/channel.py` | Phase 2B | **Added in Addendum § 7.1.** AgentMail WebSocket implementation per https://docs.agentmail.to/websockets; outbound socket subscribes to inbound emails for the configured inbox; `conversation_id` derived from email thread/message-id (exact derivation TBD on Phase 2B docs read). |
| `src/shared/channels/agentmail/config.py` | Phase 2B | **Added in Addendum § 7.1.** Pydantic-settings `BaseSettings` for `OSCAR_AGENTMAIL_*` (boundary validation only, per CLAUDE.md). |
| `src/shared/dispatcher.py` | Phase 1 | `Dispatcher`: derives `thread_id` from `conversation_id`, invokes GC with `config={"configurable": {"thread_id": thread_id}}`, posts reply via `channel.post_message`. |
| `src/shared/agents/__init__.py` | Phase 1 | Package marker. |
| `src/shared/agents/general_counsel.py` | Phase 1 | Copy-not-import of Sprint 9's GC pattern per decision § 6.1. `MemorySaver` wired at build time per § 6.2. |
| `src/shared/runtime/__init__.py` | Phase 3 | Package marker. |
| `src/shared/runtime/main.py` | Phase 3 | Long-running entry point that runs **inside the sandbox**, started by main-VPS with tokens injected as env vars per § 6.4. |
| `tests/shared/...` | Phase 1 | Test layout convention to be set in Phase 1 (no `tests/` dir exists today — sub-finding above). |

## 3. Files M2 expects to MODIFY (modify)

| Path | Phase | Change |
|------|-------|--------|
| `requirements.txt` | Phase 2 (one pass for both channels) | Append `slack-bolt==<latest stable on PyPI at install time>` per decision § 6.5 **and** the AgentMail Python SDK (package name TBD on PyPI lookup, latest stable at install time, per Addendum § 7.1); record both resolved versions in the M2 SPRINT_LOG entry's evidence section. |
| `policies/oscar-dev.yaml` | Phase 2 (one pass for both channels + bind-mount) | (a) Add a new `slack` entry under `network_policies:` permitting HTTPS/WSS:443 to `slack.com`, `wss-primary.slack.com`, `*.slack.com`, `files.slack.com`. (b) **Per Addendum § 7.1**, add an `agentmail` entry permitting outbound WSS to AgentMail's WebSocket edge (host(s) TBD on Phase 2B docs read). (c) **Per Addendum § 7.2**, add a read-only bind-mount of `/etc/oscar/oscar.env` under `filesystem_policy.read_only:` so the sandbox can source secrets from the host-side file. Tag DEV-only per ADR 006 where dev-specific. |
| `.env.example` | **AgentMail block added in Phase 0 addendum (this commit) per Addendum § 7.1**; Slack block remains Phase 2 | Phase 2 still appends documented placeholders `OSCAR_SLACK_BOT_TOKEN=` and `OSCAR_SLACK_APP_TOKEN=`. **Real tokens are written into `/etc/oscar/oscar.env` on the host (root-owned 0600) and exposed to the sandbox via read-only bind-mount per Addendum § 7.2 (supersedes the env-injection-at-startup mechanism in § 6.4); never written into any file the sandbox can commit.** |
| `docs/secrets.md` | **AgentMail entries added in Phase 0 addendum (this commit) per Addendum § 7.1**; Slack entries remain Phase 2 | Phase 2 still extends the secrets table with the two Slack vars; documents the host-bind-mount operational rule per Addendum § 7.2 / ADR 025 alongside the existing ADR 005 split. |
| `PROJECT.md` | Phase 3 (sprint-close) | Append `[Infrastructure]` Sprint Index one-liner for M2. |
| `SPRINT_LOG.md` | Phase 3 (sprint-close) | Append `### Sprint M2 — [Infrastructure] — <date> — Channel framework + Slack` entry following M1's format; record final SHA for `slack-bolt` pin and any deferred work for M3. |
| `TODO.md` | Phase 3 (sprint-close) if any carry-forwards emerge | Track-tagged items per CLAUDE.md § Multi-Track Discipline. |

## 4. Files M2 expects to READ but NOT modify

| Path | Why |
|------|-----|
| `src/redline/experiments/sprint-07-gc-commercial-routing/gc_and_commercial.py` | Pattern reference (two-level GC). |
| `src/redline/experiments/sprint-09-accept-reject-specialist/gc_commercial_acceptreject.py` | Pattern reference (three-level GC, more mature; Phase 1 GC copies from this verbatim per § 6.1). |
| `src/shared/llm/chat_model.py` | `get_chat_model(env_prefix=...)` is the seam M2's GC build will reuse. |
| `src/shared/llm/metadata_capture.py` | Routing-verification helper (CLAUDE.md § Redline Track Discipline). M2 may or may not call it; informational. |
| `src/cosec/agents/drafter.py` | Informational reference for the OPERATING_DISCIPLINE preamble pattern (defends against Deep Agents' auto-injected `task` tool). |
| `CLAUDE.md`, `PROJECT.md`, `SPRINT_LOG.md` | Governance baseline + sprint context. |
| `docs/secrets.md`, `docs/sandbox-egress-summary.md` | Source of truth for the conventions M2 extends. |
| `docs/adr/{002..018}*.md` | Accepted ADRs for cross-reference. Particularly relevant: 005 (secrets-vs-config), 006 (DEV/SIT policy parity), 009 (Deep Agents chat-model seam), 010 (per-agent model allocation), 014 (three-level delegation via compiled subagent). |
| `docs/adr/{019..022}*PLACEHOLDER*.md` | Existing reservations (3 redline + 1 cosec); confirms ADR 023+ is the next free slot for M2. |

## 5. No-clash with the redline track

**File ownership boundaries (as of pre-flight commit):**

- **Redline owns:** `src/redline/**`, `docs/redline/**`, branches `sprint-10*` (12 active/recent; current head of redline branch is `566347a` on `sprint-10P-counterparty-response`).
- **CoSec owns:** `src/cosec/**`, `docs/cosec/**`, branch `sprint-c1-cosec-drafter` (worktree at `/sandbox/oscar-cosec/`, head `00ec758`).
- **M2 will write under:** `src/shared/{channels,agents,runtime}/**`, `src/shared/dispatcher.py`, `requirements.txt`, `policies/oscar-dev.yaml`, `.env.example`, `docs/{sprints,architecture,operations,adr}/**`, root governance files (PROJECT.md / SPRINT_LOG.md / TODO.md at sprint close).

**Overlap check:**

- **`src/redline/`** — read only; zero modifications. ✓
- **`src/cosec/`** — read only; zero modifications. ✓
- **`src/shared/`** — M2 introduces new packages (`channels/`, `agents/`, `runtime/`) and one new top-level file (`dispatcher.py`). Existing `src/shared/llm/` is read but not modified. ✓
- **`requirements.txt`** — append-only change (one line: `slack-bolt`). Cleanly mergeable with any concurrent edits. ✓
- **`policies/oscar-dev.yaml`** — additive: a new `slack` block under `network_policies:`. Redline track has not modified policies recently (last touch in `git log --oneline policies/`: ADR 006 era). Cleanly mergeable. ✓
- **Root governance files** — touched by all tracks. Discipline: `git pull --rebase origin main` before every push (CLAUDE.md § Multi-Track Discipline). M2 follows this. Already validated: the rebase that brought `1789c8e` into the M2 worktree at creation time was clean. ✓

**Coordination protocol:**

- The empty-feature-branch draft PR (Step 5) is the visible coordination point that the redline session can see in the GitHub UI.
- This pre-flight document on main is the authoritative file footprint for M2; the redline session can grep it before touching `src/shared/` or `policies/oscar-dev.yaml`.
- During Phases 1–3, M2 will pull --rebase before every push. **Clean rebases** (concurrent redline commits without conflict) are not stop conditions; the new HEAD SHA is recorded and work proceeds. **Conflicts** are stop conditions; surface to Arturs without auto-resolution. (Per pre-flight review directive.)

## 6. Decisions adopted from Arturs's pre-flight review (2026-04-26)

The seven open questions raised in initial planning have been answered by Arturs and are baked into Phase 1+ scope. No further review needed on items 1–6; item 7's gate has been cleared by Arturs's confirmation that the untracked C1 files in oscar-enterprise mirror the committed state on `sprint-c1-cosec-drafter` at SHA `00ec758`.

1. **GC location: option (b) — copy-not-import.** Promote the Sprint 9 pattern verbatim into `src/shared/agents/general_counsel.py` for M2. Zero touches to `src/redline/`. The original Sprint 9 experiment file stays untouched. M2's GC and the redline-experiment GC are independent code paths until a future sprint reunifies them (out of scope here).

2. **Multi-turn memory: option (i) — `MemorySaver` in the GC build.** `langgraph.checkpoint.memory.MemorySaver` (= `InMemorySaver` in this version) is wired into `create_deep_agent(... checkpointer=MemorySaver())` at GC build time. The dispatcher passes `config={"configurable": {"thread_id": <derived from Slack conversation_id>}}` on every invocation. The GC's prompt / tools / subagents do not change.

3. **Docs commit target: confirmed.** `docs/sprints/M2-{preflight,spec}.md` and `docs/adr/02{3,4}-PLACEHOLDER-*.md` go to main directly per CLAUDE.md § Git Discipline. The draft PR opened against the feature branch points at this pre-flight on main as its coordination artefact.

4. **Slack workspace + app provisioning, and runtime topology: revised.** Arturs handles Slack app creation, `xoxb-` and `xapp-` token generation, and bot installation into a test channel. The **live Slack-bolt process runs inside the sandbox** alongside Deep Agents (one perimeter, no main-VPS↔sandbox bridge). Tokens are **env-injected by main-VPS at sandbox startup** and are **never written into any file the sandbox can commit**. `policies/oscar-dev.yaml` therefore must add Slack egress (HTTPS/WSS:443 to `slack.com`, `wss-primary.slack.com`, `*.slack.com`, `files.slack.com`). Phase 3 integration test runs the live runtime in-sandbox, observed by Arturs. **Superseded in part by Addendum § 7.1 + § 7.2:** (a) M2 ships a second channel in parallel (AgentMail WebSocket); the sandbox-as-runtime-host topology applies to both. (b) Token / API-key delivery moves from "env-injected at sandbox startup" to a host-side `/etc/oscar/oscar.env` (root-owned 0600) bind-mounted read-only into the sandbox; main-VPS Claude Code owns the file, sandbox reads it.

5. **`slack-bolt` version pin: latest stable at install time.** When `pip install slack-bolt` runs, take whatever PyPI returns as the latest stable, freeze it into `requirements.txt`, and record the resolved version string in the M2 SPRINT_LOG entry's evidence section (and update this pre-flight's evidence column if revisited).

6. **ADR number reservation: 023 and 024 reserved as placeholders.** Committed alongside this pre-flight: `docs/adr/023-PLACEHOLDER-channel-protocol-and-dispatcher.md` (Phase 1 content) and `docs/adr/024-PLACEHOLDER-slack-channel-deployment.md` (Phase 2 content). Body: one-line note "Reserved by Sprint M2 Phase 0; decision content to follow."

7. **`src/cosec/experiments/sprint-c1/` untracked-files question: cleared.** The untracked C1 tree in `/sandbox/oscar-enterprise/` is the expected mirror of `sprint-c1-cosec-drafter` head `00ec758` (worktrees share the object DB; the redline branch hasn't committed those paths so they appear untracked). Arturs confirmed 2026-04-26. Phase 1 may proceed.

---

Phase 1 will start once decisions 1–6 are absorbed and the Step 0 untracked-files gate (item 7) has cleared. Both conditions met as of the original Phase 0 commit; Phase 1 has further been deferred until the three additions in § 7 below were absorbed. With this addendum committed, Phase 1 is unblocked and starts on Arturs's go.

---

## 7. Phase 0 addendum (post-review, 2026-04-26)

After the initial Phase 0 review, Arturs adopted three further decisions before Phase 1 starts. They are recorded here as deltas to §§ 1–6 above. Where they revise a row in §§ 1–6, an inline pointer was added in that row; the addendum entry is the authoritative version.

### 7.1 Second channel: AgentMail (parallel to Slack)

M2 now ships **two** channels in parallel: Slack (Socket Mode) and AgentMail (WebSocket). Both are outbound-only transports — no public endpoint required from the sandbox in either case. AgentMail's WebSocket transport is documented at https://docs.agentmail.to/websockets and avoids the public-endpoint requirement that an SMTP / IMAP polling architecture would impose.

**Topology:**

- Each channel lives under its own subdirectory of `src/shared/channels/` (`slack/` and `agentmail/`) with **no shared implementation files**.
- **Phase 1** (framework spine) is unchanged.
- **Phase 2 splits** into:
  - **Phase 2A** — Slack channel implementation under `src/shared/channels/slack/` (existing scope from § 2 / § 6.4).
  - **Phase 2B** — AgentMail channel implementation under `src/shared/channels/agentmail/` (new).
  - Sequence Phase 2A and 2B in whichever order makes sense at execution time; they share no implementation files.
- **Shared files** (`requirements.txt`, `policies/oscar-dev.yaml`, `.env.example`, `docs/secrets.md`) get append-only additions for **both** channels in **one pass** during Phase 2 (rather than splitting these files across 2A and 2B). The `.env.example` and `docs/secrets.md` AgentMail entries are added in this addendum commit; Slack entries remain Phase 2 work.
- **Phase 3** starts **both** channels concurrently in the runtime entry point. The integration test covers both: an `@oscar-gc hello` Slack mention AND an inbound email to the GC's AgentMail inbox each yield a coherent reply within 30 seconds, with thread-memory preserved across follow-ups in each medium.

**AgentMail credentials:** Arturs provisions a new AgentMail inbox dedicated to the GC, separate from the existing OpenClaw inbox. The AgentMail API key is workspace-scoped (one key per workspace, not per inbox) and is the only secret. Two env vars are added to `.env.example` and `docs/secrets.md` in this commit:

- `OSCAR_AGENTMAIL_API_KEY` — workspace API key.
- `OSCAR_AGENTMAIL_INBOX_ID` — id of the GC's dedicated inbox.

Real values land in `/etc/oscar/oscar.env` on the host alongside the Slack tokens (see § 7.2).

**File-footprint deltas (consolidated):**

- New under `src/shared/channels/agentmail/`: `__init__.py`, `channel.py` (WebSocket client + inbound-email parsing + outbound `post_message` via AgentMail API), `config.py` (Pydantic-settings for `OSCAR_AGENTMAIL_*`).
- `requirements.txt` — append AgentMail Python SDK (latest stable at install time; package name TBD on Phase 2B PyPI lookup).
- `policies/oscar-dev.yaml` — additional egress block for AgentMail's WebSocket edge (host(s) TBD on Phase 2B docs read).
- `.env.example` — AgentMail block added in this addendum commit; Slack block remains Phase 2.
- `docs/secrets.md` — AgentMail entries added in this addendum commit (in the "Declared but not yet used" section, since no runtime code reads them yet); Slack entries remain Phase 2.

### 7.2 Secrets via host bind-mount (revises § 6.4)

Main-VPS Claude Code's discovery surfaced two facts that change the Sprint 3 secrets pattern:

- There is no host-side `OSCAR_*` secrets file today; Sprint 3's `.env` lives inside the sandbox's writable overlay (reachable to anything inside the sandbox).
- There is no systemd unit running Oscar Enterprise — OpenShell manages the sandbox lifecycle itself. The "env-injected by main-VPS at sandbox startup" mechanism described in § 6.4 has no concrete carrier in the current deployment.

**Decision:** Shift to a host-bind-mount pattern for all `OSCAR_*` secrets that this and future sprints introduce.

- `/etc/oscar/oscar.env` lives on the host: root-owned, mode 0600. **Owned by main-VPS Claude Code** (creation, write, rotation).
- The sandbox sees the file via a **read-only bind-mount** declared in `policies/oscar-dev.yaml` (alongside the existing read-only mounts of `/usr`, `/lib`, `/etc`, etc.).
- The runtime config loader reads env vars from the bind-mounted path, **not** from the in-sandbox `.env` Sprint 3 established. Sprint 3's `.env` pattern remains for developer-local non-secret configuration; the bind-mounted file is the only carrier for secrets.

**Phase 2 work (sandbox-Claude-Code, this session):**

- (a) Add a read-only bind-mount of `/etc/oscar/oscar.env` to `policies/oscar-dev.yaml`, alongside the Slack and AgentMail egress rules.
- (b) Update the runtime config loader to read env vars from the bind-mounted path rather than from the in-sandbox `.env` Sprint 3 established.
- (c) Write ADR 025 content (`docs/adr/025-PLACEHOLDER-secrets-on-host-bind-mounted-readonly.md`, reserved in this addendum commit) documenting the shift from Sprint 3's pattern.

**Out of scope here (handled by main-VPS Claude Code):**

- Creating the empty `/etc/oscar/oscar.env` file on the host (in progress at addendum-commit time).
- Writing the actual token values when Arturs hands them over (Slack `xoxb-` + `xapp-`, AgentMail API key + inbox id).

**Verification at end of Phase 2:**

- From inside the sandbox: `test -n "$OSCAR_SLACK_BOT_TOKEN"` returns truthy ("present").
- A live Slack `auth.test` call from the runtime, using the bot token sourced from the bind-mounted file, succeeds.

This supersedes § 6.4's "env-injected by main-VPS at sandbox startup" framing for token/secret delivery; bind-mount is the new mechanism. The "live Slack-bolt process runs inside the sandbox" topology in § 6.4 is unchanged.

### 7.3 ADR 024 placeholder rename + ADR 025 reservation

`docs/adr/024-PLACEHOLDER-slack-channel-deployment.md` is renamed to `docs/adr/024-PLACEHOLDER-channel-deployment-topologies.md` to reflect that the ADR now covers **both** Slack Socket Mode and AgentMail WebSocket deployment topologies (Phase 2A and 2B). The rename is performed in this commit via `git mv` (history preserved). ADR content is still Phase 2; the placeholder body is updated to the new scope.

`docs/adr/025-PLACEHOLDER-secrets-on-host-bind-mounted-readonly.md` is created in this commit as a reservation for the bind-mount decision (§ 7.2). Body: a one-paragraph note that decision content lands in Phase 2.

### 7.4 Phase ordering after addendum

- **Phase 1** — unchanged from the original spec / pre-flight. Framework spine: `src/shared/channels/{base,fake}.py`, `src/shared/dispatcher.py`, `src/shared/agents/general_counsel.py`, FakeChannel-backed unit tests, ADR 023 content, `docs/architecture/channel-abstraction.md`, `docs/operations/runbook-channel-switch.md` (seeded version).
- **Phase 2A** — Slack channel implementation; `requirements.txt` / `policies/oscar-dev.yaml` / `.env.example` / `docs/secrets.md` Slack additions; ADR 024 content (Slack section).
- **Phase 2B** — AgentMail channel implementation; `requirements.txt` / `policies/oscar-dev.yaml` AgentMail additions; ADR 024 content (AgentMail section).
- **Phase 2 (also, in either-2A-or-2B pass)** — bind-mount entry in `policies/oscar-dev.yaml`; runtime config loader reads from bind-mounted `/etc/oscar/oscar.env`; ADR 025 content. Verification per § 7.2.
- **Phase 3** — runtime starts both channels concurrently; integration test covers both; SPRINT_LOG entry; PROJECT.md Sprint Index one-liner.

Phases 2A, 2B, and the bind-mount work can be sequenced however makes sense at execution time. Phase 3 cannot start until all Phase 2 components have landed.
