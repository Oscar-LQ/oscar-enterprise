# ADR 014 — Three-Level Delegation via `CompiledSubAgent`

- **Status:** Accepted
- **Date:** 2026-04-18
- **Scope:** How Oscar nests sub-agents three levels deep in Deep Agents (General Counsel → Head of Commercial → accept/reject specialist) given that `SubAgent` has no `subagents` field
- **Supersedes:** none
- **Related:** ADR 010 (per-agent allocation), Sprint 7 log (two-level scaffolding), Sprint 9 brief

## Context

Sprint 7 built two-level delegation: General Counsel passes a list of
`SubAgent` dicts to `create_deep_agent(subagents=...)`, each wrapping a
department head. Sprint 9 adds a third level: Head of Commercial must
itself be able to delegate to functional specialists (first one:
`accept-reject-reasoner`).

Reading Deep Agents' source
(`deepagents/middleware/subagents.py:25-127`): the `SubAgent` TypedDict
supports `name`, `description`, `system_prompt`, `tools`, `model`,
`middleware`, `interrupt_on`, `skills`, `permissions`,
`response_format` — and nothing else. There is no
`SubAgent["subagents"]` field. A flat-parent-with-many-children topology
is what `SubAgent` encodes.

However (`subagents.py:130-159`), `CompiledSubAgent` is an alternative
entry form:

```python
class CompiledSubAgent(TypedDict):
    name: str
    description: str
    runnable: Runnable
```

`SubAgentMiddleware._get_subagents()` (`subagents.py:538-542`) preserves
a `CompiledSubAgent`'s `runnable` as-is. `create_deep_agent(...)` itself
returns a compiled LangGraph runnable. So nothing stops us from
building Head of Commercial as its own `create_deep_agent` (with its own
`subagents=[...]`) and then wrapping the compiled graph as a
`CompiledSubAgent` when passing it to the General Counsel.

## Decision

**Head of Commercial is built with `create_deep_agent(...)` — its own
Deep Agent graph, with its own `subagents=[accept_reject_reasoner]` —
and passed to General Counsel as a `CompiledSubAgent`:**

```python
hoc_graph = create_deep_agent(
    model=hoc_model,
    tools=[],
    system_prompt=HOC_SYSTEM_PROMPT,
    subagents=[accept_reject_reasoner_spec],  # SubAgent dict
)

gc_agent = create_deep_agent(
    model=gc_model,
    tools=[],
    system_prompt=GC_SYSTEM_PROMPT,
    subagents=[{
        "name": "head-of-commercial",
        "description": "...",
        "runnable": hoc_graph,  # CompiledSubAgent form
    }],
)
```

This is the documented mechanism for plugging an arbitrary runnable
graph under a Deep Agent's `task` tool. The `SubAgent` spec's fixed set
of fields is by design — complex agents are expected to live as
pre-compiled graphs.

Rejected:
- **Flat topology (GC directly invokes the specialist).** Breaks the
  org-chart metaphor in PROJECT.md; every specialist would live under
  GC's `subagents` list. GC's prompt would have to name every specialist
  across every department. Does not scale past one department.
- **Custom LangGraph graph that wires HOC and the specialist together
  without Deep Agents.** Works, but we lose the default middleware
  stack (planning, filesystem, summarisation, patch-tool-calls,
  sub-agent routing) that ADR 009 deliberately plugs into. Premature
  complexity.
- **`SubAgent["subagents"]` as a patch upstream.** Not a decision we
  can make unilaterally; would need a feature request and an install
  cycle. Unnecessary once the compiled-runnable path is confirmed.

## Consequences

- **Pro:** arbitrary depth is possible — each `CompiledSubAgent` can
  itself have `subagents=[...]`, all the way down, at the cost of one
  extra `create_deep_agent` call per level.
- **Pro:** each department head is a self-contained Deep Agent — it can
  be unit-tested independently, have its own default middleware stack,
  its own model allocation, its own permissions. Matches the
  functional-agent decomposition PROJECT.md describes.
- **Pro:** the `task` tool's structured-response path (ADR 013) works at
  every level — the JSON from the specialist reaches HOC as a
  `ToolMessage`, and HOC's plain-text synthesis reaches GC as a
  `ToolMessage`. Nesting does not break the serialisation contract.
- **Con:** `CompiledSubAgent` does not inherit `interrupt_on` from the
  parent (`graph.py:388-392` docstring). If human-in-the-loop is added
  to GC, HOC's inside-agent tools (its own `task`, filesystem ops) will
  not inherit the interrupt config; HITL has to be configured at each
  compile site. Not a concern in Sprint 9; flagged for when HITL lands.
- **Con:** the per-level middleware stack is built twice (once for GC,
  once for HOC), including a `SummarizationMiddleware` and an
  `AnthropicPromptCachingMiddleware` at each level. Harmless — the
  caching middleware no-ops for non-Anthropic models (Sprint 6 surprise
  4), and the summarization middleware only fires when the context
  grows. But the stack isn't free.
- **Con:** each Deep Agent auto-inserts a general-purpose subagent
  unless one named `general-purpose` is supplied (Sprint 6 surprise 3).
  HOC's general-purpose subagent is distinct from GC's — three latent
  subagents across the tree. Enforcement stays prompt-level: the system
  prompt at each level names the intended specialists only.
