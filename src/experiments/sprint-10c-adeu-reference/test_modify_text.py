"""Sprint 10C — ModifyText behaviour tests.

Covers span-length variations, pure deletion, the prefix-match insertion
idiom, and multi-edit composition / overlap. Paragraph-boundary and
formatting-boundary behaviour is included here because ModifyText is the
only entry point that can span runs.
"""

from __future__ import annotations

import io
from typing import Any

from adeu import ModifyText, RedlineEngine
from adeu.redline.engine import BatchValidationError

from harness import (
    AUTHOR_ATTR,
    DEFAULT_AUTHOR,
    ID_ATTR,
    NS,
    TestResult,
    build_formatted_paragraph_docx,
    build_multi_paragraph_docx,
    build_single_paragraph_docx,
    del_texts,
    find_del,
    find_ins,
    ins_texts,
    load_xml,
    text_of,
)


def _apply(docx_bytes: bytes, edits: list[Any], author: str = DEFAULT_AUTHOR) -> tuple[dict, bytes]:
    engine = RedlineEngine(io.BytesIO(docx_bytes), author=author)
    result = engine.process_batch(edits)
    return result, engine.save_to_stream().getvalue()


# -------------------------- span-length variants ------------------------


def test_span_one_word() -> TestResult:
    r = TestResult(name="modify: 1-word span", passed=False)
    src = build_single_paragraph_docx("The governing law is Delaware and the parties agree.")
    result, out = _apply(src, [ModifyText(target_text="Delaware", new_text="New York")])
    root = load_xml(out)
    r.notes.append(f"result={result}")
    assert result == {"actions_applied": 0, "actions_skipped": 0, "edits_applied": 1, "edits_skipped": 0}
    assert "New York" in "".join(ins_texts(root))
    assert "Delaware" in "".join(del_texts(root))
    r.notes.append("1-word target — single w:del + single w:ins, MODIFICATION path")
    r.passed = True
    return r


def test_span_five_words() -> TestResult:
    r = TestResult(name="modify: 5-word span", passed=False)
    src = build_single_paragraph_docx(
        "The parties agree to resolve disputes through good-faith negotiation before litigation."
    )
    result, out = _apply(
        src,
        [ModifyText(target_text="resolve disputes through good-faith negotiation", new_text="settle disputes through binding arbitration")],
    )
    root = load_xml(out)
    r.notes.append(f"result={result}")
    assert result["edits_applied"] == 1
    assert "settle disputes through binding arbitration" in "".join(ins_texts(root))
    assert "resolve disputes through good-faith negotiation" in "".join(del_texts(root))
    r.passed = True
    return r


def test_span_fifteen_words() -> TestResult:
    r = TestResult(name="modify: 15-word span", passed=False)
    original = (
        "The Receiving Party shall use the Confidential Information solely for the purpose of evaluating the business relationship between the Parties and for no other purpose whatsoever."
    )
    target = "The Receiving Party shall use the Confidential Information solely for the purpose of evaluating the"  # 16 words
    new = "Each Party shall use the Confidential Information solely for the purpose of evaluating the"
    src = build_single_paragraph_docx(original)
    result, out = _apply(src, [ModifyText(target_text=target, new_text=new)])
    root = load_xml(out)
    r.notes.append(f"result={result}  ins={len(find_ins(root))} del={len(find_del(root))}")
    assert result["edits_applied"] == 1
    r.notes.append(
        "span still accepted at 15+ words — no internal length cap"
    )
    # trim_common_context narrows the edit — confirm that's what we see:
    all_ins = "".join(ins_texts(root))
    all_del = "".join(del_texts(root))
    r.notes.append(f"net ins text = {all_ins!r}")
    r.notes.append(f"net del text = {all_del!r}")
    r.passed = True
    return r


