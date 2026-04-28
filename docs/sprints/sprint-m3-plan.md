# Sprint M3 — LangChain orchestrator at the front door

**Status:** approved 2026-04-28; implementation in progress under auto mode.
**Author of plan:** Claude Code in the OpenShell sandbox, 2026-04-28.
**Branch:** `sprint-m3-orchestrator-langchain`, cut from `main` at HEAD `8465473` (verified clean tree).
**Working tree:** `/sandbox/oscar-m2`. Do not touch `/sandbox/oscar-enterprise`.

---

## 0. Approved decisions (recorded 2026-04-28)

The user approved this plan with the following answers to § 10's open questions:

- **Q1** Env-var triple naming: **`OSCAR_LLM_OSCAR_*`**.
- **Q2** ADR split: **two ADRs** — fill 019 (planner-executor split pattern) and write a separate 027 (10P-as-LangChain-tool).
- **Q3** Module disposition: **new `src/shared/agents/orchestrator.py`, delete `src/shared/agents/general_counsel.py`**.
- **Q4** Dispatcher field: **rename `gc_graph` → `agent_factory` and reshape from `Graph` to `Callable[..., Graph]`**.
- **Q5** Progress narration: **option (a) — `Channel.post_progress` + tool-bound callback**.
- **Q6** 10Q branch: **keep parked**.
- **Q7** Plan-file location: **move this content to `docs/sprints/sprint-m3-plan.md`** as the first commit on the new branch (this commit).
- **Q8** Live integration test at sprint close: **yes, run it**.

User added one Phase 1 requirement, recorded in § 5 below: `build_redline_tool` accepts `default_input_path`, `default_original_path`, `default_output_path` parameters set in `runtime/main.py` from a constants module; tool schema unchanged; defaults disappear in M4 when Slack file upload replaces them.

User recorded one context note for the future playbook sprint: ADR 026's draft text exists as untracked content at `/sandbox/oscar-m2-addendum/docs/adr/026-playbook-as-per-client-docx.md` — not on any branch. The playbook sprint should read it before superseding. M3 reuses ADR number 026 for the LangChain orchestrator decision (the addendum's draft was never committed and never given the 026 reservation).

---

## 1. Sprint identity

- **Sprint number:** M3. Cross-track infrastructure (M-series). Locked.
- **Branch:** `sprint-m3-orchestrator-langchain`. The longer name is justified — "orchestrator" is the architectural role and "LangChain" is the technology decision; both belong in the branch name to disambiguate from any future Deep-Agent-based orchestrator.
- **Character:** M3 swaps Oscar's front door from M2's three-level Deep Agent General Counsel chain to a single LangChain agent named "Oscar". Oscar uses the frontier model, routes inbound work, and (in M3) calls one tool: the 10P NDA counterparty-response pipeline. The sprint proves the pattern end-to-end on a hardcoded fixture path with a default author "Oscar", with progress narration in the Slack thread. Architectural sprint — the goal is the new shape, not new substance.

---

## 2. Phase 0 findings — what I verified, what I found, what changes the brief

### What the brief says, that I verified on disk

