# ADR 027 [Infrastructure] — 10P pipeline as a LangChain `StructuredTool`

**Status:** Accepted (Sprint M3, 2026-04-28).

## Context

M2's General Counsel chain delegated commercial decisions to a Deep Agent subagent (Head of Commercial), which delegated structured judgements to a sub-specialist (Accept/Reject Reasoner). The shape was right for *judgement delegation*. It is wrong for *deterministic operation invocation* — the redline pipeline is not a judgement, it is a 55-128-second function over a `.docx` whose internal LLM split (planner + executor, ADR 019/020) is opaque to the caller.

ADR 026 establishes Oscar (the M3 front door) as a LangChain agent. The natural way for a LangChain agent to invoke a deterministic operation is as a tool registered via `tools=[...]` on `create_agent`. M3 wraps the 10P pipeline accordingly.

The brief sanctioned the smallest possible 10P touch — "extracting a callable" — without changing pipeline logic. The 10P entry point `run_once` is non-parameterised (hardcoded fixture paths and the "Acme Counsel" author baked into 10P's `.docx` baseline). M3 adds a sibling `run_redline` rather than editing `run_once`, preserving the demonstrator script byte-for-byte.

## Decision

The 10P planner-executor pipeline is exposed to Oscar as a LangChain `StructuredTool` named `redline_nda`.

- **Tool factory.** `build_redline_tool(*, default_input_path, default_original_path, default_output_path, progress_callback=None) -> BaseTool` in `src/redline/tools/redline.py`. Async coroutine — the 55-128-second pipeline runs without blocking the agent loop. Three default-path parameters captured in closure; the LLM-supplied input may override per-field. Defaults vanish in M4 when Slack file upload supplies attachment paths.
- **Tool input schema.** `RedlineToolInput` (Pydantic): `brief: str` (required), `input_path / original_path / output_path: str | None = None` (Optional; None falls through to the factory default).
- **Tool output schema.** `RedlineToolOutput` (Pydantic): flat fields the LLM can paraphrase — output_path, elapsed_seconds, decisions_total/accepted/countered/commented, summary.
- **10P sibling.** `run_redline(*, input_path, output_path, original_path, brief, author_name="Oscar", author_date=None, progress_callback=None) -> RedlineResult` added alongside `run_once` in `src/redline/experiments/sprint-10P/run.py`. Async; mirrors `run_once`'s body but parameterises inputs and the brief, defaults the author to "Oscar", and emits five progress-callback milestones (extracting / thinking / drafting / applying / done). No diagnostic files written — the structured `RedlineResult` is the output.
- **Brief substitution.** `prompt_builder.build_planner_user_prompt` gains an additive `solicitor_brief: str | None = None` keyword that defaults to reading `user_prompt.txt` (preserves `run_once`).
- **Path-handling wrapper.** `src/redline/tools/redline.py` inserts the 10P experiment directory on `sys.path` before importing `run.py`, working around the hyphen in `sprint-10P` (Python rejects hyphens in package names).
- **Constants.** `src/redline/tools/_paths.py` holds the M3 fixture path constants (`DEFAULT_NDA_INPUT`, `DEFAULT_NDA_ORIGINAL`, `DEFAULT_NDA_OUTPUT`). CLAUDE.md "no magic strings" rule covered.

## Options considered

- **Keep the M2 subagent shape (delegate to a "redline specialist" agent).** Mismatch — subagents are for judgement delegation; the pipeline is a deterministic operation with internal judgement (planner + executor) opaque to the caller.
- **Embed the pipeline inline in the orchestrator.** Loses isolation (orchestrator becomes harder to test); makes future tool addition awkward.
- **MCP-style external tool server.** Overkill for in-process call; adds a process boundary that serves no immediate purpose.

## Consequences

- The pipeline acquires its first parameterised public entry (`run_redline`). `run_once` stays byte-for-byte unchanged — the 10P fixture baseline (`nda-output-minimal.docx`) is preserved. M3 writes to a separate output path (`nda-output-oscar.docx`) so the two coexist.
- The tool's Optional path schema is wider than M3 needs (the LLM only ever supplies `brief` in M3; the paths fall through to defaults). The wider schema lands the right shape for M4's Slack file upload without a schema change.
- Other future stdlib pipelines (e.g. comment-thread responder, playbook-adherence reviewer) follow the same wrapping pattern: callable in the experiments directory, path-handling wrapper module, LangChain `StructuredTool` registered on Oscar.
- ADR 019 (planner-executor split) is the *internal* architectural pattern; this ADR is the *external* infrastructure decision. Two ADRs, two decisions — a redline-track concern and a cross-track concern. They evolve independently.
