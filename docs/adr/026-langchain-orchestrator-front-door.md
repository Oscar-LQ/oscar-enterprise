# ADR 026 [Infrastructure] — LangChain orchestrator at the front door (Oscar)

**Status:** Accepted (Sprint M3, 2026-04-28).

## Context

M2 shipped a three-level Deep Agent General Counsel chain at the front door — GC root → Head of Commercial subagent → Accept/Reject Specialist. M2's GC was a copy-not-import of the Sprint 9 pattern; it worked for the M2 demo (a one-liner partner question routed to a structured-decision specialist) but is the wrong shape for the long-run architecture.

The 2026-04-28 architectural handover sets a different shape:

- The agent at the front door is the user-facing identity "Oscar". One agent, one identity, multiple channels.
- Oscar performs simple commercial work himself by calling a tool (M3: the 10P NDA counterparty-response pipeline as a LangChain `StructuredTool` — see ADR 027).
- Oscar delegates more complex work to practice-area heads (later sprints; Head of Commercial first).
- The 10P planner-executor pair (ADR 019/020) is a load-bearing primitive Oscar calls as a tool, not a sub-agent he delegates to.

The Deep Agent harness is the right shape for *judgement delegation* (a department head with sub-specialists). It is the wrong shape for *tool-calling orchestration* (a single agent invoking deterministic operations). Front-door work is the latter.

## Decision

Oscar is built with `langchain.agents.create_agent`, not `deepagents.create_deep_agent`.

- **Construction.** `build_orchestrator(*, redline_tool, model=None, checkpointer=None) -> CompiledStateGraph` in `src/shared/agents/orchestrator.py`. Defaults: `model = get_chat_model(env_prefix="OSCAR_LLM_OSCAR")`, `checkpointer = MemorySaver()`. The redline tool is supplied by the runtime (constructed with M3 fixture-path defaults and a per-invocation progress callback per ADR 028).
- **System prompt.** `OSCAR_SYSTEM_PROMPT` instructs Oscar in the first person. Routing rules: NDA review against a brief → call `redline_nda`; anything else → reply *"this work needs a partner-level review and I haven't been wired into the heads of practice yet — flagging for the human partner"*. No clarifying questions before tool call. No mention of internal plumbing. Plain English.
- **Module disposition.** `src/shared/agents/general_counsel.py` is deleted. The Sprint 9 experiment file at `src/redline/experiments/sprint-09-accept-reject-specialist/gc_commercial_acceptreject.py` survives untouched as the canonical reference for the Deep Agents nesting pattern (ADR 014).
- **Dispatcher contract.** `create_agent` returns a `CompiledStateGraph`. The dispatcher's `ainvoke({"messages": [...]}, config={"configurable": {"thread_id": ...}})` shape from M2 holds verbatim — only the import path changes.
- **API.** Uses `langchain.agents.create_agent`. Note: `langgraph.prebuilt.create_react_agent` is deprecated at LangGraph 1.1.8 with a migration warning pointing at `langchain.agents.create_agent`. We use the non-deprecated path.

## Options considered

- **Stay with Deep Agents.** Mismatch — `create_deep_agent`'s subagent model fits department-head delegation, not tool-calling orchestration. Forces an unnatural decomposition where Oscar would have a "redline-specialist" subagent that does nothing but call the pipeline.
- **LangGraph low-level `StateGraph`.** More control, more boilerplate, no upside for a one-tool agent. Reach for it later if Oscar needs custom routing graphs.
- **Custom orchestrator.** Reinventing the wheel. The LangChain agent loop already implements the message → bind_tools → tool_call → tool result → message loop with checkpointer support.

## Consequences

- Extends ADR 010 (per-agent model allocation) by adding a new role: Oscar. Env-var triple `OSCAR_LLM_OSCAR_*` lands in `.env.example` and on the host (`/etc/oscar/oscar.env`). `OSCAR_LLM_GENERAL_COUNSEL_*` becomes unused after M3 — kept in `.env.example` with a `# UNUSED as of M3` comment, slated for deletion in a housekeeping sprint.
- Does not supersede ADR 014. The CompiledSubAgent nesting pattern still applies for practice-area heads when those land. ADR 029 records the harness-layering principle.
- The dispatcher reshape (ADR 028) is technically independent but lands together with this decision because progress narration needs a per-invocation tool rebuild — and a per-invocation tool rebuild is most natural with a per-invocation agent rebuild.
- Oscar's single-tool shape is the M3 starting point. Future sprints add more tools (Slack file upload + download, the playbook layer's lookup tools) and eventually delegation primitives to practice-area heads.