def test_span_full_sentence() -> TestResult:
    r = TestResult(name="modify: full sentence span; trim_common_context narrows edit", passed=False)
    src = build_single_paragraph_docx(
        "This Agreement shall be governed by English law. Disputes go to arbitration in London."
    )
    old = "This Agreement shall be governed by English law."
    new = "This Agreement shall be governed by the laws of the State of New York."
    result, out = _apply(src, [ModifyText(target_text=old, new_text=new)])
    root = load_xml(out)
    r.notes.append(f"result={result}")
    assert result["edits_applied"] == 1
    ins_all = "".join(ins_texts(root))
    del_all = "".join(del_texts(root))
    # trim_common_context in adeu/diff.py collapses the common "This Agreement shall be
    # governed by " prefix and the trailing "." so only the *differing* portion is redlined.
    r.notes.append(f"net ins = {ins_all!r}")
    r.notes.append(f"net del = {del_all!r}")
    assert "the laws of the State of New York" in ins_all
    assert "English law" in del_all
    # The common prefix must NOT appear in either redline block.
    assert "This Agreement shall be governed by" not in ins_all
    assert "This Agreement shall be governed by" not in del_all
    r.passed = True
    return r


def test_span_full_paragraph() -> TestResult:
    r = TestResult(name="modify: full paragraph; trim narrows to 'five'→'three'", passed=False)
    p1 = "Confidentiality survives termination by five years."
    p2 = "Governing law is Delaware."
    src = build_multi_paragraph_docx([p1, p2])
    result, out = _apply(src, [ModifyText(target_text=p1, new_text="Confidentiality survives termination by three years.")])
    root = load_xml(out)
    ins_all = "".join(ins_texts(root))
    del_all = "".join(del_texts(root))
    r.notes.append(f"result={result}  ins={ins_all!r}  del={del_all!r}")
    assert result["edits_applied"] == 1
    # Trim collapses to the word-level diff; " years" on both sides is common.
    assert "three" in ins_all
    assert "five" in del_all
    assert "Confidentiality survives termination" not in ins_all
    r.passed = True
    return r


def test_span_crossing_paragraph_boundary() -> TestResult:
    r = TestResult(name="modify: fuzzy regex CAN match across paragraph boundaries", passed=False)
    src = build_multi_paragraph_docx(["First paragraph.", "Second paragraph."])
    # Mapper.full_text joins paragraphs with "\n\n". Fuzzy regex tokenizes " " as \s+,
    # which matches "\n\n". Observe what the engine does.
    result, out = _apply(
        src, [ModifyText(target_text="First paragraph. Second", new_text="Merged text")]
    )
    root = load_xml(out)
    ins_all = "".join(ins_texts(root))
    del_all = "".join(del_texts(root))
    r.notes.append(f"result={result}  ins={ins_all!r}  del={del_all!r}")
    assert result["edits_applied"] == 1
    r.notes.append("QUIRK: cross-paragraph fuzzy match succeeded — engine's fuzzy regex"
                   " treats \\s+ as matching \\n\\n, so 'First paragraph. Second' matched.")
    r.passed = True
    return r


# ---------------------- deletion (empty new_text) ----------------------


def test_deletion_empty_new_text() -> TestResult:
    r = TestResult(name="modify: deletion via empty new_text", passed=False)
    src = build_single_paragraph_docx("The parties hereby agree that Delaware law applies.")
    result, out = _apply(src, [ModifyText(target_text=" Delaware law applies", new_text="")])
    root = load_xml(out)
    r.notes.append(f"result={result}  ins={len(find_ins(root))}  del={len(find_del(root))}")
    assert result["edits_applied"] == 1
    # Empty new_text → pure DELETION: we expect one or more w:del and zero w:ins with new text
    del_all = "".join(del_texts(root))
    assert "Delaware law applies" in del_all, del_all
    # w:ins: engine only emits w:ins if new_text is non-empty
    ins_all = "".join(ins_texts(root))
    r.notes.append(f"ins_all={ins_all!r}  (expected empty for pure deletion)")
    assert ins_all == "", f"pure deletion leaked a w:ins: {ins_all!r}"
    r.passed = True
    return r


# ------------------- insertion via prefix-match idiom ------------------


