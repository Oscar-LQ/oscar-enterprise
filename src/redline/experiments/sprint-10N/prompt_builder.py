"""Sprint 10N — prompt assembly for the real solicitor's brief test.

System prompt is loaded from a file (B1 = trimmed Vibe; B2 = short
solicitor; in Phase 3, system_prompt.txt = the chosen variant).

User message structure (from the 10N sprint brief):
  1. Solicitor's brief (verbatim, naturalistic instructions)
  2. The NDA contract text (from pipeline.prepare)
  3. Data contract note (JSON schema directive)

The solicitor's brief and data contract note are kept verbatim in
user_prompt.txt as a static reference. This module reads that file at
runtime, splits on the `---\\n\\n## Data contract note` marker, and
assembles the final user message with the contract injected between
the brief and the data contract note.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent
USER_PROMPT_FILE = HERE / "user_prompt.txt"

# Marker that splits the static user_prompt.txt into [brief, data_contract_note].
_SPLIT_MARKER = "---\n\n## Data contract note\n\n"


def load_system_prompt(variant: str) -> str:
    """Return the system prompt text for a variant ('B1', 'B2', or '' for chosen).

    Phase 1: variant='B1' loads system_prompt_B1.txt; variant='B2' loads
    system_prompt_B2.txt.
    Phase 3: variant='' loads system_prompt.txt (the chosen variant
    after Phase 2 approval, written there during Phase 3 setup).
    """
    if variant in ("B1", "B2"):
        path = HERE / f"system_prompt_{variant}.txt"
    elif variant == "":
        path = HERE / "system_prompt.txt"
    else:
        raise ValueError(f"unknown system prompt variant: {variant!r}")
    return path.read_text(encoding="utf-8")


def _split_brief_and_data_contract() -> tuple[str, str]:
    """Read user_prompt.txt and split into (solicitor_brief, data_contract_note).

    The data contract note starts with the H2 heading we use as a marker.
    The brief is everything before the marker; the note is everything after
    plus the marker itself (so the rendered prompt has the heading visible).
    """
    full = USER_PROMPT_FILE.read_text(encoding="utf-8")
    if _SPLIT_MARKER not in full:
        raise RuntimeError(
            f"split marker not found in {USER_PROMPT_FILE}: expected "
            f"'{_SPLIT_MARKER!r}'"
        )
    brief, _, data_note = full.partition(_SPLIT_MARKER)
    # Re-prepend the H2 heading so the rendered prompt has it.
    data_note_with_heading = "## Data contract note\n\n" + data_note
    return brief.rstrip("\n") + "\n", data_note_with_heading


def build_user_prompt(contract_text: str) -> str:
    """Assemble the runtime user message: brief → contract → data contract note.

    contract_text is the output of pipeline.prepare(docx_bytes,
    clean_view=False) — the NDA text plus doc_analyser's structural
    context header.
    """
    brief, data_note = _split_brief_and_data_contract()
    return (
        f"{brief}"
        "\n---\n\n"
        f"CONTRACT (NDA from counterparty):\n\n{contract_text}\n"
        "\n---\n\n"
        f"{data_note}"
    )
