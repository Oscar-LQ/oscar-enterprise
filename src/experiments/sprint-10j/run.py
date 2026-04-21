"""Sprint 10J — run the three-stage deterministic decomposition pipeline.

Invokes ``pipeline.stage1_draft`` → ``pipeline.stage2_diff`` →
``pipeline.stage3_apply`` in sequence, writes all artefacts, runs
``verify_output`` plus 10J-specific lawyer-shape checks. Single attempt,
mechanical debugging only per the brief.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import zipfile
from collections import Counter
from io import BytesIO
from pathlib import Path

# Load .env so the OSCAR_LLM_REDLINE_EXECUTOR_* triple is available without
# requiring the caller to pre-source the env. Matches the python-dotenv pin
# in oscar-enterprise/requirements.txt.
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

# Silence Adeu's structlog stream before any adeu import — pattern from
# sprint-10e/run.py:54-77, copied verbatim.
import structlog

logging.basicConfig(level=logging.WARNING)
for _name in (
    "adeu",
    "adeu.redline.engine",
    "adeu.redline.mapper",
    "adeu.redline.comments",
    "adeu.ingest",
    "adeu.markup",
    "adeu.utils.docx",
):
    logging.getLogger(_name).setLevel(logging.WARNING)
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(colors=False),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from adeu import extract_text_from_stream  # noqa: E402

import pipeline as pipeline_mod  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
INPUT_DOCX = HERE / "nda-input.docx"
OUTPUT_DOCX = HERE / "nda-output.docx"
TRANSCRIPT = HERE / "transcript.txt"
DRAFT_OUTPUT = HERE / "draft-output.json"
DIFF_OUTPUT = HERE / "diff-output.jsonl"
TOOL_CALL_LOG = HERE / "tool-calls.jsonl"


# ---------------------------------------------------------------------------
# verify_output — copied verbatim from sprint-10e/run.py:575-717
# ---------------------------------------------------------------------------

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": W_NS}


def _element_text(el) -> str:
    texts = el.xpath(".//w:t/text() | .//w:delText/text()", namespaces=_NS)
    return "".join(texts)


def _element_word_count(el) -> int:
    text = _element_text(el).strip()
    return len(text.split()) if text else 0


def verify_output(output_path: Path) -> tuple[bool, list[str]]:
    """Three mechanical checks + four Sprint 10E lawyer-shape warnings.

    Copied verbatim from sprint-10e/run.py. The ``ok`` return reflects only
    the three mechanical checks from 10D (file exists, valid zip, parseable
    document.xml). The four warnings are diagnostic: they append to
    ``notes`` with a ``WARN:`` prefix and never flip ``ok`` to False.
    """
    notes: list[str] = []

    if not output_path.exists():
        return False, [f"output file does not exist: {output_path}"]
    notes.append(f"exists: {output_path} ({output_path.stat().st_size} bytes)")

    try:
        with zipfile.ZipFile(output_path) as zf:
            names = zf.namelist()
            if "word/document.xml" not in names:
                return False, notes + ["word/document.xml not in zip"]
            doc_xml = zf.read("word/document.xml")
    except zipfile.BadZipFile:
        return False, notes + ["not a valid zip file"]
    notes.append(f"valid zip with {len(names)} parts")

    from lxml import etree

    try:
        root = etree.fromstring(doc_xml)
    except etree.XMLSyntaxError as exc:
        return False, notes + [f"XML parse failed: {exc}"]
    notes.append(f"parsed OK (root tag: {etree.QName(root.tag).localname})")

    ins_elements = root.findall(".//w:ins", _NS)
    del_elements = root.findall(".//w:del", _NS)
    notes.append(
        f"tracked changes: w:ins={len(ins_elements)}, w:del={len(del_elements)}"
    )

    # (1) Span widths.
    for el in ins_elements + del_elements:
        tag = etree.QName(el.tag).localname
        wid = el.get(f"{{{W_NS}}}id", "?")
        wc = _element_word_count(el)
        if wc > 50:
            notes.append(
                f"WARN: w:{tag}[id={wid}] span={wc} words — >50, "
                f"almost certainly over-broad (lawyer-shape fail)"
            )
        elif wc > 20:
            notes.append(
                f"WARN: w:{tag}[id={wid}] span={wc} words — >20, "
                f"suspicious (review against criteria)"
            )

    # (2) Empty-delText nested-delete signature.
    for d in del_elements:
        empty_dts = [
            dt
            for dt in d.findall(".//w:delText", _NS)
            if (dt.text is None or dt.text == "")
        ]
        has_ancestor_del = False
        parent = d.getparent()
        while parent is not None:
            if etree.QName(parent.tag).localname == "del":
                has_ancestor_del = True
                break
            parent = parent.getparent()
        if empty_dts and has_ancestor_del:
            wid = d.get(f"{{{W_NS}}}id", "?")
            notes.append(
                f"WARN: w:del[id={wid}] is a nested w:del with empty "
                f"w:delText — original text not preserved in audit trail "
                f"(matches Sprint 10D nested-delete failure)"
            )

    # (3) Duplicate w:ins content (>10 words, ≥2 copies).
    counter: Counter[str] = Counter()
    for i_el in ins_elements:
        content = _element_text(i_el).strip()
        if len(content.split()) > 10:
            counter[content] += 1
    for content, count in counter.items():
        if count >= 2:
            wc = len(content.split())
            notes.append(
                f"WARN: {count} w:ins elements share identical {wc}-word "
                f"content — duplicate insertion (matches Sprint 10D "
                f"duplicate-ins failure). Content starts: "
                f"{content[:80]!r}"
            )

    # (4) Litigation-text preservation spot-check.
    all_del_text = "".join(root.xpath(".//w:delText/text()", namespaces=_NS))
    needle = "exclusive jurisdiction of the courts of England and Wales"
    if needle in all_del_text:
        notes.append(
            f"SPOT-CHECK OK: litigation phrase {needle!r} is preserved "
            f"in w:delText (original text is in the audit trail)."
        )
    else:
        notes.append(
            f"WARN: litigation phrase {needle!r} NOT found in any "
            f"w:delText — the original text may not be preserved in the "
            f"audit trail (matches Sprint 10D broken-audit-trail failure)."
        )

    return True, notes


# ---------------------------------------------------------------------------
# 10J-specific checks
# ---------------------------------------------------------------------------


def run_10j_specific_checks(
    output_path: Path,
    edits_count: int,
) -> list[str]:
    """Check edit count + clause-9 element presence + governing-law preservation.

    Returns a list of diagnostic notes (WARN / FOUND / MISSING prefixes).
    Non-mechanical — these feed the outcome classification, not a boolean gate.
    """
    notes: list[str] = []

    # Edit-count shape.
    if 2 <= edits_count <= 5:
        notes.append(
            f"10J-shape OK: {edits_count} ModifyText edits (target 2-5 narrow edits)."
        )
    elif edits_count < 2:
        notes.append(
            f"10J-shape WARN: only {edits_count} edit(s); target 2-5 narrow "
            f"edits. Bundling risk."
        )
    else:
        notes.append(
            f"10J-shape WARN: {edits_count} edits; target 2-5 narrow edits. "
            f"Over-split risk (word-level granularity may be too fine)."
        )

    # Clean-view §9 read-back + five-element check.
    with open(output_path, "rb") as f:
        clean = extract_text_from_stream(
            BytesIO(f.read()), filename=output_path.name, clean_view=True
        )

    # Extract just §9's body for the element check.
    m_start = clean.find("9. Governing Law and Dispute Resolution")
    m_end = clean.find("10. General")
    clause9_clean = clean[m_start:m_end] if (m_start >= 0 and m_end > m_start) else ""

    element_checks = {
        "seat London": any(p in clause9_clean for p in ("seat of arbitration shall be London", "seat in London", "seat shall be London", "London shall be the seat")),
        "LCIA Rules": any(p in clause9_clean for p in ("LCIA Rules", "Rules of the LCIA", "LCIA arbitration rules")),
        "sole arbitrator": any(p in clause9_clean for p in ("sole arbitrator", "one arbitrator", "single arbitrator")),
        "English language": any(p in clause9_clean for p in ("language shall be English", "English shall be the language", "conducted in English", "in the English language")),
        "final and binding": "final and binding" in clause9_clean,
    }
    for element, found in element_checks.items():
        notes.append(
            f"ELEMENT {'FOUND' if found else 'MISSING'}: {element!r} in clean-view §9"
        )

    # Governing-law sentence preservation.
    govlaw_phrase = "governed by and construed in accordance with the laws of England and Wales"
    if govlaw_phrase in clause9_clean:
        notes.append(f"GOV-LAW OK: {govlaw_phrase!r} intact in clean-view §9.")
    else:
        notes.append(
            f"GOV-LAW WARN: {govlaw_phrase!r} NOT found in clean-view §9 — "
            f"the governing-law sentence may have been altered."
        )

    # Store the clean-view §9 for the transcript.
    notes.append("CLEAN-VIEW §9:")
    notes.append(clause9_clean.strip() if clause9_clean else "(clause 9 not extractable from clean view)")

    return notes


# ---------------------------------------------------------------------------
# Artefact writers
# ---------------------------------------------------------------------------


def _echo_env() -> None:
    """Print the OSCAR_LLM_REDLINE_EXECUTOR triple's provider+model.

    10J runs only the executor triple (no GC, no HOC, no planner). API key
    redacted — length only, so misconfig is visible without leaking the secret.
    """
    for name in (
        "OSCAR_LLM_REDLINE_EXECUTOR_PROVIDER",
        "OSCAR_LLM_REDLINE_EXECUTOR_MODEL",
    ):
        print(f"{name:45s} = {os.environ.get(name)!r}")
    api_key = os.environ.get("OSCAR_LLM_REDLINE_EXECUTOR_API_KEY", "")
    key_repr = f"<len={len(api_key)}>" if api_key else "<unset>"
    print(f"{'OSCAR_LLM_REDLINE_EXECUTOR_API_KEY':45s} = {key_repr}")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    _echo_env()
    print()

    # Regenerate the input .docx every run — deterministic, python-sourced.
    if not INPUT_DOCX.exists():
        from build_input import build_document

        build_document(INPUT_DOCX)
        print(f"regenerated {INPUT_DOCX}")

    transcript_lines: list[str] = []

    def log(line: str = "") -> None:
        transcript_lines.append(line)
        print(line)

    log("=" * 72)
    log("Sprint 10J — deterministic edit decomposition pipeline")
    log("=" * 72)
    log("")
    log(f"input:  {INPUT_DOCX}")
    log(f"output: {OUTPUT_DOCX}")
    log("")

    log("-" * 72)
    log("STAGE 1 — Draft (MiniMax chat call)")
    log("-" * 72)
    log("")
    log("SYSTEM PROMPT (verbatim):")
    log(pipeline_mod.SYSTEM_PROMPT)
    log("")
    log("HUMAN MESSAGE (verbatim §9 text):")
    log(pipeline_mod.CURRENT_CLAUSE_9)
    log("")

    try:
        draft = pipeline_mod.stage1_draft()
    except Exception as exc:
        log(f"STAGE 1 ERROR: {exc}")
        DRAFT_OUTPUT.write_text(json.dumps({"error": str(exc)}, indent=2))
        TRANSCRIPT.write_text("\n".join(transcript_lines))
        return 1

    DRAFT_OUTPUT.write_text(json.dumps(draft.to_json(), indent=2, ensure_ascii=False))
    log(f"wrote {DRAFT_OUTPUT}")
    log("")
    log("RAW LLM RESPONSE (verbatim):")
    log(draft.raw_response)
    log("")
    log(f"echo matches prompt verbatim: {draft.echo_matches_prompt}")
    if not draft.echo_matches_prompt:
        log(f"echo diff: {draft.echo_diff_note}")
    log("")
    log("PARSED replacement_text (before Unicode normalisation):")
    log(draft.parsed_replacement_text)
    log("")
    log("NORMALISED replacement_text (fed into Stage 2):")
    log(draft.normalised_replacement_text)
    log("")

    log("-" * 72)
    log("STAGE 2 — Word-diff + block-group (pure Python)")
    log("-" * 72)
    log("")

    try:
        edits = pipeline_mod.stage2_diff(
            pipeline_mod.CURRENT_CLAUSE_9,
            draft.normalised_replacement_text,
            INPUT_DOCX,
        )
    except Exception as exc:
        log(f"STAGE 2 ERROR: {exc}")
        TRANSCRIPT.write_text("\n".join(transcript_lines))
        return 1

    _write_jsonl(DIFF_OUTPUT, [e.to_jsonl() for e in edits])
    log(f"wrote {DIFF_OUTPUT}")
    log(f"edit count: {len(edits)}")
    log("")
    for i, e in enumerate(edits):
        log(f"  Edit {i + 1}: {e.kind}")
        log(f"    target_text ({len(e.target_text.split())} words): {e.target_text!r}")
        log(f"    new_text    ({len(e.new_text.split())} words): {e.new_text!r}")
        if e.kind == "pure_insert":
            log(f"    anchor_tokens: {e.anchor_tokens}")
        if e.left_context or e.right_context:
            log(f"    widened: left={e.left_context} right={e.right_context} content tokens")
        log("")

    log("-" * 72)
    log("STAGE 3 — Apply (Adeu RedlineEngine.process_batch)")
    log("-" * 72)
    log("")

    # Pre-call intent log.
    intent_records = [
        {"phase": "pre_call", "edit_index": i, **e.to_jsonl()}
        for i, e in enumerate(edits)
    ]
    _write_jsonl(TOOL_CALL_LOG, intent_records)
    log(f"wrote pre-call intent to {TOOL_CALL_LOG}")

    apply_result = pipeline_mod.stage3_apply(edits, INPUT_DOCX)

    # Post-call result log (append).
    with open(TOOL_CALL_LOG, "a") as f:
        f.write(json.dumps({
            "phase": "post_call",
            "validation_errors": apply_result.validation_errors,
            "process_result": apply_result.process_result,
            "output_bytes_len": len(apply_result.output_bytes),
        }) + "\n")

    if apply_result.validation_errors:
        log("STAGE 3 VALIDATION ERRORS:")
        for err in apply_result.validation_errors:
            log(f"  {err}")
        log("")
        log("Document not written; Stage 3 aborted at validate_edits.")
        TRANSCRIPT.write_text("\n".join(transcript_lines))
        return 1

    OUTPUT_DOCX.write_bytes(apply_result.output_bytes)
    log(f"wrote {OUTPUT_DOCX} ({len(apply_result.output_bytes)} bytes)")
    log(f"process_batch result: {apply_result.process_result}")
    log("")

    log("-" * 72)
    log("VERIFICATION")
    log("-" * 72)
    log("")

    ok, notes = verify_output(OUTPUT_DOCX)
    log(f"verify_output ok={ok}")
    for note in notes:
        log(f"  {note}")
    log("")

    ten_j_notes = run_10j_specific_checks(OUTPUT_DOCX, edits_count=len(edits))
    for note in ten_j_notes:
        log(note)
    log("")

    TRANSCRIPT.write_text("\n".join(transcript_lines))
    print(f"\nwrote transcript to {TRANSCRIPT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
