"""Sprint 10L — driver.

Loads Sprint 10K's ``parsed-edits.json`` + ``nda-input.docx`` (copied into
this directory at sprint start), feeds the edits through the ported CPM
mechanism (``post_processor.narrow_edits``), applies the narrowed list via
``RedlineEngine.process_batch``, runs Sprint 10E's ``verify_output``
lawyer-shape warnings on the result, and writes a transcript capturing every
boundary for inspection.

No LLM calls. One attempt. Mechanical fixes allowed (imports, paths, types);
no algorithmic tuning.
"""
from __future__ import annotations

import datetime
import io
import json
import logging
import os
import sys
import zipfile
from collections import Counter
from pathlib import Path

import structlog

# Silence Adeu's structlog stream before any adeu import (pattern from 10C).
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

sys.path.insert(0, str(Path(__file__).parent))

from adeu import RedlineEngine, extract_text_from_stream
from adeu.redline.engine import BatchValidationError

from post_processor import NarrowedEdit, narrow_edits


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
INPUT_DOCX = HERE / "nda-input.docx"
PARSED_EDITS_JSON = HERE / "parsed-edits.json"
NARROWED_EDITS_JSONL = HERE / "narrowed-edits.jsonl"
OUTPUT_DOCX = HERE / "nda-output.docx"
TRANSCRIPT = HERE / "transcript.txt"

AUTHOR = "Oscar"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": W_NS}


# ---------------------------------------------------------------------------
# verify_output — copied verbatim from Sprint 10E (same four lawyer-shape
# warnings operationalised in 10E and reused in 10F-10K). Copy-inline rather
# than import because 10E's run.py pulls Deep Agents and its own agent
# scaffolding, which Sprint 10L does not need.
# ---------------------------------------------------------------------------


def _element_text(el) -> str:
    texts = el.xpath(".//w:t/text() | .//w:delText/text()", namespaces=_NS)
    return "".join(texts)


def _element_word_count(el) -> int:
    text = _element_text(el).strip()
    return len(text.split()) if text else 0


def verify_output(output_path: Path) -> tuple[bool, list[str]]:
    """Three mechanical checks + four Sprint 10E lawyer-shape warnings."""
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

    # (2) Empty-delText nested-delete.
    from lxml.etree import QName
    for d in del_elements:
        empty_dts = [
            dt for dt in d.findall(".//w:delText", _NS)
            if (dt.text is None or dt.text == "")
        ]
        has_ancestor_del = False
        parent = d.getparent()
        while parent is not None:
            if QName(parent.tag).localname == "del":
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
                f"content — duplicate insertion. Content starts: {content[:80]!r}"
            )

    # (4) Litigation-text preservation spot-check.
    all_del_text = "".join(
        root.xpath(".//w:delText/text()", namespaces=_NS)
    )
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
            f"audit trail."
        )

    return True, notes


# ---------------------------------------------------------------------------
# Clean-view §9 extraction — mirrors 10K's pipeline.py approach.
# ---------------------------------------------------------------------------


def extract_clean_view_section_9(output_path: Path) -> str:
    try:
        with open(output_path, "rb") as f:
            clean_view = extract_text_from_stream(
                io.BytesIO(f.read()), clean_view=True,
            )
        idx = clean_view.find("9. Governing Law")
        if idx != -1:
            return clean_view[idx : idx + 1200]
        idx = clean_view.find("England and Wales")
        if idx != -1:
            return clean_view[max(0, idx - 200) : idx + 1000]
        return clean_view[:1500]
    except Exception as exc:
        return f"<clean-view extraction failed: {exc}>"


# ---------------------------------------------------------------------------
# Transcript + main
# ---------------------------------------------------------------------------


def _word_count(s: str) -> int:
    return len(s.strip().split())


def _write_narrowed_edits_jsonl(narrowed: list[NarrowedEdit]) -> None:
    """One JSON object per narrowed edit, pre-Adeu application — for inspection."""
    with open(NARROWED_EDITS_JSONL, "w") as f:
        for ne in narrowed:
            f.write(json.dumps({
                "target_text": ne.target_text,
                "new_text": ne.new_text,
                "comment": ne.comment,
                "raw_target": ne.raw_target,
                "raw_new": ne.raw_new,
                "anchor_tokens_prepended": ne.anchor_tokens_prepended,
                "anchor_tokens_appended": ne.anchor_tokens_appended,
                "op_trace": [{"op": op, "text": text} for op, text in ne.op_trace],
            }) + "\n")


