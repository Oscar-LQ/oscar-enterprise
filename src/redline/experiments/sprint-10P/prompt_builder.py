"""Sprint 10P — prompt assembly for the counterparty-response pipeline.

Two prompt types:

- Planner: system prompt from planner_prompt.txt; user message =
  Acme's brief + state-of-play JSON + original NDA clean text.

- Executor: system prompt from executor_prompt.txt; user message
  built per counter-propose decision from the planner's instruction +
  Zenith's marked text + paragraph context + preserve list.

Acme's verbatim brief lives in user_prompt.txt (one file; brief portion
only — no schema directives, the planner prompt carries those).
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


def _serialise_state_of_play(state) -> str:
    """Serialise StateOfPlay to JSON for the planner prompt.

    Uses the lib's TrackedChangeEntry / StateOfPlay Pydantic models'
    `model_dump_json` for shape stability. Only the planner-relevant
    fields are surfaced (paragraph_context, changed_text, ooxml_id are
    all included; replies array is included if non-empty).
    """
    return state.model_dump_json(indent=2)


def build_planner_user_prompt(
    state,
    original_nda_clean_text: str,
    *,
    solicitor_brief: str | None = None,
) -> str:
    """Assemble the planner's user message.

    Order:
      1. Acme's brief (the partner's tactical instructions)
      2. State-of-play JSON (Zenith's tracked changes, structured)
      3. Original NDA clean text (Acme's round-1 draft, for cross-reference)

    If ``solicitor_brief`` is None, the brief is loaded from
    ``user_prompt.txt`` (preserves ``run_once`` behaviour). When supplied,
    the caller's string substitutes for the file content. The supplied
    string is normalised to end with exactly one newline so the assembled
    prompt's section spacing is stable.
    """
    if solicitor_brief is None:
        brief = _solicitor_brief()
    else:
        brief = solicitor_brief.rstrip("\n") + "\n"
    state_json = _serialise_state_of_play(state)

    return (
        f"PARTNER'S BRIEF:\n\n"
        f"{brief}"
        "\n---\n\n"
        f"STATE OF PLAY (Zenith's tracked changes on the NDA you previously sent):\n\n"
        f"{state_json}\n"
        "\n---\n\n"
        f"ORIGINAL NDA (clean text, pre-Zenith — what Acme drafted in round 1):\n\n"
        f"{original_nda_clean_text}\n"
    )


def build_executor_user_prompt(
    decision: dict[str, Any],
    state_entry: dict[str, Any],
) -> str:
    """Assemble the executor's user message for one counter-propose decision.

    `decision` is the planner's NegotiationDecision (action="counter_propose").
    `state_entry` is the matching TrackedChangeEntry as a dict (looked up by
    change_id from the state-of-play).
    """
    cid = decision.get("change_id", "?")
    position = decision.get("position", "") or ""
    instruction = decision.get("instruction", "") or ""
    preserve = decision.get("preserve") or []
    comment_for_partner = decision.get("comment_text", "") or ""

    change_type = state_entry.get("change_type", "?")
    target_text = state_entry.get("changed_text", "")
    paragraph_context = state_entry.get("paragraph_context", "")

    if preserve:
        preserve_block = "\n".join(f'  - "{p}"' for p in preserve)
    else:
        preserve_block = "  (No preservation requirements for this counter-proposal.)"

    if comment_for_partner.strip():
        comment_block = comment_for_partner.strip()
    else:
        comment_block = "(none)"

    return (
        f"Counter-proposal for {cid}:\n"
        f"  change_type: {change_type}\n"
        f"  target_text (Zenith's marked text, verbatim):\n"
        f"  >>>\n"
        f"{target_text}\n"
        f"  <<<\n"
        f"\n"
        f"  paragraph_context (the accepted-all view of the paragraph for surrounding context):\n"
        f"  >>>\n"
        f"{paragraph_context}\n"
        f"  <<<\n"
        f"\n"
        f"Senior's tactical position:\n"
        f"  {position}\n"
        f"\n"
        f"Senior's drafting instruction:\n"
        f"  {instruction}\n"
        f"\n"
        f"Phrases that MUST remain present verbatim in your new_text (preserve list):\n"
        f"{preserve_block}\n"
        f"\n"
        f"Optional partner comment (use as part of the `comment` field if helpful):\n"
        f"  {comment_block}\n"
        f"\n"
        f"---\n"
        f"\n"
        f"Return one JSON object with `new_text` and `comment` per the schema in your system instructions."
    )
