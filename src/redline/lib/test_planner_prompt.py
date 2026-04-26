"""Unit tests for src/redline/lib/planner_prompt.

Covers the design-note §3-§4 decision schema (eight fields, three-action
enum, divergence defaults), the §6 four-layer system-prompt shape
(named sections present even when empty, playbook content inserted
verbatim, layer order canonical), graceful degradation on empty playbook,
and the user-prompt structure.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from src.redline.lib.planner_prompt import (
    PlannerDecision,
    build_planner_system_prompt,
    build_planner_user_prompt,
    load_first_pass_instructions,
)


# ---------------------------------------------------------------------------
# Decision schema (design-note §3-§4)
# ---------------------------------------------------------------------------


def test_decision_has_exactly_eight_fields() -> None:
    """Schema validation: PlannerDecision exposes the eight design-note fields."""
    expected = {
        "clause_reference",
        "playbook_position",
        "playbook_consultation",
        "action",
        "comment_text",
        "intent",
        "divergence_from_playbook",
        "divergence_comment_text",
    }
    actual = {f.name for f in fields(PlannerDecision)}
    assert actual == expected


def test_decision_field_types() -> None:
    """Schema validation: required fields are strings; divergence flag is bool."""
    type_map = {f.name: f.type for f in fields(PlannerDecision)}
    assert type_map["clause_reference"] == "str"
    assert type_map["playbook_position"] == "str"
    assert type_map["playbook_consultation"] == "str"
    assert type_map["comment_text"] == "str"
    assert type_map["intent"] == "str"
    assert type_map["divergence_from_playbook"] == "bool"
    assert type_map["divergence_comment_text"] == "str"


def test_decision_first_pass_defaults_match_design_note() -> None:
    """Divergence fields default to false / empty per §4."""
    decision = PlannerDecision(
        clause_reference="Section 5.2(b)",
        playbook_position="§5 Indemnity caps",
        playbook_consultation="Drafted clause uses rolling-12-month measure; playbook calls for contract-bounded.",
        action="counter_propose",
        comment_text="Replacing rolling-12-month measure with contract-bounded fees-paid cap.",
        intent="Replace with 'fees paid by the Customer under this Agreement'.",
    )
    assert decision.divergence_from_playbook is False
    assert decision.divergence_comment_text == ""


def test_decision_no_action_default_text_fields() -> None:
    """no_action decisions default comment_text and intent to empty string."""
    decision = PlannerDecision(
        clause_reference="Section 8.1",
        playbook_position="§3 SLA tiers",
        playbook_consultation="Drafted SLA matches playbook tiered-credit structure; no pushback.",
        action="no_action",
    )
    assert decision.comment_text == ""
    assert decision.intent == ""


# ---------------------------------------------------------------------------
# System prompt — four-layer shape (design-note §6)
# ---------------------------------------------------------------------------


def test_system_prompt_contains_all_four_layer_sections_even_when_empty() -> None:
    """All four named sections present in the canonical first-pass build."""
    prompt = build_planner_system_prompt()
    assert "<playbook>" in prompt and "</playbook>" in prompt
    assert "<direction>" in prompt and "</direction>" in prompt
    assert "<state_of_play>" in prompt and "</state_of_play>" in prompt
    assert "<memory>" in prompt and "</memory>" in prompt


def test_system_prompt_layer_order_is_canonical() -> None:
    """Layer order: playbook → direction → state_of_play → memory."""
    prompt = build_planner_system_prompt()
    pb = prompt.index("<playbook>")
    dr = prompt.index("<direction>")
    sop = prompt.index("<state_of_play>")
    mem = prompt.index("<memory>")
    assert pb < dr < sop < mem


def _extract_layer_section(prompt: str, name: str) -> str:
    """Return the content between the section's opening and closing tags.

    The instructions text mentions the layer tags inline (e.g. ``<playbook>``
    in backticks), so the section's opening tag is the LAST occurrence of
    ``<{name}>`` and the closing tag is the FIRST occurrence of
    ``</{name}>``.
    """
    open_tag = f"<{name}>"
    close_tag = f"</{name}>"
    start = prompt.rindex(open_tag) + len(open_tag)
    end = prompt.index(close_tag)
    assert start < end, f"layer {name!r} section malformed"
    return prompt[start:end]


def test_system_prompt_inserts_playbook_verbatim() -> None:
    """Loader output appears verbatim inside <playbook>...</playbook> per §6."""
    playbook = (
        "# Customer-Side Compute Capacity MSA Playbook\n"
        "## 1. Data residency\n"
        "Customer data must remain in named jurisdictions.\n\n"
    )
    prompt = build_planner_system_prompt(playbook=playbook)
    pb_section = _extract_layer_section(prompt, "playbook")
    assert "# Customer-Side Compute Capacity MSA Playbook" in pb_section
    assert "## 1. Data residency" in pb_section
    assert "Customer data must remain in named jurisdictions." in pb_section


def test_system_prompt_with_empty_playbook_still_builds() -> None:
    """Graceful degradation: empty playbook is a valid input (loader §6)."""
    prompt = build_planner_system_prompt(playbook="")
    # Build does not raise; sections are present
    assert "<playbook>" in prompt
    assert "</playbook>" in prompt
    pb_section = _extract_layer_section(prompt, "playbook")
    assert pb_section.strip() == ""


def test_system_prompt_includes_first_pass_instruction_text() -> None:
    """The instruction-text block from the .txt is in the assembled prompt."""
    prompt = build_planner_system_prompt()
    instructions = load_first_pass_instructions()
    # Spot-check a verbatim phrase from §1.3.5 that the .txt carries
    assert "Read the MSA clause-by-clause." in prompt
    assert "Read the MSA clause-by-clause." in instructions


def test_system_prompt_accepts_instruction_override() -> None:
    """Subsequent-pass sprints reuse layer-assembly with their own instructions."""
    custom = "CUSTOM INSTRUCTIONS BLOCK"
    prompt = build_planner_system_prompt(instructions=custom)
    assert custom in prompt
    # First-pass-specific text must not bleed in when instructions overridden
    assert "Read the MSA clause-by-clause." not in prompt


def test_system_prompt_populates_non_playbook_layers_when_provided() -> None:
    """Subsequent-pass infrastructure can populate direction/state/memory."""
    prompt = build_planner_system_prompt(
        direction="HOLD THE LINE on indemnity",
        state_of_play='{"changes": []}',
        memory="Prior partner Slack: customer prefers MFN clauses.",
    )
    assert "HOLD THE LINE on indemnity" in prompt
    assert '"changes": []' in prompt
    assert "customer prefers MFN clauses" in prompt


# ---------------------------------------------------------------------------
# User prompt — MSA in document order (§1.3.6)
# ---------------------------------------------------------------------------


def test_user_prompt_contains_msa_text() -> None:
    """User prompt renders the MSA text passed in."""
    msa = "Section 1. Definitions.\n\n'Affiliate' means..."
    prompt = build_planner_user_prompt(msa)
    assert msa in prompt


def test_user_prompt_preserves_structural_markers() -> None:
    """Section markers like Section 2(a) survive verbatim into the user prompt."""
    msa = "Section 2(a) Capacity Reservations.\nSection 2(b) Allocation."
    prompt = build_planner_user_prompt(msa)
    assert "Section 2(a) Capacity Reservations." in prompt
    assert "Section 2(b) Allocation." in prompt


# ---------------------------------------------------------------------------
# Verbatim-bound prompt content (CLAUDE.md "Verbatim where LLM-bound")
# ---------------------------------------------------------------------------


def test_first_pass_instructions_carry_verbatim_phrases() -> None:
    """Spec-mandated phrases from resume-prompt §1.3.5 present verbatim."""
    text = load_first_pass_instructions()
    # Three phrases from §1.3.5 of the Phase 1.3 spec
    assert "the playbook is the source of authority" in text
    assert "Emit one decision per clause warranting attention." in text
    assert "Decisions internally consistent" in text


def test_first_pass_instructions_describe_three_action_enum_no_accept() -> None:
    """No `accept` action on first-pass per §4."""
    text = load_first_pass_instructions()
    assert "comment_only" in text
    assert "counter_propose" in text
    assert "no_action" in text
    # `accept` must not appear as a documented action value
    assert "There is no `accept` action on first-pass" in text
