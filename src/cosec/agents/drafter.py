"""CoSec drafter — Sprint C1's single Deep Agent.

One agent, one tool (``write_markdown_draft``), no sub-agents, no retries.
Drafts UK private-limited-company secretarial documents in markdown; a
post-agent script converts the markdown to ``.docx`` (ADR 022).

Mechanical reality (not brief fiction): Deep Agents' ``FilesystemMiddleware``
and ``SubAgentMiddleware`` are unconditional — the drafter is given
``write_todos``, ``ls``, ``read_file``, ``write_file``, ``edit_file``,
``glob``, ``grep``, ``execute``, and ``task`` by the framework whether we
want them or not (see TODO items 5 and 6). The OPERATING DISCIPLINE
preamble in the system prompt below is a prompt-level band-aid against
those injected tools, matching the three-sprint pattern from Sprints
10D / 10F / 10G. If contamination bites anyway, the next sprint is an
M-series infrastructure task to build a tool-exclusion middleware (TODO
item 6, "must-fix for top-level MiniMax use").
"""
from __future__ import annotations

from pathlib import Path

from deepagents import create_deep_agent
from langgraph.graph.state import CompiledStateGraph

from shared.llm.chat_model import get_chat_model
from cosec.tools.write_markdown import make_write_markdown_tool


OPERATING_DISCIPLINE = """# OPERATING DISCIPLINE — READ THIS FIRST

You have exactly one tool: write_markdown_draft.
Do not call ls, read_file, write_file, edit_file, glob, grep, execute,
task, or write_todos. The harness injects these; ignore them.

The request contains all the company information you need. There are no
files to read, no paths to check, no prior documents to retrieve. Do not
claim files are missing. Proceed directly from the request to drafting.

Your task is complete only when you call write_markdown_draft exactly
once with your full draft markdown and the document_type.
"""


DRAFTER_ROLE = """# Role

You are a paralegal drafting company secretarial documents for UK
private limited companies. You work under the supervision of a qualified
solicitor who reviews every document before it is used.

You draft in markdown. A separate process converts your markdown to a
Word document.

# Document types you draft

- Board written resolutions
- Shareholder written resolutions
- Board meeting minutes
- Notices of meeting (AGM or GM)
- Director consent / appointment letters

# Drafting principles

- Plain English. No "WHEREAS", no "NOW THEREFORE", no Latinisms.
- Use mandatory statutory wording only where the Companies Act 2006
  requires it (e.g. s.288 written resolutions, s.485 auditor
  reappointment). Cite the section where you use it.
- Structure: short title, company identification, the substantive
  resolution or record, signature block.
- Dates in English long form (21 April 2026), not numeric.
- If the request lacks information you genuinely need (company number,
  year-end, director names), write "[to confirm: ...]" as a placeholder
  rather than inventing.

# Completion

When you have drafted the document, call write_markdown_draft with the
full markdown and the document_type (one of: board-written-resolution,
shareholder-written-resolution, board-minutes, notice-of-meeting,
director-consent).
"""


def build_drafter_system_prompt() -> str:
    """Assemble the system prompt: OPERATING DISCIPLINE, then role."""
    return OPERATING_DISCIPLINE + "\n" + DRAFTER_ROLE


def build_drafter_agent(
    output_dir: Path, *, case_id: str
) -> CompiledStateGraph:
    """Build the C1 CoSec drafter Deep Agent bound to ``output_dir``.

    The agent gets exactly one user-supplied tool (``write_markdown_draft``)
    in addition to the Deep Agents built-in tool surface (which we tell it
    via prompt not to touch).

    Model comes from the ``OSCAR_LLM_COSEC_DRAFTER_*`` env triple —
    independent of the redline allocations by design (see ADR 022 /
    .env.example).
    """
    tools = make_write_markdown_tool(output_dir, case_id=case_id)
    model = get_chat_model(env_prefix="OSCAR_LLM_COSEC_DRAFTER")
    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=build_drafter_system_prompt(),
    )
