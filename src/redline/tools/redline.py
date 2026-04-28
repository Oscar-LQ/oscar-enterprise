"""LangChain StructuredTool wrapping the 10P NDA counterparty-response pipeline.

This module is the bridge between Oscar (the LangChain orchestrator at
the front door) and the 10P redline pipeline. The orchestrator sees a
single tool, ``redline_nda``, which it calls with a plain-English brief.
Internally the tool delegates to :func:`run_redline` in the 10P
experiment module.

The 10P experiment directory is named ``sprint-10P`` (with a hyphen),
which Python rejects as an importable package name. This module sidesteps
that by inserting the experiment directory on ``sys.path`` before
``importlib.import_module("run")`` resolves the bare module name. The
experiment directory's own ``sys.path`` insertion (in ``run.py`` for the
demonstrator script) is redundant in this codepath but harmless.

ADRs: 026 (LangChain orchestrator), 027 (10P-as-LangChain-tool),
028 (channel-level progress narration).
"""
from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from importlib import import_module
from pathlib import Path

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

# Insert the 10P experiment directory on sys.path so `import pipeline`,
# `from prompt_builder import ...`, and similar bare-name imports inside
# run.py resolve. Idempotent — adding the same path twice is fine, and
# run.py also inserts it.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[3]
_TENP_DIR = _REPO_ROOT / "src/redline/experiments/sprint-10P"
if str(_TENP_DIR) not in sys.path:
    sys.path.insert(0, str(_TENP_DIR))

_run_module = import_module("run")
run_redline = _run_module.run_redline
RedlineResult = _run_module.RedlineResult


class RedlineToolInput(BaseModel):
    """Input schema the LangChain agent fills when calling ``redline_nda``.

    M3 lets the LLM supply only ``brief``; the three path fields are
    Optional and resolve to the factory's defaults when None. M4 will
    populate ``input_path`` / ``output_path`` from Slack file uploads.
    """

    brief: str = Field(
        description=(
            "The partner's plain-English instruction for this round of "
            "counterparty review — what positions to push back on, what "
            "to accept, what to comment on. Pass the user's Slack message "
            "text here verbatim."
        )
    )
    input_path: str | None = Field(
        default=None,
        description=(
            "Path to the .docx the counterparty returned with their "
            "tracked changes. Leave unset to use the M3 default fixture."
        ),
    )
    original_path: str | None = Field(
        default=None,
        description=(
            "Path to the clean original .docx (pre-counterparty) for "
            "cross-reference by the planner. Leave unset to use the M3 "
            "default fixture."
        ),
    )
    output_path: str | None = Field(
        default=None,
        description=(
            "Path to write the redlined .docx. Leave unset to use the M3 "
            "default fixture path."
        ),
    )


class RedlineToolOutput(BaseModel):
    """Structured output the orchestrator paraphrases into a final reply."""

    output_path: str
    elapsed_seconds: float
    decisions_total: int
    decisions_accepted: int
    decisions_countered: int
    decisions_commented: int
    summary: str


_TOOL_DESCRIPTION = (
    "Run a counterparty-response redline on an NDA the partner has "
    "briefed Oscar on. Reads the counterparty's tracked-changed .docx, "
    "decides per-change whether to accept, counter-propose, comment, or "
    "no-action against the brief, and writes a redlined .docx with two-"
    "author tracked changes and partner-quality comments. The pipeline "
    "takes 55 to 128 seconds end-to-end against GPT-5.5 plus MiniMax. "
    "Returns a structured summary the orchestrator can paraphrase into a "
    "final user-facing message."
)


def build_redline_tool(
    *,
    default_input_path: Path,
    default_original_path: Path,
    default_output_path: Path,
    progress_callback: Callable[[str], Awaitable[None]] | None = None,
) -> BaseTool:
    """Construct the ``redline_nda`` StructuredTool.

    The factory captures the three default paths and the progress
    callback in closure. The tool's body resolves any None field on the
    input by substituting the corresponding default, then awaits
    :func:`run_redline`.

    Args:
        default_input_path: Substituted when the input does not supply
            ``input_path``.
        default_original_path: Substituted when the input does not
            supply ``original_path``.
        default_output_path: Substituted when the input does not supply
            ``output_path``.
        progress_callback: Optional async callable invoked at five well-
            defined milestones during the pipeline run. The dispatcher
            binds this per-invocation to a Slack-thread-scoped poster.
    """

    async def _redline_nda(
        brief: str,
        input_path: str | None = None,
        original_path: str | None = None,
        output_path: str | None = None,
    ) -> RedlineToolOutput:
        in_path = Path(input_path) if input_path else default_input_path
        orig_path = Path(original_path) if original_path else default_original_path
        out_path = Path(output_path) if output_path else default_output_path

        result = await run_redline(
            input_path=in_path,
            output_path=out_path,
            original_path=orig_path,
            brief=brief,
            progress_callback=progress_callback,
        )

        plural = "s" if result.decisions_total != 1 else ""
        breakdown = (
            f"{result.decisions_accepted} accepted, "
            f"{result.decisions_countered} counter-proposed, "
            f"{result.decisions_commented} commented"
        )
        summary = (
            f"Reviewed {result.decisions_total} tracked change{plural} "
            f"in {result.elapsed_seconds:.1f} seconds ({breakdown}). "
            f"Output written to {result.output_path}."
        )

        return RedlineToolOutput(
            output_path=str(result.output_path),
            elapsed_seconds=result.elapsed_seconds,
            decisions_total=result.decisions_total,
            decisions_accepted=result.decisions_accepted,
            decisions_countered=result.decisions_countered,
            decisions_commented=result.decisions_commented,
            summary=summary,
        )

    return StructuredTool.from_function(
        coroutine=_redline_nda,
        name="redline_nda",
        description=_TOOL_DESCRIPTION,
        args_schema=RedlineToolInput,
    )