def test_insertion_prefix_match_basic() -> TestResult:
    r = TestResult(name="insertion: prefix-match idiom (basic)", passed=False)
    src = build_single_paragraph_docx("Clause A. Clause B. Clause C.")
    anchor = "Clause C."
    new_clause = "Clause C. Additional clause D."
    result, out = _apply(src, [ModifyText(target_text=anchor, new_text=new_clause)])
    root = load_xml(out)
    r.notes.append(f"result={result}")
    ins = find_ins(root)
    dl = find_del(root)
    r.notes.append(f"w:ins={len(ins)}  w:del={len(dl)}")
    # Pure insertion idiom: exactly one w:ins, zero w:del paired with it.
    assert len(ins) == 1, f"expected 1 w:ins, got {len(ins)}"
    assert len(dl) == 0, f"expected 0 w:del for prefix-match insert, got {len(dl)}"
    txt = text_of(ins[0], "t")
    assert "Additional clause D." in txt
    # Leading space behaviour: engine strips prefix overlap, so insertion text starts
    # with the character immediately after the overlap. Record what it is.
    r.notes.append(f"inserted text (verbatim): {txt!r}")
    r.passed = True
    return r


def test_insertion_empty_target_rejected() -> TestResult:
    r = TestResult(name="insertion: empty target_text rejected", passed=False)
    src = build_single_paragraph_docx("Some body text.")
    # Sprint 10B finding: empty target_text is not reachable via the heuristic.
    result, out = _apply(src, [ModifyText(target_text="", new_text="New sentence at start. ")])
    root = load_xml(out)
    r.notes.append(f"result={result}")
    # validate_edits short-circuits on empty target_text; apply_edits logs warning and skips.
    assert result["edits_applied"] == 0, result
    assert result["edits_skipped"] == 1, result
    assert len(find_ins(root)) == 0
    r.passed = True
    return r


def test_insertion_short_overlap() -> TestResult:
    r = TestResult(name="insertion: short prefix overlap (one word)", passed=False)
    src = build_single_paragraph_docx("The confidentiality obligations survive termination.")
    anchor = "survive termination."
    new = "survive termination. Return of Confidential Information is required."
    result, out = _apply(src, [ModifyText(target_text=anchor, new_text=new)])
    root = load_xml(out)
    r.notes.append(f"result={result} ins={len(find_ins(root))} del={len(find_del(root))}")
    assert result["edits_applied"] == 1
    assert len(find_del(root)) == 0
    ins = find_ins(root)
    assert len(ins) == 1
    r.notes.append(f"inserted: {text_of(ins[0], 't')!r}")
    r.passed = True
    return r


def test_insertion_long_overlap() -> TestResult:
    r = TestResult(name="insertion: long prefix overlap (full clause)", passed=False)
    src = build_single_paragraph_docx(
        "This Agreement shall be governed by English law and the parties submit to the exclusive jurisdiction of the courts of England."
    )
    anchor = "This Agreement shall be governed by English law and the parties submit to the exclusive jurisdiction of the courts of England."
    new = anchor + " Any disputes shall be resolved by binding arbitration."
    result, out = _apply(src, [ModifyText(target_text=anchor, new_text=new)])
    root = load_xml(out)
    r.notes.append(f"result={result} ins={len(find_ins(root))} del={len(find_del(root))}")
    assert result["edits_applied"] == 1
    assert len(find_del(root)) == 0
    r.passed = True
    return r


def test_insertion_at_paragraph_boundary() -> TestResult:
    r = TestResult(name="insertion: anchor ends paragraph, insert new paragraph", passed=False)
    src = build_multi_paragraph_docx(["Para one.", "Para two."])
    anchor = "Para one."
    # track_insert splits newline-containing text into multiple paragraphs.
    new = "Para one.\nInserted middle paragraph."
    result, out = _apply(src, [ModifyText(target_text=anchor, new_text=new)])
    root = load_xml(out)
    r.notes.append(f"result={result} ins={len(find_ins(root))} del={len(find_del(root))}")
    assert result["edits_applied"] == 1
    # Expect at least one w:ins containing "Inserted middle paragraph"
    all_ins = "".join(ins_texts(root))
    assert "Inserted middle paragraph" in all_ins, all_ins
    r.passed = True
    return r


# ----------------------- compose / interact ----------------------------


def test_multi_edit_non_overlapping() -> TestResult:
    r = TestResult(name="compose: three non-overlapping edits", passed=False)
    src = build_single_paragraph_docx(
        "Delaware governs this Agreement. Disputes go to litigation. The term is one year."
    )
    edits = [
        ModifyText(target_text="Delaware", new_text="New York"),
        ModifyText(target_text="litigation", new_text="arbitration"),
        ModifyText(target_text="one year", new_text="two years"),
    ]
    result, out = _apply(src, edits)
    root = load_xml(out)
    r.notes.append(f"result={result} ins={len(find_ins(root))} del={len(find_del(root))}")
    assert result["edits_applied"] == 3
    ins_all = "".join(ins_texts(root))
    del_all = "".join(del_texts(root))
    for token in ("New York", "arbitration", "two years"):
        assert token in ins_all, token
    for token in ("Delaware", "litigation", "one year"):
        assert token in del_all, token
    r.passed = True
    return r


