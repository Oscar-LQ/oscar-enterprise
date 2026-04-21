"""Sprint 10K — entry point for the CPM first-pass port.

Single-attempt pipeline per the approved plan. Ensures the NDA input
exists, runs the pipeline once, writes the transcript, prints a
summary. Never retries.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make this directory importable so `from build_input import ...` resolves
# inside pipeline.py.
sys.path.insert(0, str(Path(__file__).parent))

from pipeline import (  # noqa: E402
    INPUT_DOCX,
    OUTPUT_DOCX,
    TRANSCRIPT,
    _echo_env,
    run_pipeline,
    write_transcript,
)


def main() -> None:
    _echo_env()
    print()

    if not INPUT_DOCX.exists():
        from build_input import build_document

        build_document()
        print(f"generated {INPUT_DOCX}")
    else:
        print(f"using existing {INPUT_DOCX}")

    print()
    print("=" * 72)
    print("INVOKING CPM-PORT PIPELINE (single attempt)")
    print("=" * 72)

    try:
        artefacts = run_pipeline()
    except ValueError as exc:
        # Malformed JSON — Outcome C with diagnosis.
        print(f"\nFATAL: {exc}")
        print("\nRaw LLM output preserved at: src/redline/experiments/sprint-10k/llm-output.txt")
        print("This is Outcome C (malformed output). See sprint log for analysis.")
        raise SystemExit(1) from exc

    # Summaries.
    print(f"\nparsed edits: {len(artefacts.parsed_edits)}")
    for i, e in enumerate(artefacts.parsed_edits, 1):
        tt = e.get("target_text", "")
        nt = e.get("new_text", "")
        print(f"  edit {i}: target={len(tt.split())}w new={len(nt.split())}w")

    print(f"\nadeu apply: applied={artefacts.apply_result.applied} skipped={artefacts.apply_result.skipped}")
    if artefacts.apply_result.validation_errors:
        print("VALIDATION ERRORS:")
        for err in artefacts.apply_result.validation_errors:
            print(f"  - {err}")

    print("\n--- MECHANICAL VERIFICATION ---")
    for n in artefacts.verify_notes:
        print(f"  {n}")

    print("\n--- CLEAN-VIEW §9 READ-BACK ---")
    for line in artefacts.clean_view_excerpt.splitlines():
        print(f"  {line}")

    write_transcript(artefacts)
    print(f"\ntranscript written to {TRANSCRIPT}")

    if not artefacts.verify_ok:
        print("\nMechanical verification: FAILED (file missing or corrupt).")
        raise SystemExit(2)

    # Lawyer-shape outcome classification is in the sprint log, not here —
    # the transcript + WARN lines tell the story.
    print(f"\nOutput for human review: {OUTPUT_DOCX}")


if __name__ == "__main__":
    main()
