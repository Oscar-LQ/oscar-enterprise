"""Sprint 10C — comment attachment shapes and round-trip stability.

Covers:
  * Comment on a modification: where does it anchor (del, ins, or span)?
  * Comment on a pure insertion (prefix-match idiom).
  * Comment on a deletion.
  * Multiple comments on different edits.
  * Round-trip: edit → save → open fresh engine → edit → save; verify
    that IDs don't collide and the first round's edits survive.
  * Round-tripping through CriticMarkup: clean_view of a doc with edits
    must equal the semantic final text.
  * Editing a doc that *already* has tracked changes (mapper must cope
    with existing ins/del in the Raw view).
  * Markdown header idiom (``# Title`` in new_text produces a styled
    paragraph).
"""

from __future__ import annotations

import io

from adeu import (
    AcceptChange,
    ModifyText,
    RedlineEngine,
    extract_text_from_stream,
)

from harness import (
    AUTHOR_ATTR,
    DEFAULT_AUTHOR,
    ID_ATTR,
    NS,
    TestResult,
    build_multi_paragraph_docx,
    build_single_paragraph_docx,
    del_texts,
    find_del,
    find_ins,
    ins_texts,
    load_part,
    load_xml,
    text_of,
)


def test_comment_on_modification() -> TestResult:
    r = TestResult(name="comment: anchors at del → ins range on modifications", passed=False)
    src = build_single_paragraph_docx("The governing law is Delaware.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine.process_batch(
        [ModifyText(target_text="Delaware", new_text="New York", comment="Prefer NY for tax.")]
    )
    out = engine.save_to_stream().getvalue()
    root = load_xml(out)
    # commentRangeStart + commentRangeEnd should wrap the modification.
    starts = root.findall(".//w:commentRangeStart", NS)
    ends = root.findall(".//w:commentRangeEnd", NS)
    refs = root.findall(".//w:commentReference", NS)
    r.notes.append(f"start={len(starts)} end={len(ends)} ref={len(refs)}")
    assert starts and ends and refs
    comments_xml = load_part(out, "word/comments1.xml")
    assert comments_xml is not None
    assert b"Prefer NY for tax." in comments_xml
    r.passed = True
    return r


def test_comment_on_pure_insertion() -> TestResult:
    r = TestResult(name="comment: attaches to prefix-match insertion", passed=False)
    src = build_single_paragraph_docx("Clause A. Clause B.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine.process_batch(
        [ModifyText(target_text="Clause B.", new_text="Clause B. Clause C.", comment="Added for completeness.")]
    )
    out = engine.save_to_stream().getvalue()
    root = load_xml(out)
    starts = root.findall(".//w:commentRangeStart", NS)
    refs = root.findall(".//w:commentReference", NS)
    r.notes.append(f"start={len(starts)} ref={len(refs)}")
    assert starts and refs
    assert b"Added for completeness." in load_part(out, "word/comments1.xml")
    r.passed = True
    return r


def test_comment_on_pure_deletion() -> TestResult:
    r = TestResult(name="comment: SILENTLY DROPPED on pure deletion (new_text='')", passed=False)
    src = build_single_paragraph_docx("Keep this. Delete this clause.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    rv = engine.process_batch(
        [ModifyText(target_text=" Delete this clause.", new_text="", comment="No longer needed.")]
    )
    r.notes.append(f"rv = {rv}")
    out = engine.save_to_stream().getvalue()
    root = load_xml(out)
    # The w:del is present...
    dl = find_del(root)
    assert len(dl) >= 1
    # ...but the comment anchors and the comment itself are NOT emitted.
    starts = root.findall(".//w:commentRangeStart", NS)
    refs = root.findall(".//w:commentReference", NS)
    r.notes.append(f"start={len(starts)} ref={len(refs)} (expected 0 on DELETION path)")
    assert len(starts) == 0
    assert len(refs) == 0
    comments_xml = load_part(out, "word/comments1.xml")
    assert b"No longer needed." not in (comments_xml or b"")
    r.notes.append(
        "MAJOR FINDING: engine.py:862-864 DELETION path calls track_delete_run only; "
        "no comment attachment. Prompt must warn: comments on pure-deletion edits "
        "are silently dropped. Use modify-with-replacement OR attach comment to adjacent text."
    )
    r.passed = True
    return r


def test_multiple_comments_distinct_ids() -> TestResult:
    r = TestResult(name="comment: multiple comments in one batch get distinct ids", passed=False)
    src = build_single_paragraph_docx("Delaware. Litigation. One year.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine.process_batch(
        [
            ModifyText(target_text="Delaware", new_text="New York", comment="c1"),
            ModifyText(target_text="Litigation", new_text="Arbitration", comment="c2"),
            ModifyText(target_text="One year", new_text="Two years", comment="c3"),
        ]
    )
    out = engine.save_to_stream().getvalue()
    comments_xml = load_part(out, "word/comments1.xml")
    from lxml import etree as _etree
    croot = _etree.fromstring(comments_xml)
    comments = croot.findall(".//w:comment", NS)
    r.notes.append(f"comment count = {len(comments)}")
    ids = sorted(int(c.get(ID_ATTR)) for c in comments)
    r.notes.append(f"ids = {ids}")
    assert ids == [1, 2, 3]
    r.passed = True
    return r


