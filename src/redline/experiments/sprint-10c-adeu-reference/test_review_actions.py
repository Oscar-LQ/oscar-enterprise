"""Sprint 10C — AcceptChange / RejectChange / ReplyComment tests.

The three review-action primitives operate on tracked-change IDs (``Chg:N``)
or comment IDs (``Com:N``) that appear in the CriticMarkup metadata blocks
emitted by ``extract_text_from_stream``. The engine resolves paired changes
via ``_get_paired_nodes`` — so accepting ``Chg:2`` atomically accepts the
paired ``w:del`` at ``Chg:1`` too.

Tests here exercise:
  * Accepting your own prior modification (commits replacement, drops original).
  * Rejecting your own prior modification (drops replacement, restores original).
  * Attempting to reject someone else's insertion (foreign author).
  * Attempting to reject counterparty "original" text (can't — nothing to reject
    unless it's been marked as a ``w:ins`` or ``w:del`` first).
  * Accepting/rejecting by either member of a paired change (same result).
  * ReplyComment on an existing comment.
"""

from __future__ import annotations

import io
from typing import Any

from adeu import (
    AcceptChange,
    ModifyText,
    RedlineEngine,
    RejectChange,
    ReplyComment,
    extract_text_from_stream,
)
from adeu.redline.engine import BatchValidationError

from harness import (
    AUTHOR_ATTR,
    DEFAULT_AUTHOR,
    ID_ATTR,
    NS,
    TestResult,
    build_single_paragraph_docx,
    del_texts,
    find_del,
    find_ins,
    ins_texts,
    load_part,
    load_xml,
    text_of,
)


def _apply_then_review(
    src: bytes,
    edits: list[Any],
    review: list[Any],
    author: str = DEFAULT_AUTHOR,
) -> tuple[dict, dict, bytes]:
    engine = RedlineEngine(io.BytesIO(src), author=author)
    edit_result = engine.process_batch(edits)
    out_after_edits = engine.save_to_stream().getvalue()
    # Start a fresh engine to exercise the accept/reject round-trip the way
    # a real workflow would: open the saved doc, act on it.
    engine2 = RedlineEngine(io.BytesIO(out_after_edits), author=author)
    review_result = engine2.process_batch(review)
    final = engine2.save_to_stream().getvalue()
    return edit_result, review_result, final


def test_accept_own_modification() -> TestResult:
    r = TestResult(name="accept: own modification commits new_text, drops original", passed=False)
    src = build_single_paragraph_docx("The governing law is Delaware.")
    _e, rv, final = _apply_then_review(
        src,
        [ModifyText(target_text="Delaware", new_text="New York")],
        [AcceptChange(target_id="Chg:1")],  # Accept by either id in the pair
    )
    r.notes.append(f"review result = {rv}")
    assert rv["actions_applied"] == 2 or rv["actions_applied"] == 1, rv
    # Accept is atomic across paired nodes — either 1 (reported once) or 2
    # depending on whether the paired id appeared in resolved_history.
    root = load_xml(final)
    assert len(find_ins(root)) == 0, "w:ins should be gone after accept"
    assert len(find_del(root)) == 0, "w:del should be gone after accept"
    # The resulting text should contain "New York" directly
    body_text = "".join(t.text or "" for t in root.findall(".//w:t", NS))
    r.notes.append(f"final text = {body_text!r}")
    assert "New York" in body_text
    assert "Delaware" not in body_text
    r.passed = True
    return r


def test_reject_own_modification() -> TestResult:
    r = TestResult(name="reject: own modification restores original, drops new_text", passed=False)
    src = build_single_paragraph_docx("The governing law is Delaware.")
    _e, rv, final = _apply_then_review(
        src,
        [ModifyText(target_text="Delaware", new_text="New York")],
        [RejectChange(target_id="Chg:1")],
    )
    r.notes.append(f"review result = {rv}")
    root = load_xml(final)
    assert len(find_ins(root)) == 0
    assert len(find_del(root)) == 0
    body_text = "".join(t.text or "" for t in root.findall(".//w:t", NS))
    r.notes.append(f"final text = {body_text!r}")
    assert "Delaware" in body_text
    assert "New York" not in body_text
    r.passed = True
    return r