def test_multi_edit_same_location_conflict() -> TestResult:
    r = TestResult(name="compose: overlapping edits, second skipped", passed=False)
    src = build_single_paragraph_docx("Payment terms are Net 30 days unless otherwise agreed.")
    edits = [
        ModifyText(target_text="Net 30 days", new_text="Net 60 days"),
        ModifyText(target_text="30 days", new_text="90 days"),
    ]
    result, out = _apply(src, edits)
    root = load_xml(out)
    r.notes.append(f"result={result}  ins={len(find_ins(root))}  del={len(find_del(root))}")
    # Engine records occupied_ranges and skips overlaps with a warning.
    assert result["edits_applied"] >= 1
    assert result["edits_skipped"] >= 1
    r.passed = True
    return r


def test_multi_edit_identical_skipped() -> TestResult:
    r = TestResult(name="compose: identical duplicate edits — validator rejects ambiguity", passed=False)
    src = build_single_paragraph_docx("Delaware law. Delaware courts.")
    # "Delaware" appears twice — validation should catch this unless we disambiguate
    try:
        result, out = _apply(
            src, [ModifyText(target_text="Delaware", new_text="New York")]
        )
        r.notes.append(f"UNEXPECTED: no BatchValidationError. result={result}")
        r.passed = False
    except BatchValidationError as e:
        r.notes.append(f"BatchValidationError raised: {e.errors[0][:100]}…")
        r.passed = True
    return r


# ------------------- formatting boundaries -----------------------------


def test_modify_inside_bold_run() -> TestResult:
    r = TestResult(name="formatting: target inside bold run", passed=False)
    src = build_formatted_paragraph_docx(
        [
            ("The term ", {}),
            ("Confidential Information", {"bold": True}),
            (" means all non-public data.", {}),
        ]
    )
    result, out = _apply(
        src, [ModifyText(target_text="Confidential Information", new_text="Proprietary Data")]
    )
    root = load_xml(out)
    r.notes.append(f"result={result}")
    assert result["edits_applied"] == 1
    # Observe whether the new text inherits the bold formatting or has it suppressed
    ins = find_ins(root)
    assert len(ins) == 1
    ins_run = ins[0].find(".//w:r", NS)
    rpr = ins_run.find("w:rPr", NS) if ins_run is not None else None
    if rpr is not None:
        b = rpr.find("w:b", NS)
        r.notes.append(f"new run rPr/w:b = {b.attrib if b is not None else 'absent'}")
    else:
        r.notes.append("new run has no rPr")
    r.passed = True
    return r


def test_modify_spanning_bold_boundary() -> TestResult:
    r = TestResult(name="formatting: target straddles bold + plain runs", passed=False)
    src = build_formatted_paragraph_docx(
        [
            ("The ", {}),
            ("Receiving Party", {"bold": True}),
            (" shall not disclose.", {}),
        ]
    )
    # Target spans the boundary between bold and plain
    result, out = _apply(
        src, [ModifyText(target_text="Receiving Party shall not disclose", new_text="Party agrees to keep it secret")]
    )
    root = load_xml(out)
    r.notes.append(f"result={result} ins={len(find_ins(root))} del={len(find_del(root))}")
    assert result["edits_applied"] == 1
    # Expect multiple w:del (one per affected run) and a single w:ins.
    dl = find_del(root)
    assert len(dl) >= 2, f"expected >= 2 w:del across formatting boundary, got {len(dl)}"
    r.notes.append(f"w:del count across bold/plain boundary = {len(dl)}")
    r.passed = True
    return r