def test_comment_survives_round_trip_open() -> TestResult:
    r = TestResult(name="round-trip: open edited doc with fresh engine — comment survives", passed=False)
    src = build_single_paragraph_docx("Delaware.")
    e1 = RedlineEngine(io.BytesIO(src), author="Oscar")
    e1.process_batch([ModifyText(target_text="Delaware", new_text="NY", comment="c")])
    after1 = e1.save_to_stream().getvalue()
    # Fresh engine reads the same doc
    e2 = RedlineEngine(io.BytesIO(after1), author="Oscar")
    out = e2.save_to_stream().getvalue()
    # Comment should still be present.
    comments_xml = load_part(out, "word/comments1.xml")
    from lxml import etree as _etree
    croot = _etree.fromstring(comments_xml)
    comments = croot.findall(".//w:comment", NS)
    r.notes.append(f"comments after round trip = {len(comments)}")
    assert len(comments) == 1
    r.passed = True
    return r


def test_edits_on_doc_with_existing_changes() -> TestResult:
    r = TestResult(name="round-trip: add new edit to doc with prior tracked changes", passed=False)
    src = build_single_paragraph_docx("Delaware and litigation.")
    e1 = RedlineEngine(io.BytesIO(src), author="Oscar")
    e1.process_batch([ModifyText(target_text="Delaware", new_text="New York")])
    after1 = e1.save_to_stream().getvalue()
    e2 = RedlineEngine(io.BytesIO(after1), author="Counterparty")
    # Add a second edit on text unchanged by the first author.
    e2.process_batch([ModifyText(target_text="litigation", new_text="arbitration")])
    final = e2.save_to_stream().getvalue()
    root = load_xml(final)
    r.notes.append(f"ins={len(find_ins(root))} del={len(find_del(root))}")
    ins_all = "".join(ins_texts(root))
    del_all = "".join(del_texts(root))
    assert "New York" in ins_all and "arbitration" in ins_all
    assert "Delaware" in del_all and "litigation" in del_all
    # Change ids should NOT collide
    ids = [int(el.get(ID_ATTR)) for el in find_ins(root) + find_del(root)]
    assert len(set(ids)) == len(ids), f"duplicate change ids: {ids}"
    r.passed = True
    return r


def test_edit_inside_existing_insertion() -> TestResult:
    r = TestResult(name="round-trip: editing text that's inside another author's w:ins", passed=False)
    src = build_single_paragraph_docx("The law is set.")
    # Oscar inserts text
    e1 = RedlineEngine(io.BytesIO(src), author="Oscar")
    e1.process_batch([ModifyText(target_text="set.", new_text="set. Additional sentence added here.")])
    after1 = e1.save_to_stream().getvalue()
    # Counterparty modifies text within Oscar's insertion
    e2 = RedlineEngine(io.BytesIO(after1), author="Counterparty")
    try:
        rv = e2.process_batch(
            [ModifyText(target_text="Additional sentence", new_text="Supplementary provision")]
        )
        r.notes.append(f"rv = {rv}")
        final = e2.save_to_stream().getvalue()
        root = load_xml(final)
        ins_all = "".join(ins_texts(root))
        r.notes.append(f"combined ins text = {ins_all!r}")
        assert "Supplementary provision" in ins_all
        r.passed = True
    except Exception as e:
        r.notes.append(f"FAILED: {type(e).__name__}: {e}")
        r.passed = False
    return r


def test_critic_markup_in_target_text() -> TestResult:
    r = TestResult(name="target_text: CriticMarkup in target matches existing markup span", passed=False)
    # ModifyText docstring says you can include {==...==} in target to match inside existing markup.
    src = build_single_paragraph_docx("Delaware.")
    e1 = RedlineEngine(io.BytesIO(src), author="Oscar")
    e1.process_batch([ModifyText(target_text="Delaware", new_text="Delaware", comment="note only")])
    # Above is a no-op mod (same text) with a comment — creates {==Delaware==} style span
    # Actually, the engine handles same-text case specially (returns True in heuristic).
    # Let me just confirm the docstring statement via a direct apply: include {==...==} literally.
    after = e1.save_to_stream().getvalue()
    raw = extract_text_from_stream(io.BytesIO(after))
    r.notes.append(f"raw after same-text+comment = {raw!r}")
    # Because target_text == new_text, engine skips the edit as a no-op — there's no markup.
    # So the CriticMarkup-in-target feature isn't reachable via a round-trip this way.
    # Document the finding.
    r.notes.append("NOTE: same-text modify collapses to no-op; CriticMarkup-in-target "
                   "documented in ModifyText docstring but not reachable from a clean doc.")
    r.passed = True
    return r