- M2 closed at HEAD `8465473`; `main` is clean apart from untracked `docs/research/`. ✓
- `src/shared/agents/general_counsel.py` exists with `def build_general_counsel(*, gc_model=None, checkpointer=None) -> CompiledStateGraph`. Three `create_deep_agent` calls inside (GC root → HOC subagent via `CompiledSubAgent` → accept-reject-reasoner specialist). ✓
- `src/shared/dispatcher.py` has `Dispatcher(channel, gc_graph)`, `thread_id := conversation_id` (no hashing, ADR 023), single-target routing, last-AIMessage extraction. ✓
- `src/shared/runtime/main.py` runs `secrets_loader → channel_factory → graph_factory → dispatcher → channel.start → stop_event.wait`, `_DEFAULT_STOP_TIMEOUT_SECS = 25.0`. ✓
- `src/shared/channels/slack/channel.py` is Socket Mode, `_LONG_MESSAGE_SOFT_LIMIT = 2500`, `_CONVERSATION_ID_SEP = ":"`, `app_mention` handler acks immediately and routes via `self._inbound`. File upload not implemented. No progress-narration hook. ✓
- `src/redline/experiments/sprint-10P/run.py` has a `run_once()` callable (lines 258-475) — but it is **non-parameterised** (hardcoded paths, hardcoded `AuthorConfig(name="Acme Counsel", date_override=date(2026,4,26))`). The brief said extracting a callable was sanctioned "if needed"; it is needed if we want to change inputs without editing `run_once`.
- `src/redline/experiments/sprint-10P/pipeline.py` has `extract_state_of_play(input_path)` and `apply_decisions(input_path, output_path, state, decisions, author_config, executor_callback)`. Stage A/B/C orchestrated monolithically inside `apply_decisions`. ✓
- `requirements.txt` pins: `langchain==1.2.15`, `langchain-core==1.3.0`, `langgraph==1.1.8`, `langchain-openai==1.1.14`, `deepagents==0.5.3`, `slack-bolt==1.28.0`, `python-docx==1.2.0`, `pydantic==2.13.2`. ✓
- 53 unit tests in the suite; dispatcher tests use a `StubGraph`, no end-to-end Slack→agent test. ✓
- ADRs go up to 025; PLACEHOLDERs at 019 (planner-executor split), 020 (plan data contract), 021 (specialist tier allocation), 022 (CoSec markdown as IR). ✓
- CLAUDE.md banked rule at lines 53-55 ("Deep Agents Is Reference Material, Not Runtime") is exactly as the brief described. Framework Stack at lines 19-21 says "Deep Agents as the agent harness on top". PROJECT.md Tech Stack table line 84: "Agent harness | Deep Agents on LangGraph". ✓
- `.env.example` carries `OSCAR_LLM_GENERAL_COUNSEL_*`, `OSCAR_LLM_HEAD_OF_COMMERCIAL_*`, `OSCAR_LLM_ACCEPT_REJECT_REASONER_*`, `OSCAR_LLM_REDLINE_SPECIALIST_*` triples. ✓

### What I found that the brief got wrong, or is silent on

1. **`langgraph.prebuilt.create_react_agent` is deprecated.** The brief floated it as a candidate primitive. At LangGraph 1.1.8 (our pin) it raises a DeprecationWarning pointing at `langchain.agents.create_agent`. We use the non-deprecated path. Both return `CompiledStateGraph` and accept `checkpointer`, so the dispatcher contract holds verbatim — only the import line changes.
2. **No ADR 026 exists on any branch.** The brief described ADR 026 as "drafted but uncommitted on the paused 10Q branch (per-client `.docx` playbook storage)". Verified: 10Q tip is `bd1f236`; `docs/adr/026-*` does not exist on main, on 10Q, or anywhere else. The brief's "ADR 026" refers to a *design direction* in flight on 10Q (a research note), not a committed ADR. M3 is therefore free to use ADR 026 for its first new ADR. (User flagged after approval that an addendum draft exists in `/sandbox/oscar-m2-addendum/docs/adr/026-playbook-as-per-client-docx.md` — also uncommitted, also not on any branch; the playbook sprint reads it then.) The architectural conflict (per-client `.docx` vs Store-backed playbooks) still exists but is a design conflict for the future playbook sprint to resolve, not a numbering conflict.
3. **`OSCAR_LLM_REDLINE_PLANNER_*` and `OSCAR_LLM_REDLINE_EXECUTOR_*` are not in `.env.example` on main.** They live only on feature branches that ran 10P. M3 must add them to `.env.example` on main when the redline pipeline is promoted from "experiment" to "first-class tool".
4. **10P's `run.py` uses bare-name imports** (`import pipeline`, `from prompt_builder import ...`). This works only because the script does `sys.path.insert(0, str(HERE))` at module load. The new parameterised callable will be imported from outside the experiments directory; the bare-name imports will fail. Fix: a small wrapper module at `src/redline/tools/redline.py` that does the `sys.path` insertion before importing — keeps the experiment directory untouched.
5. **`run_once`'s author is hardcoded "Acme Counsel".** The brief specifies M3's default is "Oscar". Editing `run_once` in place would shift the 10P fixture baseline (`nda-output-minimal.docx` would change author). Cleanest path: add a sibling function `run_redline` with `author_name="Oscar"` default; leave `run_once` byte-for-byte; M3 writes to a different output path (`nda-output-oscar.docx`).
6. **`oscar_config.yaml` does not exist** (PROJECT.md line 137 references it). **ADR 001 is missing** (`docs/adr/` starts at 002). Both are documentation gaps, not M3's problem; flagged in M3's SPRINT_LOG entry as known-debt.
7. **`/sandbox/oscar-enterprise` has the 11/5 history-rewrite split.** Confirmed. Not M3's problem. Branch state on `/sandbox/oscar-m2` is clean.
8. **Sprint 9 GC experiment file** (`src/redline/experiments/sprint-09-accept-reject-specialist/gc_commercial_acceptreject.py`) stays untouched — it is reference material for ADR 014's nesting pattern, not on the production path. M3's deletion of `src/shared/agents/general_counsel.py` does not touch the experiment file. Note in SPRINT_LOG so future readers don't think the experiment file is the new canonical.
9. **`tests/shared/agents/` does not exist yet.** New directory will be created in Phase 2 for `test_orchestrator.py`. `src/shared/agents/__init__.py` does not exist either; the directory is a PEP 420 namespace package and resolves fine. Do not "fix" by adding an `__init__.py` — that risks breaking path resolution that currently works.