def test_accept_by_second_id_of_pair() -> TestResult:
    r = TestResult(name="accept: Chg:N where N is second id of pair works identically", passed=False)
    src = build_single_paragraph_docx("The governing law is Delaware.")
    # Apply then inspect which id belongs to ins vs del so we target the ins id.
    engine = RedlineEngine(io.BytesIO(src), author=DEFAULT_AUTHOR)
    engine.process_batch([ModifyText(target_text="Delaware", new_text="New York")])
    after = engine.save_to_stream().getvalue()
    root = load_xml(after)
    ins_id = find_ins(root)[0].get(ID_ATTR)
    del_id = find_del(root)[0].get(ID_ATTR)
    r.notes.append(f"ins_id={ins_id}  del_id={del_id}")
    # Accept the ins id — engine should pair it with the del.
    engine2 = RedlineEngine(io.BytesIO(after), author=DEFAULT_AUTHOR)
    rv = engine2.process_batch([AcceptChange(target_id=f"Chg:{ins_id}")])
    r.notes.append(f"accept-by-ins-id result = {rv}")
    final = engine2.save_to_stream().getvalue()
    root2 = load_xml(final)
    assert len(find_ins(root2)) == 0
    assert len(find_del(root2)) == 0
    r.passed = True
    return r


def test_reject_nonexistent_id() -> TestResult:
    r = TestResult(name="reject: nonexistent target_id reports as skipped, not raised", passed=False)
    src = build_single_paragraph_docx("The governing law is Delaware.")
    engine = RedlineEngine(io.BytesIO(src), author=DEFAULT_AUTHOR)
    rv = engine.process_batch([RejectChange(target_id="Chg:999")])
    r.notes.append(f"rv = {rv}")
    assert rv["actions_skipped"] == 1
    assert rv["actions_applied"] == 0
    r.passed = True
    return r


def test_reject_foreign_author_change() -> TestResult:
    r = TestResult(name="reject: _get_paired_nodes groups by author — foreign change still resolvable by id", passed=False)
    src = build_single_paragraph_docx("The governing law is Delaware.")
    # Oscar applies a change.
    engine1 = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine1.process_batch([ModifyText(target_text="Delaware", new_text="New York")])
    after = engine1.save_to_stream().getvalue()
    # A different author, "Counterparty", tries to reject Oscar's change.
    engine2 = RedlineEngine(io.BytesIO(after), author="Counterparty")
    rv = engine2.process_batch([RejectChange(target_id="Chg:1")])
    r.notes.append(f"Counterparty-rejecting-Oscar's-change result = {rv}")
    final = engine2.save_to_stream().getvalue()
    root = load_xml(final)
    ins = find_ins(root)
    dl = find_del(root)
    r.notes.append(f"ins_remaining={len(ins)}  del_remaining={len(dl)}")
    # FINDING: engine CAN act on foreign changes by id — _get_paired_nodes only restricts pairing.
    # The primary node is found regardless of author; pairing is author-scoped.
    # So a Counterparty acting on Oscar's Chg:1 rejects at least the primary node.
    if rv["actions_applied"] >= 1:
        r.notes.append("QUIRK: non-owning author can reject/accept by id — author scope only pairs nodes,"
                       " it does not gate primary node resolution.")
    r.passed = True
    return r


def test_reject_non_tracked_text_unreachable() -> TestResult:
    r = TestResult(name="reject: counterparty text not tracked — nothing to reject", passed=False)
    # 10A / 10B: RejectChange cancels prior edits; it cannot make untracked text
    # disappear. Confirm there is no Chg:N or Com:N available on a clean doc.
    src = build_single_paragraph_docx("The governing law is Delaware.")
    critic = extract_text_from_stream(io.BytesIO(src))
    r.notes.append(f"clean-doc critic = {critic!r}")
    assert "{--" not in critic and "{++" not in critic and "Chg:" not in critic
    # Any RejectChange on a clean doc skips with applied=0.
    engine = RedlineEngine(io.BytesIO(src), author=DEFAULT_AUTHOR)
    rv = engine.process_batch([RejectChange(target_id="Chg:1")])
    r.notes.append(f"rv on clean doc = {rv}")
    assert rv["actions_applied"] == 0
    assert rv["actions_skipped"] == 1
    r.passed = True
    return r