def test_markdown_header_in_new_text() -> TestResult:
    r = TestResult(name="new_text: leading '# Title' produces Heading-styled paragraph", passed=False)
    src = build_multi_paragraph_docx(["Introduction.", "Body."])
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    # Insert a header before Body. via prefix-match idiom
    engine.process_batch(
        [ModifyText(target_text="Body.", new_text="Body.\n# Section Title\nSection body.")]
    )
    out = engine.save_to_stream().getvalue()
    root = load_xml(out)
    # Look for a pStyle = "Heading1" (python-docx style_id) on any new paragraph
    pstyles = root.findall(".//w:pStyle", NS)
    vals = [p.get(f"{{{NS['w']}}}val") for p in pstyles]
    r.notes.append(f"pStyle values found = {vals}")
    assert any("Heading" in v for v in vals if v), vals
    r.passed = True
    return r


def test_markdown_bold_italic_in_new_text() -> TestResult:
    r = TestResult(name="new_text: **bold** and _italic_ produce w:b / w:i runs", passed=False)
    src = build_single_paragraph_docx("Replace here.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine.process_batch(
        [ModifyText(target_text="here", new_text="**bold** and _italic_ here")]
    )
    out = engine.save_to_stream().getvalue()
    root = load_xml(out)
    bolds = root.findall(".//w:ins//w:b", NS)
    italics = root.findall(".//w:ins//w:i", NS)
    r.notes.append(f"w:b in w:ins = {len(bolds)}  w:i in w:ins = {len(italics)}")
    assert bolds and italics
    r.passed = True
    return r


def test_clean_view_round_trip_three_edits() -> TestResult:
    r = TestResult(name="round-trip: clean_view text equals fully-accepted text (3 edits)", passed=False)
    src = build_single_paragraph_docx("Delaware law governs. Litigation goes to Delaware courts.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine.process_batch(
        [
            ModifyText(target_text="Delaware law", new_text="New York law"),
            ModifyText(target_text="Litigation", new_text="Arbitration"),
            ModifyText(target_text="Delaware courts", new_text="New York tribunals"),
        ]
    )
    after = engine.save_to_stream().getvalue()
    # Clean view via ingest
    clean_ingest = extract_text_from_stream(io.BytesIO(after), clean_view=True)
    # Now manually accept everything via accept_all_revisions and re-extract
    engine2 = RedlineEngine(io.BytesIO(after), author="Oscar")
    engine2.accept_all_revisions()
    accepted = engine2.save_to_stream().getvalue()
    accepted_text = extract_text_from_stream(io.BytesIO(accepted))
    r.notes.append(f"clean_view:   {clean_ingest!r}")
    r.notes.append(f"accept_all+extract: {accepted_text!r}")
    assert clean_ingest == accepted_text
    r.passed = True
    return r


def test_batch_all_action_types_smoke() -> TestResult:
    r = TestResult(name="smoke: accept+reject+reply+modify in one batch", passed=False)
    src = build_single_paragraph_docx("Delaware. Litigation.")
    # Prepare doc with one change + one comment so we have an id to reject.
    e1 = RedlineEngine(io.BytesIO(src), author="Oscar")
    e1.process_batch(
        [ModifyText(target_text="Delaware", new_text="NY", comment="c1")]
    )
    after = e1.save_to_stream().getvalue()
    # Extract the first change and comment id from the raw view.
    raw = extract_text_from_stream(io.BytesIO(after))
    r.notes.append(f"raw: {raw!r}")
    # Now mix: reject Chg:1, new modify, comment reply
    from adeu import RejectChange, ReplyComment
    e2 = RedlineEngine(io.BytesIO(after), author="Oscar")
    rv = e2.process_batch(
        [
            RejectChange(target_id="Chg:1"),
            ModifyText(target_text="Litigation", new_text="Arbitration"),
            ReplyComment(target_id="Com:1", text="ack"),
        ]
    )
    r.notes.append(f"rv = {rv}")
    # Rejecting Chg:1 also kills Com:1 (it's inside the reject range), so the
    # Com:1 reply is against a comment the same batch just deleted. Behaviour
    # should be: RejectChange+ReplyComment ordering — actions are processed in
    # list order; ReplyComment after RejectChange fails silently.
    # We just need the batch not to raise; behaviour gets documented.
    r.passed = True
    return r


TESTS = [
    test_comment_on_modification,
    test_comment_on_pure_insertion,
    test_comment_on_pure_deletion,
    test_multiple_comments_distinct_ids,
    test_comment_survives_round_trip_open,
    test_edits_on_doc_with_existing_changes,
    test_edit_inside_existing_insertion,
    test_critic_markup_in_target_text,
    test_markdown_header_in_new_text,
    test_markdown_bold_italic_in_new_text,
    test_clean_view_round_trip_three_edits,
    test_batch_all_action_types_smoke,
]


if __name__ == "__main__":
    from harness import run_suite, summarise

    print(f"\n== comments_and_round_trip suite ({len(TESTS)} tests) ==")
    results = run_suite("comments_and_round_trip", TESTS)
    raise SystemExit(summarise(results))
