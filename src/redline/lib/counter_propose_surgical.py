"""Surgical word-level counter-proposal helpers.

Provides functions to apply fine-grained word-level diffs to tracked
change elements, producing w:del/w:ins for only the changed words
instead of replacing the entire element wholesale.

Uses diff_words from src.redline.lib.word_diff to identify changed
spans, then manipulates the OOXML elements surgically. Falls back to
wholesale when the element structure is too complex for safe surgical
editing.

Source: claude-plugin-mcp/src/negotiation/counter_propose_surgical.py
(verbatim, imports adapted for redline.lib paths).
See src/redline/lib/__init__.py for the package-level upgrade warning.
"""

from copy import deepcopy

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from src.redline.lib.counter_propose_helpers import (
    _convert_run_text_to_del_text,
    _create_run_with_text,
    _create_tracked_change,
)
from src.redline.lib.word_diff import diff_words, verify_reconstruction


def can_apply_surgical_diff(
    element: etree._Element,
    change_type: str,
) -> bool:
    """Check whether a tracked change element is simple enough for surgical diff.

    Returns True only for single-run elements (one direct w:r child).
    Multi-run elements are too complex -- word boundaries may not align
    with run boundaries, making surgical splitting unsafe.
    """
    direct_runs = element.findall(qn("w:r"))
    return len(direct_runs) == 1


def extract_element_text(
    element: etree._Element,
    change_type: str,
) -> str:
    """Extract plain text from a tracked change element's run children.

    For insertions, reads w:t elements. For deletions, reads w:delText
    elements. Only reads from direct w:r children (not nested elements).
    """
    text_tag = qn("w:t") if change_type == "insertion" else qn("w:delText")
    parts: list[str] = []
    for run in element.findall(qn("w:r")):
        for text_el in run.findall(text_tag):
            if text_el.text:
                parts.append(text_el.text)
    return "".join(parts)


def compute_surgical_diffs(
    old_text: str,
    new_text: str,
) -> list[tuple[int, str]] | None:
    """Compute word-level diffs and verify reconstruction.

    Returns the diff list if reconstruction verifies, None otherwise.
    Also returns None if the diff shows no changes (all EQUAL).
    """
    diffs = diff_words(old_text, new_text)
    if not diffs:
        return None

    if not verify_reconstruction(diffs, new_text):
        return None

    has_changes = any(op != 0 for op, _ in diffs)
    if not has_changes:
        return None

    return diffs


def is_text_identical(old_text: str, new_text: str) -> bool:
    """Check if old and new text are identical (no change needed)."""
    return old_text.strip() == new_text.strip()


def apply_surgical_insertion_counter_propose(
    ins_element: etree._Element,
    diffs: list[tuple[int, str]],
    client_author: str,
    timestamp: str,
    next_id: int,
) -> int:
    """Apply surgical word-level counter-proposal to an insertion element.

    Splits the parent w:ins into fragments at each INSERT boundary so
    that client insertions appear at the correct position in the text
    flow. For each diff segment:
    - EQUAL (0): Plain run appended to the current w:ins fragment
    - DELETE (-1): Client w:del wrapping deleted text inside current fragment
    - INSERT (1): Close current fragment, emit client w:ins, start new fragment

    The first fragment reuses the original w:ins element. Subsequent
    fragments get new w:id values but preserve the original author/date.
    """
    original_author = ins_element.get(qn("w:author"))
    original_date = ins_element.get(qn("w:date"))
    original_id = ins_element.get(qn("w:id"))
    original_run = ins_element.findall(qn("w:r"))[0]
    source_rPr = original_run.find(qn("w:rPr"))

    ins_element.remove(original_run)

    fragments: list[etree._Element] = []
    current_fragment = ins_element

    for op, text in diffs:
        if op == 0:
            run = _create_run_with_text(text, source_rPr=source_rPr)
            current_fragment.append(run)
        elif op == -1:
            del_wrapper = _create_tracked_change(
                "w:del", client_author, timestamp, next_id
            )
            next_id += 1
            del_run = _create_run_with_text(text, source_rPr=source_rPr)
            _convert_run_text_to_del_text(del_run)
            del_wrapper.append(del_run)
            current_fragment.append(del_wrapper)
        elif op == 1:
            if len(current_fragment) > 0:
                fragments.append(current_fragment)

            client_ins = _create_tracked_change(
                "w:ins", client_author, timestamp, next_id
            )
            next_id += 1
            ins_run = _create_run_with_text(text, source_rPr=source_rPr)
            client_ins.append(ins_run)
            fragments.append(client_ins)

            current_fragment = _create_tracked_change(
                "w:ins", original_author, original_date, next_id
            )
            next_id += 1

    if len(current_fragment) > 0:
        fragments.append(current_fragment)

    parent = ins_element.getparent()
    original_index = list(parent).index(ins_element)
    parent.remove(ins_element)

    for i, fragment in enumerate(fragments):
        parent.insert(original_index + i, fragment)

    return next_id


def apply_surgical_deletion_counter_propose(
    del_element: etree._Element,
    diffs: list[tuple[int, str]],
    client_author: str,
    timestamp: str,
    next_id: int,
) -> int:
    """Apply surgical word-level counter-proposal to a deletion element.

    For deletions, the counterparty deleted some text. The client wants
    to replace it with different text. The w:del stays unchanged
    (counterparty's deletion remains visible). The client w:ins must
    contain the FULL replacement text (EQUAL + INSERT segments from the
    diff), not just INSERT segments alone — otherwise the EQUAL portions
    (shared between old and new) would be lost on accept.
    """
    del_runs = del_element.findall(qn("w:r"))
    source_rPr = None
    if del_runs:
        source_rPr = del_runs[0].find(qn("w:rPr"))

    replacement_parts: list[str] = []
    for op, text in diffs:
        if op >= 0:  # EQUAL (0) or INSERT (1)
            replacement_parts.append(text)

    if not replacement_parts:
        return next_id

    replacement_text = "".join(replacement_parts)
    new_ins = _create_tracked_change("w:ins", client_author, timestamp, next_id)
    next_id += 1
    new_run = _create_run_with_text(replacement_text, source_rPr=source_rPr)
    new_ins.append(new_run)

    parent = del_element.getparent()
    if parent.tag == qn("w:ins"):
        grandparent = parent.getparent()
        wrapper_index = list(grandparent).index(parent)
        grandparent.insert(wrapper_index + 1, new_ins)
    else:
        del_index = list(parent).index(del_element)
        parent.insert(del_index + 1, new_ins)

    return next_id
