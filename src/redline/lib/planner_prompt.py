"""Planner prompt assembly for first-pass playbook-driven redlining.

Phase 1.3 of Sprint 10Q. Implements the planner-side of the loader-prompt
contract documented in docs/redline/research/sprint-10Q-phase-1-3-design.md
§6: a four-layer context shape (playbook, direction, state_of_play, memory)
where the loader's output is inserted verbatim into the playbook layer's
named section, and the other three layers exist as named placeholders for
subsequent-pass infrastructure (Sprint 10R+).

The decision schema documented in §3-§4 of the design note is the planner's
output contract. Each emitted decision has eight fields; the
divergence_from_playbook and divergence_comment_text fields are present
structurally and remain false / empty on first-pass.

Coupling note: this module knows nothing about the loader's path resolution
or .docx parsing; it consumes the loader's output as a string. Either side
can change internally without disturbing the other (design note §6).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

HERE = Path(__file__).parent

PLANNER_PROMPT_FIRST_PASS_FILE = HERE / "planner_prompt_first_pass.txt"

DecisionAction = Literal["comment_only", "counter_propose", "no_action"]


@dataclass
class PlannerDecision:
    """One planner decision per design-note §3-§4.

    Eight fields. divergence_from_playbook and divergence_comment_text are
    structural-only on first-pass — the dispatcher renders nothing for them
    on first-pass per design-note §5.
    """

    clause_reference: str
    playbook_position: str
    playbook_consultation: str
    action: DecisionAction
    comment_text: str = ""
    intent: str = ""
    divergence_from_playbook: bool = False
    divergence_comment_text: str = ""


def load_first_pass_instructions() -> str:
    """Load the first-pass planner instruction text (verbatim from .txt)."""
    return PLANNER_PROMPT_FIRST_PASS_FILE.read_text(encoding="utf-8")


def build_planner_system_prompt(
    *,
    playbook: str = "",
    direction: str = "",
    state_of_play: str = "",
    memory: str = "",
    instructions: str | None = None,
) -> str:
    """Assemble the planner system prompt with the four named context layers.

    Each layer renders as a named XML-style section so the planner reads
    them as discrete contextual inputs even when empty. On first-pass
    (Sprint 10Q Phase 2), only `playbook` is populated; the other three
    are empty placeholders that subsequent-pass infrastructure (Sprint
    10R+) will populate.

    Args:
        playbook: Loader output per design-note §6 — markdown-rendered
            playbook content. Inserted verbatim. Empty string is a valid
            input (graceful degradation when no playbook is configured).
        direction: Partner / in-house lawyer's tactical brief. Empty in
            10Q Phase 2.
        state_of_play: Structured extraction of pending tracked changes
            from a prior pass. Empty on first-pass.
        memory: Slack-derived addenda or accumulated decisions. Empty
            in 10Q Phase 2.
        instructions: Optional override for the instruction-text block.
            Defaults to the first-pass instructions loaded from the
            companion .txt. Subsequent-pass sprints can pass a different
            instructions block while reusing the layer-assembly machinery.

    Returns:
        Full system prompt: instructions block, then the four context-layer
        sections in the canonical order playbook → direction →
        state_of_play → memory.
    """
    body = instructions if instructions is not None else load_first_pass_instructions()
    return (
        f"{body.rstrip()}\n\n"
        f"<playbook>\n{playbook.rstrip()}\n</playbook>\n\n"
        f"<direction>\n{direction.rstrip()}\n</direction>\n\n"
        f"<state_of_play>\n{state_of_play.rstrip()}\n</state_of_play>\n\n"
        f"<memory>\n{memory.rstrip()}\n</memory>\n"
    )


def build_planner_user_prompt(msa_text: str) -> str:
    """Assemble the planner user prompt: the MSA text in document order.

    Section markers (Section 1, Section 2(a), etc.) are preserved as
    drafted upstream — this assembler does no restructuring. The planner
    reads the document as the parties drafted it.
    """
    return f"MSA TEXT (document order; structural markers preserved):\n\n{msa_text}\n"