def main() -> None:
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if not PARSED_EDITS_JSON.exists():
        print(f"FATAL: parsed-edits.json missing at {PARSED_EDITS_JSON}")
        raise SystemExit(2)
    if not INPUT_DOCX.exists():
        print(f"FATAL: nda-input.docx missing at {INPUT_DOCX}")
        raise SystemExit(2)

    print(f"Sprint 10L — run — {ts}")
    print(f"inputs:  {PARSED_EDITS_JSON.name}, {INPUT_DOCX.name}")
    print()

    with open(PARSED_EDITS_JSON) as f:
        parsed_edits = json.load(f)

    with open(INPUT_DOCX, "rb") as f:
        nda_bytes = f.read()

    print(f"parsed edits: {len(parsed_edits)}")
    for i, e in enumerate(parsed_edits, 1):
        tt = e.get("target_text", "")
        nt = e.get("new_text") or ""
        print(
            f"  edit {i}: target={_word_count(tt)}w new={_word_count(nt)}w "
            f"comment={e.get('comment')!r}"
        )

    print()
    print("=" * 72)
    print("POST-PROCESSOR: ported CPM find_match_three_layer + diff_words")
    print("=" * 72)

    narrowed = narrow_edits(parsed_edits, nda_bytes)

    print(f"\nnarrowed edits: {len(narrowed)}")
    for i, ne in enumerate(narrowed, 1):
        print(
            f"  narrowed {i}: target={_word_count(ne.target_text)}w "
            f"new={_word_count(ne.new_text)}w "
            f"raw_target={_word_count(ne.raw_target)}w "
            f"raw_new={_word_count(ne.raw_new)}w "
            f"anchor_prepended={ne.anchor_tokens_prepended} "
            f"anchor_appended={ne.anchor_tokens_appended}"
        )

    _write_narrowed_edits_jsonl(narrowed)
    print(f"\nwrote {NARROWED_EDITS_JSONL.name}")

    print()
    print("=" * 72)
    print("APPLY: RedlineEngine.process_batch (single shot, no retries)")
    print("=" * 72)

    engine = RedlineEngine(io.BytesIO(nda_bytes), author=AUTHOR)
    modify_edits = [ne.to_modify_text() for ne in narrowed]

    apply_error: str | None = None
    applied = 0
    skipped = 0
    try:
        result = engine.process_batch(modify_edits)
        applied = int(result.get("edits_applied", 0))
        skipped = int(result.get("edits_skipped", 0))
        output_stream = engine.save_to_stream()
        with open(OUTPUT_DOCX, "wb") as f:
            f.write(output_stream.read())
        print(f"apply: edits_applied={applied} edits_skipped={skipped}")
    except BatchValidationError as exc:
        errs = getattr(exc, "errors", [str(exc)])
        apply_error = "\n".join(errs)
        print(f"apply: BatchValidationError\n{apply_error}")
    except Exception as exc:
        apply_error = f"{type(exc).__name__}: {exc}"
        print(f"apply: {apply_error}")

    verify_ok = False
    verify_notes: list[str] = []
    clean_view = ""
    if apply_error is None:
        verify_ok, verify_notes = verify_output(OUTPUT_DOCX)
        print("\n--- MECHANICAL VERIFICATION ---")
        for n in verify_notes:
            print(f"  {n}")

        clean_view = extract_clean_view_section_9(OUTPUT_DOCX)
        print("\n--- CLEAN-VIEW §9 READ-BACK ---")
        for line in clean_view.splitlines():
            print(f"  {line}")

    # -----------------------------------------------------------------------
    # Per-edit comparison: 10K's direct-Adeu output vs 10L's.
    # 10K's numbers are recorded in SPRINT_LOG §10K and copied here verbatim.
    # -----------------------------------------------------------------------

    print()
    print("--- PER-EDIT SPAN-WIDTH COMPARISON (10K vs 10L) ---")
    print("  10K (direct-Adeu): 1 block, w:del=29 words, w:ins=56 words (both wide).")

    if apply_error is None and verify_ok:
        # Count w:ins / w:del widths in the output.
        from lxml import etree
        with zipfile.ZipFile(OUTPUT_DOCX) as zf:
            doc_xml = zf.read("word/document.xml")
        root = etree.fromstring(doc_xml)
        ins_widths = [_element_word_count(el) for el in root.findall(".//w:ins", _NS)]
        del_widths = [_element_word_count(el) for el in root.findall(".//w:del", _NS)]
        total_ins = sum(ins_widths)
        total_del = sum(del_widths)
        print(
            f"  10L (mechanism): {len(ins_widths)} blocks, "
            f"w:ins widths={ins_widths} (total {total_ins}w), "
            f"w:del widths={del_widths} (total {total_del}w)."
        )
    else:
        print("  10L: apply failed; no output to compare.")

    write_transcript(
        ts=ts,
        parsed_edits=parsed_edits,
        narrowed=narrowed,
        modify_edits=modify_edits,
        applied=applied,
        skipped=skipped,
        apply_error=apply_error,
        verify_ok=verify_ok,
        verify_notes=verify_notes,
        clean_view=clean_view,
    )
    print(f"\ntranscript written to {TRANSCRIPT.name}")

    if apply_error is not None:
        raise SystemExit(1)
    if not verify_ok:
        raise SystemExit(2)


