"""Sprint 10P Phase 2.2 — cut-down 3-change Zenith fixture.

Builds nda-input-minimal.docx from nda-input-full.docx (10P-prep's
nda-output.docx, fetched via `git show` into this directory) by
surgically removing 15 of the 18 Zenith tracked changes via lxml,
keeping exactly 3 that exercise the three planner decision types:

  KEEP — original Chg:1 (ooxml=6, §1 deletion of "whether or not
    marked or described as confidential.")
    Maps to: action="accept" with planner-drafted comment.
    Tests: accept-with-comment composite (Adeu AcceptChange +
    ported add_comment via paragraph_context anchor — Q2(a) from
    Phase 0).

  KEEP — original Chg:7 (ooxml=10, §3 insertion of "and its
    Affiliates, and to its contractors and subcontractors engaged
    in connection with the Purpose,")
    Maps to: action="counter_propose".
    Tests: dispatcher routing through counter_propose_on_document
    to surgical or wholesale variant (depends on shared-token
    analysis between Zenith's text and the executor's replacement).

  KEEP — original Chg:15 (ooxml=14, §6 insertion of " Without
    limiting the foregoing, the Receiving Party is not required to
    delete...")
    Maps to: action="no_action" with reasoning note.
    Tests: preservation of Zenith's tracked change unchanged
    (attribution intact in raw OOXML).

After the trim, build_state_of_play renumbers the remaining 3 in
document order to Chg:1 (was Chg:1, ooxml=6), Chg:2 (was Chg:7,
ooxml=10), Chg:3 (was Chg:15, ooxml=14). The planner sees 3 entries.

Trim methodology — why lxml, not Adeu RejectChange:

The Zenith fixture has six paired modifications (delete + insert
sharing a revision_id). Adeu's RejectChange sweeps the paired node
to maintain audit-trail integrity (the resolved_history mechanism
in apply_review_actions, Sprint 10C finding). For most of the
discards this is helpful (rejecting one half of a discard pair
sweeps the other half, halving the call count). But for the §1
narrowing, we want to KEEP the deletion (ooxml=6) and DISCARD the
insertion (ooxml=7) — they share a revision_id, so any
RejectChange targeting one would sweep the other.

Surgical lxml removal sidesteps the pair-sweep mechanism by
operating element-by-element. For each unwanted w:ins, we remove
the entire wrapper (the inserted text disappears — restoring the
pre-Zenith state). For each unwanted w:del, we unwrap the wrapper
(promoting w:delText → w:t and lifting child runs to the parent —
restoring the deleted text as plain document content).

This is the same shape as Adeu's _reject_change body without the
pair-sweep top half. Reusing Adeu's primitive would require pre-
suppressing the pair lookup, which isn't a public surface — so
inlining is cleaner. The cleanup author's identity does not appear
in any element; the kept changes retain their Zenith Counsel
attribution end-to-end.

Discarded changes (15): Chg:2..6, Chg:8..14, Chg:16..18 in the
original Chg:N numbering. These cover §1 insertion (the
reasonable-understanding qualifier — discarded so the cut-down
exercises a single accept decision rather than two; the §1 paragraph
loses substantive coherence post-accept but the test is mechanical),
§1 purpose narrowing, §2 carve-out, §3 representatives + clause-7
reference, §4 court-order rewording + jurisdiction shift +
independent-development carve-out, §7 mandatory-law liability cap
reframing, and §8A no-warranty gap-fill (heading + body).

Usage:
    python src/redline/experiments/sprint-10P/build_input.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
sys.path.insert(0, str(REPO_ROOT))

from src.redline.lib.state_of_play import build_state_of_play  # noqa: E402

INPUT_FULL = HERE / "nda-input-full.docx"
OUTPUT_MINIMAL = HERE / "nda-input-minimal.docx"

# ooxml_ids (the actual w:id attribute values) to KEEP in the cut-down.
# Source: state-of-play of the full fixture (Phase 2.2 inspection).
KEEP_OOXML_IDS = {"6", "10", "14"}


def _surgical_remove_unwanted_changes(doc: Document, keep_ids: set[str]) -> tuple[int, int]:
    """Remove all w:ins and w:del elements whose w:id is NOT in keep_ids.

    For w:ins not in keep: remove the entire element (insertion discarded).
    For w:del not in keep: unwrap (promote w:delText → w:t and lift
    child runs to the parent — restores deleted text to plain content).

    Returns (removed_ins, removed_del) counts.
    """
    body = doc.element.body
    ins_removed = 0
    del_removed = 0

    for ins in list(body.findall(f".//{qn('w:ins')}")):
        wid = ins.get(qn("w:id"))
        if wid in keep_ids:
            continue
        parent = ins.getparent()
        if parent is None:
            continue
        parent.remove(ins)
        ins_removed += 1

    for d in list(body.findall(f".//{qn('w:del')}")):
        wid = d.get(qn("w:id"))
        if wid in keep_ids:
            continue
        parent = d.getparent()
        if parent is None:
            continue
        index = parent.index(d)
        for child in list(d):
            for dt in child.findall(f".//{qn('w:delText')}"):
                dt.tag = qn("w:t")
                if dt.text is not None and dt.text.strip() != dt.text:
                    dt.set(qn("xml:space"), "preserve")
            parent.insert(index, child)
            index += 1
        parent.remove(d)
        del_removed += 1

    return ins_removed, del_removed


def main() -> None:
    if not INPUT_FULL.exists():
        print(f"missing input: {INPUT_FULL}", file=sys.stderr)
        print(
            "Fetch via: "
            "git show sprint-10P-prep-zenith-firstpass:"
            "src/redline/experiments/sprint-10P-prep/nda-output.docx "
            f"> {INPUT_FULL}",
            file=sys.stderr,
        )
        sys.exit(2)

    print(f"[10P-build] full fixture: {INPUT_FULL.stat().st_size} bytes")

    full_state = build_state_of_play(str(INPUT_FULL))
    print(f"[10P-build] full state: {len(full_state.changes)} changes")
    keep_chgs = [e for e in full_state.changes if e.ooxml_id in KEEP_OOXML_IDS]
    discard_chgs = [e for e in full_state.changes if e.ooxml_id not in KEEP_OOXML_IDS]
    print(f"[10P-build] keeping {len(keep_chgs)} changes (ooxml_ids: {sorted(KEEP_OOXML_IDS)}):")
    for e in keep_chgs:
        txt = e.changed_text[:60] + "..." if len(e.changed_text) > 60 else e.changed_text
        print(f"  {e.change_id} (ooxml={e.ooxml_id}, {e.change_type}): {txt!r}")
    print(f"[10P-build] discarding {len(discard_chgs)} changes")

    # Copy and surgically clean.
    shutil.copy2(INPUT_FULL, OUTPUT_MINIMAL)
    doc = Document(str(OUTPUT_MINIMAL))
    ins_removed, del_removed = _surgical_remove_unwanted_changes(doc, KEEP_OOXML_IDS)
    doc.save(str(OUTPUT_MINIMAL))

    print(
        f"[10P-build] removed {ins_removed} w:ins + {del_removed} w:del "
        f"(total {ins_removed + del_removed})"
    )
    print(f"[10P-build] minimal fixture: {OUTPUT_MINIMAL.stat().st_size} bytes")

    # Verify post-trim state.
    minimal_state = build_state_of_play(str(OUTPUT_MINIMAL))
    print(f"[10P-build] minimal state: {len(minimal_state.changes)} changes")
    for entry in minimal_state.changes:
        txt = entry.changed_text[:60] + "..." if len(entry.changed_text) > 60 else entry.changed_text
        print(
            f"  {entry.change_id} (ooxml={entry.ooxml_id}, type={entry.change_type}, "
            f"author={entry.author!r}): {txt!r}"
        )

    if len(minimal_state.changes) != 3:
        print(
            f"[10P-build] ERROR: expected 3 changes, got {len(minimal_state.changes)}",
            file=sys.stderr,
        )
        sys.exit(1)

    if {e.author for e in minimal_state.changes} != {"Zenith Counsel"}:
        print(
            f"[10P-build] ERROR: not all changes attributed to 'Zenith Counsel': "
            f"{[e.author for e in minimal_state.changes]}",
            file=sys.stderr,
        )
        sys.exit(1)

    print("[10P-build] cut-down OK: 3 Zenith changes; attribution intact.")


if __name__ == "__main__":
    main()
