"""Sprint 10O — prompt assembly for the planner-executor head-to-head.

Two prompt types:
- Planner: system prompt from planner_prompt.txt; user message =
  solicitor's brief + NDA full text. Output is a structured plan.
- Executor: system prompt from executor_prompt.txt; user message
  built per-instruction from the planner's plan + NDA full text +
  preserve list.

The solicitor's brief lives verbatim in user_prompt.txt (10N copy,
brief portion only — no data contract note since the planner has its
own JSON schema directive).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent

PLANNER_PROMPT_FILE = HERE / "planner_prompt.txt"
EXECUTOR_PROMPT_FILE = HERE / "executor_prompt.txt"
USER_PROMPT_FILE = HERE / "user_prompt.txt"


def load_planner_system_prompt() -> str:
    return PLANNER_PROMPT_FILE.read_text(encoding="utf-8")


def load_executor_system_prompt() -> str:
    return EXECUTOR_PROMPT_FILE.read_text(encoding="utf-8")


def _solicitor_brief() -> str:
    return USER_PROMPT_FILE.read_text(encoding="utf-8").rstrip("\n") + "\n"


def build_planner_user_prompt(contract_text: str) -> str:
    """Assemble the planner's user message: solicitor brief + NDA.

    Order: brief first (instructions), then contract (the document
    being instructed about).
    """
    brief = _solicitor_brief()
    return (
        f"{brief}"
        "\n---\n\n"
        f"CONTRACT (NDA from counterparty):\n\n{contract_text}\n"
    )


def build_executor_user_prompt(plan_instruction: dict[str, Any], contract_text: str) -> str:
    """Assemble the executor's user message for one plan instruction.

    Includes the senior's instruction, preserve list, optional
    comment_for_partner, depends_on, and the full NDA for context
    (the executor needs to find and quote target_text from the
    document).
    """
    pid = plan_instruction.get("id", "?")
    clause = plan_instruction.get("clause", "?")
    position = plan_instruction.get("position", "")
    instruction = plan_instruction.get("instruction", "")
    preserve = plan_instruction.get("preserve", []) or []
    comment_for_partner = plan_instruction.get("comment_for_partner", "") or ""
    depends_on = plan_instruction.get("depends_on", []) or []

    if preserve:
        preserve_block = "\n".join(f'  - "{p}"' for p in preserve)
    else:
        preserve_block = "  (No preservation requirements for this edit.)"

    if comment_for_partner.strip():
        comment_block = comment_for_partner.strip()
    else:
        comment_block = "(none)"

    if depends_on:
        depends_block = ", ".join(depends_on)
    else:
        depends_block = "(none — apply against the original document)"

    return (
        "Senior's instruction:\n"
        f"  id: {pid}\n"
        f"  clause: {clause}\n"
        f"  position: {position}\n"
        f"  instruction: {instruction}\n"
        "\n"
        "Phrases that MUST remain present verbatim in your new_text (preserve list):\n"
        f"{preserve_block}\n"
        "\n"
        "Optional partner comment to attach to this edit (use as part of `comment` field if helpful):\n"
        f"  {comment_block}\n"
        "\n"
        f"Dependencies on other instructions: {depends_block}\n"
        "\n"
        "---\n"
        "\n"
        "CONTRACT (full text for context; focus your edit on the clause named above):\n"
        "\n"
        f"{contract_text}\n"
        "\n"
        "---\n"
        "\n"
        "Return one JSON object with target_text, new_text, comment per the schema in your system instructions."
    )