---

## 3. Goal

A user @-mentions Oscar in `#oscar-test` with a brief like *"Please review the attached Zenith redlines on the Acme NDA — fixture-path test."* Oscar replies in the same thread within three seconds with a plain-English acknowledgement. Oscar then runs the 10P planner-executor pipeline end-to-end on hardcoded fixture inputs (`src/redline/experiments/sprint-10P/nda-input-minimal.docx` and `nda-original.docx`) and writes a redlined `.docx` to `src/redline/experiments/sprint-10P/nda-output-oscar.docx`. While the pipeline runs (55-128 seconds against GPT-5.5 + MiniMax), Oscar narrates progress to the same Slack thread in plain English at five milestones: extraction, planning, drafting, applying, done. Final message confirms completion and references the output file path on disk. Slack file upload is deferred — the file lives on disk in the sandbox.

---

## 4. Definition of done

Binary checks. Sprint closes when all are green:

- [ ] Live integration test passes: real Slack mention → real LLM calls → real `.docx` produced → at least three progress messages in the thread → final completion message.
- [ ] Unit-test suite at 53-or-better. After M3: ≈ 53 + ~9 new + ~10 modified = ~63 tests; all green.
- [ ] `src/shared/agents/general_counsel.py` deleted; replaced by `src/shared/agents/orchestrator.py`.
- [ ] `src/shared/dispatcher.py` renamed `gc_graph` → `agent_factory` with reshape.
- [ ] `src/shared/runtime/main.py` defaults to a factory that builds the orchestrator with the redline tool wired.
- [ ] `src/redline/tools/redline.py` exists with `RedlineToolInput`, `RedlineToolOutput`, `build_redline_tool(...)`.
- [ ] `src/redline/tools/_paths.py` constants module exists.
- [ ] `src/redline/experiments/sprint-10P/run.py` has the `run_redline` sibling; `run_once` unchanged byte-for-byte.
- [ ] ADRs 026, 027, 028, 029 committed; PLACEHOLDER 019 and 020 promoted to Accepted.
- [ ] `PROJECT.md` Tech Stack table line 84, `CLAUDE.md` Framework Stack lines 19-21 and banked-rule lines 53-55 revised.
- [ ] `SPRINT_LOG.md` has an M3 entry mirroring M2's structure; PROJECT.md Sprint Index has the one-line summary; TODO.md updated.
- [ ] `.env.example` carries `OSCAR_LLM_OSCAR_*`, `OSCAR_LLM_REDLINE_PLANNER_*`, `OSCAR_LLM_REDLINE_EXECUTOR_*` triples; legacy unused triples flagged with `# UNUSED as of M3` comments.
- [ ] Branch pushed; PR opened or merged to main per CLAUDE.md convention.
- [ ] Output `.docx` reviewed by Arturs; matches the 10P production-acceptable shape (two authors, layered changes, partner-quality comments).

---

## 5. Phases

Mirroring M2's Phase 0 / 1 / 2 / 3 structure.

### Phase 0 — Pre-flight investigation and conflict surfacing (no code)

**Output:** `docs/sprints/M3-preflight.md` confirming or contradicting every assumption in this plan against on-disk state. Includes:

- Smoke test of `langchain.agents.create_agent` with a one-tool toy agent against `get_chat_model(env_prefix="OSCAR_LLM_OSCAR")` to verify GPT-5.5 via OpenRouter does tool calling on the OpenAI-compat path. (If it doesn't, the issue is at the chat-model seam and gets surfaced before Phase 2 code lands.)
- Read of the four 10P prompt files (`planner_prompt.txt`, `executor_prompt.txt`, `user_prompt.txt`, the system-of-play helper) to verify the Slack brief can substitute for `user_prompt.txt` content with no implicit references to its shape.
- Inspection of the 53 tests; identify which couple to the M2 `gc_graph` field name vs the Deep-Agent internals.
- Confirmation that 10Q's `bd1f236` four-context-layer planner restructure stays parked.

**Exit criterion:** preflight document committed; smoke test green.

### Phase 1 — Redline tool wrapper (independent, mockable)

**Files created or modified:**

- `src/redline/experiments/sprint-10P/run.py` — *modified*: add a sibling function. Do not edit `run_once`.
  ```python
  def run_redline(
      *,
      input_path: Path,
      output_path: Path,
      original_path: Path,
      brief: str,
      author_name: str = "Oscar",
      author_date: date | None = None,
      progress_callback: Callable[[str], Awaitable[None]] | None = None,
  ) -> RedlineResult: ...
  ```
  `RedlineResult` is a frozen dataclass with `output_path`, `elapsed_seconds`, `decisions_total/accepted/countered/commented`, `output_size_bytes`, `mechanical_ok`, `notes`. Reproduces what `run_once` does — extract state of play, build planner prompt, invoke planner LLM, parse decisions, run executor callback, apply via `pipeline.apply_decisions`, verify output — but parameterises inputs and brief. Five `progress_callback` invocations: "extracting tracked changes", "thinking through positions", "drafting the redline", "applying changes", "done".
- `src/redline/experiments/sprint-10P/prompt_builder.py` — *modified*: `build_planner_user_prompt` accepts an optional `solicitor_brief: str | None = None` keyword; defaults to reading `user_prompt.txt`. Preserves `run_once` behaviour exactly.
- `src/redline/tools/redline.py` — *new*. Wrapper module that handles `sys.path` insertion before importing `run_redline`. Contains:
  - `class RedlineToolInput(BaseModel)` — `brief: str`, plus `input_path: str | None = None`, `original_path: str | None = None`, `output_path: str | None = None` (all three Optional in the schema; LLM passes only `brief` in M3, paths fall through to factory defaults).
  - `class RedlineToolOutput(BaseModel)` — flat output for the LLM to summarise.
  - ```python
    def build_redline_tool(
        *,
        default_input_path: Path,
        default_original_path: Path,
        default_output_path: Path,
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> BaseTool:
    ```
    Returns `StructuredTool.from_function(...)` with `name="redline_nda"`, async `coroutine`. Factory captures three default paths in closure; tool resolves any `None` field by substituting the corresponding default. Async tool — agent loop does not block on the 55-128s pipeline.
- `src/redline/tools/_paths.py` — *new* constants module:
  ```python
  REPO_ROOT = Path(__file__).resolve().parents[3]
  DEFAULT_NDA_INPUT = REPO_ROOT / "src/redline/experiments/sprint-10P/nda-input-minimal.docx"
  DEFAULT_NDA_ORIGINAL = REPO_ROOT / "src/redline/experiments/sprint-10P/nda-original.docx"
  DEFAULT_NDA_OUTPUT = REPO_ROOT / "src/redline/experiments/sprint-10P/nda-output-oscar.docx"
  ```

**Tests added:** `tests/redline/test_redline_tool.py`:

- `test_redline_tool_schema_round_trip`
- `test_run_redline_returns_result_on_fixture_paths` (LLMs mocked; docx pipeline runs for real)
- `test_run_redline_invokes_progress_callback`
- `test_run_once_unchanged` (smoke import-and-introspect)

**Exit criterion:** `pytest tests/redline/` green; existing `pytest tests/shared/` still 53/53 green.

### Phase 2 — LangChain orchestrator

Replace `general_counsel.py` with `orchestrator.py`. The two files share nothing structurally; a shim would mislead.

**Files:**

- `src/shared/agents/orchestrator.py` — *new*:
  - `OSCAR_SYSTEM_PROMPT` — plain-English prompt naming Oscar in first person, instructing him to call `redline_nda` for NDA reviews against a brief, to reply *"this work needs a partner-level review and I haven't been wired into the heads of practice yet — flagging for the human partner"* for anything else, and to keep all replies in plain English.
  - ```python
    def build_orchestrator(
        *,
        redline_tool: BaseTool,
        model: BaseChatModel | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> CompiledStateGraph:
    ```
    Defaults: `model = get_chat_model(env_prefix="OSCAR_LLM_OSCAR")`, `checkpointer = MemorySaver()`. Body: `return create_agent(model=model, tools=[redline_tool], system_prompt=OSCAR_SYSTEM_PROMPT, checkpointer=checkpointer, name="oscar")`. The orchestrator factory takes the tool as an argument rather than building it itself, because the tool's defaults belong to the runtime and the callback is per-invocation — keeping `build_orchestrator` ignorant of both keeps it pure.
- `src/shared/agents/general_counsel.py` — *deleted*. SPRINT_LOG note records the Sprint 9 experiment file at `src/redline/experiments/sprint-09-accept-reject-specialist/gc_commercial_acceptreject.py` as the surviving reference for the Deep Agents nesting pattern (ADR 014).

**Tests added:** `tests/shared/agents/test_orchestrator.py` (4 tests).

**Exit criterion:** four orchestrator tests green; 53-test baseline unchanged.

### Phase 3 — Dispatcher, runtime, progress narration, live integration

**Files modified:**

- `src/shared/channels/base.py` — add `Channel.post_progress(*, conversation_id: str, text: str) -> None` to the Protocol with default implementation that delegates to `post_message`. `FakeChannel` records progress posts in a separate `posted_progress` list. `SlackChannel.post_progress` is identical to `post_message` for M3.
- `src/shared/dispatcher.py` — rename field `gc_graph: Graph` → `agent_factory: Callable[[Callable[[str], Awaitable[None]]], Graph]`. The `handle` method now constructs a per-invocation progress callback bound to the conversation_id, calls the factory with it, and invokes the returned agent.
- `src/shared/runtime/main.py` — replace `graph_factory: GraphFactory = build_general_counsel` with `agent_factory: AgentFactory = _default_agent_factory`. The default factory closes over a `MemorySaver()` and the M3 default paths from `src/redline/tools/_paths.py`, builds the redline tool with the per-invocation progress callback, and builds the orchestrator. All other startup/shutdown logic preserved verbatim — secrets loader still runs first, signal handlers unchanged, `_DEFAULT_STOP_TIMEOUT_SECS = 25.0`.
- `.env.example` — add `OSCAR_LLM_OSCAR_*`, `OSCAR_LLM_REDLINE_PLANNER_*`, `OSCAR_LLM_REDLINE_EXECUTOR_*` triples; annotate `OSCAR_LLM_GENERAL_COUNSEL_*` and `OSCAR_LLM_REDLINE_SPECIALIST_*` with `# UNUSED as of M3 — slated for deletion in housekeeping sprint`.
- `PROJECT.md`, `CLAUDE.md` — see § 7.

**Tests modified and added:** five dispatcher tests adapted to renamed field and per-invocation factory; five runtime-main tests adapted to new factory shape; one new dispatcher test (`test_dispatcher_constructs_agent_per_invocation`); new live integration test under `tests/integration/test_slack_redline_pipeline.py` marked `@pytest.mark.live`.

**Exit criterion:** all unit tests pass; live integration test passes against real Slack workspace; Arturs has reviewed the produced `.docx`.

---

## 6. ADRs

Highest committed ADR on main is 025. Numbers 026 onward are free.

- **ADR 026 [Infrastructure] — LangChain orchestrator at the front door (Oscar).**
- **ADR 027 [Infrastructure] — 10P pipeline as a LangChain `StructuredTool`.**
- **ADR 028 [Infrastructure] — Slack progress narration via channel-level `post_progress` and tool-bound callback.**
- **ADR 029 [Infrastructure] — Agent harness layering, supersedes "Deep Agents Is Reference Material".**
- **PLACEHOLDER ADR 019 [Redline] — Planner-Executor Split Pattern (filled).**
- **PLACEHOLDER ADR 020 [Redline] — Plan Data Contract (filled).**
- **PLACEHOLDER ADRs 021 (Specialist Tier Allocation) and 022 (CoSec Markdown as IR)** stay PLACEHOLDER. M3 introduces no new specialists and does not touch CoSec.

Each ADR's full Decision/Context/Options/Consequences sits inline in the sprint plan's earlier draft (now the audit trail) and lands in `docs/adr/` as its own file ≤50 lines per CLAUDE.md.

---

## 7. CLAUDE.md and PROJECT.md text revisions

**PROJECT.md Tech Stack table line 84** — replace:
> Agent harness | Deep Agents on LangGraph

with:
> Agent harness | Layered: LangChain (front door, ADR 026), Deep Agents (practice-area heads, ADR 014), direct chat_model.invoke (long-running pipelines, ADR 019) — see ADR 029

**CLAUDE.md Framework Stack section (lines 19-21)** — replace the existing one-paragraph statement with:
> This project uses **NVIDIA OpenShell** for sandbox runtime and governance, **LangGraph / LangChain** as the orchestration foundation, and a **layered agent harness** on top: **LangChain** at the front door (Oscar — see ADR 026), **Deep Agents** for practice-area heads where the work fits the subagent-delegation shape (see ADR 014), and **direct chat-model invocation** for long-running pipelines like the redline planner-executor (see ADR 019). Choose the harness that fits the work; do not reach for alternative agent frameworks (CrewAI, AutoGen, OpenAI Agents SDK, custom orchestrators) unless an ADR explicitly authorises it. The model layer underneath is dependency-injected — see PROJECT.md's LLM Policy section.

**CLAUDE.md banked rule (lines 53-55)** "Deep Agents Is Reference Material, Not Runtime" — replace with:
> ## [Process] [Architecture] Agent Harness Per Use-Case
>
> Oscar's agent harness is layered. LangChain at the front door (Oscar's orchestrator — see ADR 026). Deep Agents per practice-area head where the work fits the subagent-delegation shape (Sprint 9 GC commercial-acceptreject is the canonical reference). Direct `chat_model.invoke` with stdlib infrastructure for long-running pipelines (10P redline). Choose the harness that fits the work; ADR 029 records the layering principle and supersedes the prior "Deep Agents is reference material" framing.