def write_transcript(
    *,
    ts: str,
    parsed_edits: list[dict],
    narrowed: list[NarrowedEdit],
    modify_edits: list,
    applied: int,
    skipped: int,
    apply_error: str | None,
    verify_ok: bool,
    verify_notes: list[str],
    clean_view: str,
) -> None:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"Sprint 10L — transcript — {ts}")
    lines.append("=" * 72)
    lines.append("")
    lines.append("INPUTS (copied from sprint-10k-claude-plugin-mcp-port):")
    lines.append(f"  parsed-edits.json  ({PARSED_EDITS_JSON.stat().st_size} bytes)")
    lines.append(f"  nda-input.docx     ({INPUT_DOCX.stat().st_size} bytes)")
    lines.append("")
    lines.append(f"PARSED EDITS (10K's LLM output, reprocessed): {len(parsed_edits)}")
    for i, e in enumerate(parsed_edits, 1):
        lines.append(f"  EDIT {i}:")
        lines.append(f"    target_text={_word_count(e['target_text'])}w:")
        lines.append(f"      {e['target_text']!r}")
        lines.append(f"    new_text={_word_count(e.get('new_text') or '')}w:")
        lines.append(f"      {(e.get('new_text') or '')!r}")
        lines.append(f"    comment={e.get('comment')!r}")
    lines.append("")

    lines.append(f"NARROWED EDITS (after post-processor): {len(narrowed)}")
    for i, ne in enumerate(narrowed, 1):
        lines.append(f"  NARROWED {i}:")
        lines.append(f"    raw_target (from block ops, pre-anchor, "
                     f"{_word_count(ne.raw_target)}w):")
        lines.append(f"      {ne.raw_target!r}")
        lines.append(f"    raw_new (from block ops, pre-anchor, "
                     f"{_word_count(ne.raw_new)}w):")
        lines.append(f"      {ne.raw_new!r}")
        lines.append(f"    anchor_tokens_prepended={ne.anchor_tokens_prepended} "
                     f"anchor_tokens_appended={ne.anchor_tokens_appended}")
        lines.append(f"    final target_text ({_word_count(ne.target_text)}w):")
        lines.append(f"      {ne.target_text!r}")
        lines.append(f"    final new_text ({_word_count(ne.new_text)}w):")
        lines.append(f"      {ne.new_text!r}")
        lines.append(f"    comment={ne.comment!r}")
        lines.append(f"    op_trace ({len(ne.op_trace)} ops):")
        op_name = {-1: "DEL", 0: "EQL", 1: "INS"}
        for op, text in ne.op_trace:
            lines.append(f"      [{op_name[op]}] {text!r}")
    lines.append("")

    lines.append("--- ADEU CALLS (VERBATIM) ---")
    for i, m in enumerate(modify_edits, 1):
        lines.append(f"  CALL {i}: ModifyText(")
        lines.append(f"    target_text={m.target_text!r},")
        lines.append(f"    new_text={m.new_text!r},")
        if m.comment is not None:
            lines.append(f"    comment={m.comment!r},")
        lines.append(f"  )")
    lines.append("")

    lines.append("--- APPLY RESULT ---")
    if apply_error is not None:
        lines.append(f"  apply_error: {apply_error}")
    else:
        lines.append(f"  edits_applied: {applied}")
        lines.append(f"  edits_skipped: {skipped}")
    lines.append("")

    lines.append("--- MECHANICAL VERIFICATION ---")
    lines.append(f"  verify_ok: {verify_ok}")
    for n in verify_notes:
        lines.append(f"  {n}")
    lines.append("")

    lines.append("--- CLEAN-VIEW §9 READ-BACK (simulated Accept-All) ---")
    for line in clean_view.splitlines():
        lines.append(f"  {line}")
    lines.append("")

    lines.append("--- PER-EDIT SPAN-WIDTH COMPARISON ---")
    lines.append("  10K (direct-Adeu):  1 block; w:del=29w; w:ins=56w.")
    if apply_error is None and verify_ok:
        from lxml import etree
        with zipfile.ZipFile(OUTPUT_DOCX) as zf:
            doc_xml = zf.read("word/document.xml")
        root = etree.fromstring(doc_xml)
        ins_widths = [_element_word_count(el) for el in root.findall(".//w:ins", _NS)]
        del_widths = [_element_word_count(el) for el in root.findall(".//w:del", _NS)]
        lines.append(
            f"  10L (mechanism):    {len(ins_widths)} block(s); "
            f"w:del widths={del_widths} (total {sum(del_widths)}w); "
            f"w:ins widths={ins_widths} (total {sum(ins_widths)}w)."
        )
    lines.append("")

    with open(TRANSCRIPT, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