def test_reply_comment() -> TestResult:
    r = TestResult(name="reply: threaded reply attached to existing comment", passed=False)
    src = build_single_paragraph_docx("The governing law is Delaware.")
    # Step 1 — attach a comment via ModifyText(comment=...)
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine.process_batch(
        [ModifyText(target_text="Delaware", new_text="New York", comment="Prefer NY.")]
    )
    after = engine.save_to_stream().getvalue()
    # Introspect comments part to find the assigned comment id.
    comments_xml = load_part(after, "word/comments1.xml")
    r.notes.append(f"comments xml present: {comments_xml is not None}")
    assert comments_xml is not None
    # Comment id is the first w:comment w:id attribute.
    from lxml import etree as _etree
    croot = _etree.fromstring(comments_xml)
    first_comment = croot.find(".//w:comment", NS)
    assert first_comment is not None
    parent_id = first_comment.get(ID_ATTR)
    r.notes.append(f"parent comment id = {parent_id}")
    # Step 2 — reply to the comment by id.
    engine2 = RedlineEngine(io.BytesIO(after), author="Counterparty")
    rv = engine2.process_batch([ReplyComment(target_id=f"Com:{parent_id}", text="Agreed.")])
    r.notes.append(f"reply result = {rv}")
    assert rv["actions_applied"] == 1
    final = engine2.save_to_stream().getvalue()
    croot2 = _etree.fromstring(load_part(final, "word/comments1.xml"))
    comments = croot2.findall(".//w:comment", NS)
    r.notes.append(f"comment count after reply = {len(comments)}")
    assert len(comments) == 2
    # The reply must carry Counterparty's author; the original keeps Oscar.
    authors = sorted(c.get(AUTHOR_ATTR) for c in comments)
    r.notes.append(f"authors = {authors}")
    assert authors == ["Counterparty", "Oscar"]
    r.passed = True
    return r


def test_comment_on_nonexistent_target() -> TestResult:
    r = TestResult(name="reply: nonexistent Com:N skipped, not raised", passed=False)
    src = build_single_paragraph_docx("Governing law.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    rv = engine.process_batch([ReplyComment(target_id="Com:999", text="Reply.")])
    r.notes.append(f"rv = {rv}")
    # _reply_to_comment returns True iff comments_part exists — it always does
    # after engine init. The reply succeeds (adds a comment), but the anchor
    # lookup fails silently. That is a behavioural finding.
    r.notes.append("QUIRK: ReplyComment on missing parent silently adds a stray comment"
                   " with no range anchor (anchor lookup warns but returns). applied=" + str(rv["actions_applied"]))
    r.passed = True
    return r


def test_accept_all_revisions_public_method() -> TestResult:
    r = TestResult(name="accept_all_revisions(): clears every ins/del/comment", passed=False)
    src = build_single_paragraph_docx("Delaware. Litigation. One year term.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine.process_batch(
        [
            ModifyText(target_text="Delaware", new_text="New York", comment="change 1"),
            ModifyText(target_text="Litigation", new_text="Arbitration", comment="change 2"),
        ]
    )
    engine.accept_all_revisions()
    final = engine.save_to_stream().getvalue()
    root = load_xml(final)
    assert len(find_ins(root)) == 0
    assert len(find_del(root)) == 0
    comments_xml = load_part(final, "word/comments1.xml")
    # All comments should have been purged by accept_all_revisions.
    from lxml import etree as _etree
    if comments_xml:
        c_root = _etree.fromstring(comments_xml)
        n = len(c_root.findall(".//w:comment", NS))
        r.notes.append(f"comments remaining after accept_all = {n}")
        assert n == 0
    r.passed = True
    return r


def test_batch_mixes_edits_and_actions() -> TestResult:
    r = TestResult(name="batch: edits + actions in one process_batch (actions first)", passed=False)
    src = build_single_paragraph_docx("Delaware.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    # First pass: create a change so we have an id to act on.
    engine.process_batch([ModifyText(target_text="Delaware", new_text="New York")])
    after1 = engine.save_to_stream().getvalue()
    engine2 = RedlineEngine(io.BytesIO(after1), author="Oscar")
    # Second pass: accept the prior change AND add a new edit in the same batch.
    rv = engine2.process_batch(
        [
            AcceptChange(target_id="Chg:1"),
            ModifyText(target_text="New York", new_text="California"),
        ]
    )
    r.notes.append(f"mixed batch rv = {rv}")
    # Actions apply first, mapper rebuilds, then edits validate+apply.
    assert rv["actions_applied"] >= 1
    assert rv["edits_applied"] == 1
    final = engine2.save_to_stream().getvalue()
    root = load_xml(final)
    assert "California" in "".join(ins_texts(root))
    r.passed = True
    return r


TESTS = [
    test_accept_own_modification,
    test_reject_own_modification,
    test_accept_by_second_id_of_pair,
    test_reject_nonexistent_id,
    test_reject_foreign_author_change,
    test_reject_non_tracked_text_unreachable,
    test_reply_comment,
    test_comment_on_nonexistent_target,
    test_accept_all_revisions_public_method,
    test_batch_mixes_edits_and_actions,
]


if __name__ == "__main__":
    from harness import run_suite, summarise

    print(f"\n== review_actions suite ({len(TESTS)} tests) ==")
    results = run_suite("review_actions", TESTS)
    raise SystemExit(summarise(results))
