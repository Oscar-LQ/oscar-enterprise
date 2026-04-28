# Sprint M3 — Phase 0 Preflight

**Date:** 2026-04-28.
**Branch:** `sprint-m3-orchestrator-langchain`, cut from `main` at `8465473`.
**Purpose:** Surface every assumption in the M3 plan against on-disk state before code lands.

---

## 1. LangChain agent primitive — verified

`langchain.agents.create_agent` is the non-deprecated path. Signature inspected at the pinned `langchain==1.2.15`:

```
create_agent(
    model,                                    # POSITIONAL_OR_KEYWORD
    tools=None,                               # POSITIONAL_OR_KEYWORD
    *,
    system_prompt=None,
    middleware=(),
    response_format=None,
    state_schema=None,
    context_schema=None,
    checkpointer=None,
    store=None,
    interrupt_before=None,
    interrupt_after=None,
    debug=False,
    name=None,
    cache=None,
) -> CompiledStateGraph[...]
```

The dispatcher contract (M2's `gc.ainvoke({"messages": [...]}, config={"configurable": {"thread_id": ...}})`) holds verbatim because `create_agent` returns the same `CompiledStateGraph` shape Deep Agents returned. Carry-forward: M3 plan's call shape is `create_agent(model=model, tools=[redline_tool], system_prompt=OSCAR_SYSTEM_PROMPT, checkpointer=checkpointer, name="oscar")`.

`langgraph.prebuilt.create_react_agent` is deprecated at LangGraph 1.1.8; not used.

## 2. Chat-model seam — verified

`src/shared/llm/chat_model.py` exposes `get_chat_model(env_prefix=...)` reading `{env_prefix}_PROVIDER`, `{env_prefix}_MODEL`, `{env_prefix}_API_KEY` at call time. M3 will use `env_prefix="OSCAR_LLM_OSCAR"`.

## 3. Host secrets — partial

`/etc/oscar/oscar.env` is bind-mounted read-only into the sandbox (ADR 025) and currently carries:

- `OSCAR_LLM_PROVIDER` / `_MODEL` / `_API_KEY` (default slot, sprints 3-6).
- `OSCAR_LLM_GENERAL_COUNSEL_*` triple.
- `OSCAR_LLM_HEAD_OF_COMMERCIAL_*` triple.
- `OSCAR_LLM_ACCEPT_REJECT_REASONER_*` triple.
- `OSCAR_LLM_REDLINE_SPECIALIST_*` triple.
- `OSCAR_LLM_REDLINE_PLANNER_*` triple.
- `OSCAR_LLM_REDLINE_EXECUTOR_*` triple.
- `OSCAR_LLM_COSEC_DRAFTER_*` triple.
- `OSCAR_SLACK_BOT_TOKEN`, `OSCAR_SLACK_APP_TOKEN`.

`OSCAR_LLM_OSCAR_*` is **not yet** in `/etc/oscar/oscar.env`. The operator must populate it on the host before the live integration test at sprint close. `OSCAR_LLM_REDLINE_PLANNER_*` and `OSCAR_LLM_REDLINE_EXECUTOR_*` are already on the host but missing from `.env.example` on `main` — M3 adds them to the example.

## 4. 10P prompt files — brief substitution path verified

`src/redline/experiments/sprint-10P/prompt_builder.py:_solicitor_brief()` reads `user_prompt.txt` and returns its content. `build_planner_user_prompt(state, original_nda_clean_text)` calls `_solicitor_brief()` and assembles three blocks: brief / state-of-play JSON / clean original NDA text.

`planner_prompt.txt` (the system prompt) names the inputs it expects in section "## Inputs" — first input is "the partner's brief". No implicit reference to user_prompt.txt's content shape; substituting any plain-English brief is safe. The prompt's behavioural rules (rules 1-5) are independent of brief content.

The substitution point in M3 is `build_planner_user_prompt`'s call to `_solicitor_brief()`. M3 adds an optional `solicitor_brief: str | None = None` keyword to `build_planner_user_prompt`; when None, it falls back to `_solicitor_brief()` (current behaviour preserved for `run_once`); when supplied, the supplied string substitutes for the file content.

## 5. 10P `run_once` — confirmed non-parameterised

`run.py:258-475`. Hardcodes:
- Input: `HERE / "nda-input-minimal.docx"`
- Original: `HERE / "nda-original.docx"`
- Output: `HERE / "nda-output-minimal.docx"`
- Author: `AuthorConfig(name="Acme Counsel", date_override=date(2026, 4, 26))`
- Brief: read from `user_prompt.txt` (via `_solicitor_brief()`).

Calls `get_chat_model(env_prefix="OSCAR_LLM_REDLINE_PLANNER")` and `OSCAR_LLM_REDLINE_EXECUTOR`. The pipeline body (state-of-play → planner → executor callback → apply_decisions → verify) is the contract `run_redline` reproduces with parameterised inputs and a progress callback at five milestones.

## 6. Test surface — confirmed

`tests/shared/test_dispatcher.py` references `gc_graph` once, at line 61 (the `dispatcher` pytest fixture). All five test bodies use the fixture — none reference the field directly. Rename to `agent_factory` touches the fixture line and any test that constructs a `Dispatcher` inline (none today).

`tests/shared/test_runtime_main.py` uses the `graph_factory=...` kwarg at five call sites (lines 88, 117, 145, 168, 217). All five become `agent_factory=lambda cb: ...` after the rename and reshape.

Total surface: ~10 lines across two files. Manageable.

## 7. 10Q branch — staying parked

Per user decision (Q6). The 10Q tip at `bd1f236` reorganised the planner prompt into a four-context-layer shape; that work assumes a playbook layer that does not exist on `main`. M3's single-paragraph-from-Slack brief uses the existing prompt structure unchanged. The branch is preserved on origin for the future playbook sprint.

## 8. ADR 026 numbering — free

Verified: no `docs/adr/026-*` exists on `main`, on `sprint-10Q-playbook-layer`, or any other branch. The ADR 026 the original brief was concerned about is a draft research note in the addendum tree (`/sandbox/oscar-m2-addendum/docs/adr/026-playbook-as-per-client-docx.md`), not a committed ADR. M3 takes ADR 026 for the LangChain orchestrator decision.

## 9. Risks deferred

- **GPT-5.5 tool calling via OpenRouter.** Not pre-verified with a real LLM call. Reasoning: the LangChain `BaseChatModel.bind_tools` API is the standard tool-calling path and `langchain-openrouter` implements it; OpenAI-compat tool calling is supported by `openai/gpt-5.5` upstream. The end-to-end live integration test at sprint close exercises this path. If it fails there, the issue surfaces with full diagnostic output and we adjust.
- **Per-invocation agent rebuild.** Memory pressure expected to be negligible (graph compilation is millisecond-scale); profile in M4 if visible.

## 10. Phase 0 exit

All Phase 0 checkpoints met. No blockers found. Phase 1 can begin.

Carry-forward to Phase 1 implementation:
- `OSCAR_LLM_OSCAR_*` triple needs operator action on the host before sprint close.
- `build_planner_user_prompt` gets an additive `solicitor_brief` keyword.
- `run_redline` is a sibling function (not a rewrite) of `run_once`.
- New module path `src/redline/tools/redline.py` does the `sys.path` insertion to import 10P's bare-name modules (`pipeline`, `prompt_builder`, etc.).