---

## 8. Risks (carried forward)

1. **Slack acknowledgement within 3 seconds.** Mitigation: tool's progress callback fires synchronously at start with "Working on this — give me a couple of minutes"; dispatcher posts within ~2s.
2. **`run_once` parameterisation regression risk.** Mitigation: sibling `run_redline`; `run_once` byte-for-byte unchanged.
3. **LangGraph singleton-agent issue (#2040).** Mitigation: documented in ADR 028; per-conversation lock deferred to M4+.
4. **GPT-5.5 tool calling via OpenRouter.** Mitigation: Phase 0 smoke test before Phase 2 lands.
5. **Brief-as-string substitution into planner prompt.** Mitigation: Phase 0 reads all four prompt files; planner_prompt gains one paragraph if needed.
6. **Per-invocation agent rebuild memory pressure.** Mitigation: millisecond-scale; profile in M4 if visible.
7. **Test suite drift from field rename.** Mitigation: rename touches a small surface; preserve 53-test pass count.

---

## 9. Out of scope, follow-ons

M3 stops at "Oscar runs the redline tool itself on a hardcoded fixture path with a default author 'Oscar'." Subsequent sprints in order:

- **M4: Slack file upload + download.**
- **Playbook sprint** (Store-backed playbooks; supersedes the 10Q/addendum direction).
- **Employer/client configuration sprint** (author flips from "Oscar" default to configured employer name).
- **Practice-area heads sprint** (Head of Commercial as a Deep Agent; orchestrator's fallback message replaced by delegation rule).
- **Counterparty layer + deal layer.**
- **Reflection loop + approval queue.**

---

## 10. Resolved decisions (audit)

1. Env-var triple for Oscar: **`OSCAR_LLM_OSCAR_*`**.
2. ADR split: **two ADRs** — fill PLACEHOLDER 019 and write 027 separately.
3. Module disposition: **new orchestrator.py; delete general_counsel.py**.
4. Dispatcher field: **rename and reshape** `gc_graph` → `agent_factory: Callable[..., Graph]`.
5. Progress narration: **option (a)** — `Channel.post_progress` + tool-bound callback.
6. 10Q paused branch: **keep parked**.
7. Plan-file location: **moved here**.
8. Live integration test: **runs at sprint close**.

Phase 1 addition: `build_redline_tool` accepts `default_input_path`, `default_original_path`, `default_output_path` parameters set in `runtime/main.py` from `src/redline/tools/_paths.py`. Tool schema unchanged. Defaults disappear in M4.

---

End of plan.