def test_modify_with_markdown_replacement() -> TestResult:
    r = TestResult(name="formatting: markdown ** in new_text yields bold run", passed=False)
    src = build_single_paragraph_docx("The party shall comply with all requirements.")
    result, out = _apply(
        src, [ModifyText(target_text="all requirements", new_text="**all applicable requirements**")]
    )
    root = load_xml(out)
    r.notes.append(f"result={result}")
    assert result["edits_applied"] == 1
    ins = find_ins(root)
    assert len(ins) == 1
    # At least one run inside w:ins should carry w:b
    bolds = ins[0].findall(".//w:b", NS)
    r.notes.append(f"w:b count inside w:ins = {len(bolds)}")
    assert len(bolds) >= 1
    r.passed = True
    return r


# ----------------------- target_text uniqueness ------------------------


def test_target_found_zero_times() -> TestResult:
    r = TestResult(name="validate: target_text not present", passed=False)
    src = build_single_paragraph_docx("Some innocuous text.")
    try:
        _apply(src, [ModifyText(target_text="a string not in the doc", new_text="something")])
        r.notes.append("UNEXPECTED: no BatchValidationError")
        r.passed = False
    except BatchValidationError as e:
        r.notes.append(f"BatchValidationError errors={e.errors!r}")
        assert "not found" in e.errors[0].lower()
        r.passed = True
    return r


def test_target_found_many_times() -> TestResult:
    r = TestResult(name="validate: target_text ambiguous (>1 match)", passed=False)
    src = build_single_paragraph_docx("The party agrees. The party undertakes. The party warrants.")
    try:
        _apply(src, [ModifyText(target_text="The party", new_text="Each party")])
        r.notes.append("UNEXPECTED: no BatchValidationError")
        r.passed = False
    except BatchValidationError as e:
        r.notes.append(f"BatchValidationError errors[0][:160]={e.errors[0][:160]!r}")
        assert "ambiguous" in e.errors[0].lower() or "3 times" in e.errors[0].lower()
        r.passed = True
    return r


# ------------------------ change id / pairing --------------------------


def test_modification_emits_paired_ids() -> TestResult:
    r = TestResult(name="IDs: modification emits two IDs (del+ins)", passed=False)
    src = build_single_paragraph_docx("The governing law is Delaware law.")
    _result, out = _apply(src, [ModifyText(target_text="Delaware", new_text="New York")])
    root = load_xml(out)
    ids = []
    for el in find_ins(root) + find_del(root):
        ids.append((el.tag.rsplit("}", 1)[-1], el.get(ID_ATTR)))
    r.notes.append(f"(tag, id) = {ids}")
    ins_ids = {i for t, i in ids if t == "ins"}
    del_ids = {i for t, i in ids if t == "del"}
    assert ins_ids and del_ids
    assert ins_ids.isdisjoint(del_ids), "ins and del share an id (unexpected)"
    r.passed = True
    return r


def test_insertion_emits_single_id() -> TestResult:
    r = TestResult(name="IDs: prefix-match insertion emits a single id", passed=False)
    src = build_single_paragraph_docx("Clause X. Clause Y.")
    _result, out = _apply(
        src, [ModifyText(target_text="Clause Y.", new_text="Clause Y. Clause Z.")]
    )
    root = load_xml(out)
    dl = find_del(root)
    ins = find_ins(root)
    r.notes.append(f"ins={len(ins)} del={len(dl)}")
    assert len(dl) == 0
    assert len(ins) == 1
    r.passed = True
    return r


TESTS = [
    test_span_one_word,
    test_span_five_words,
    test_span_fifteen_words,
    test_span_full_sentence,
    test_span_full_paragraph,
    test_span_crossing_paragraph_boundary,
    test_deletion_empty_new_text,
    test_insertion_prefix_match_basic,
    test_insertion_empty_target_rejected,
    test_insertion_short_overlap,
    test_insertion_long_overlap,
    test_insertion_at_paragraph_boundary,
    test_multi_edit_non_overlapping,
    test_multi_edit_same_location_conflict,
    test_multi_edit_identical_skipped,
    test_modify_inside_bold_run,
    test_modify_spanning_bold_boundary,
    test_modify_with_markdown_replacement,
    test_target_found_zero_times,
    test_target_found_many_times,
    test_modification_emits_paired_ids,
    test_insertion_emits_single_id,
]


if __name__ == "__main__":
    from harness import run_suite, summarise

    print(f"\n== modify_text suite ({len(TESTS)} tests) ==")
    results = run_suite("modify_text", TESTS)
    raise SystemExit(summarise(results))
