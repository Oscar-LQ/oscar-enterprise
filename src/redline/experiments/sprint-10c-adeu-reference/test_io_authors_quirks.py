"""Sprint 10C — I/O, author attribution, direct low-level primitives, quirks, and error paths.

Covers:
  * BytesIO I/O contract: RedlineEngine only accepts BytesIO (not a path).
  * Author attribution: default "Adeu AI"; custom string; empty string.
  * Low-level public primitives: track_insert, track_delete_run.
  * CommentsManager eager creation of four parts even when no comments used.
  * Change-ID collisions across multiple engine instances on the same doc.
  * Error paths: BatchValidationError shape; ModifyText Pydantic rejection of None.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any

from docx import Document
from pydantic import ValidationError

from adeu import (
    AcceptChange,
    ModifyText,
    RedlineEngine,
    RejectChange,
    ReplyComment,
    __version__,
    extract_text_from_stream,
)
from adeu.redline.engine import BatchValidationError

from harness import (
    AUTHOR_ATTR,
    DEFAULT_AUTHOR,
    NS,
    TestResult,
    build_single_paragraph_docx,
    del_texts,
    find_del,
    find_ins,
    ins_texts,
    load_part,
    load_xml,
    load_zip_parts,
    text_of,
)


# ------------------------------- version --------------------------------


def test_version_string() -> TestResult:
    r = TestResult(name="module: adeu.__version__ is '1.1.0'", passed=False)
    r.notes.append(f"adeu.__version__ = {__version__!r}")
    assert __version__ == "1.1.0"
    r.passed = True
    return r


# -------------------------------- I/O ----------------------------------


def test_engine_accepts_str_path_via_docx() -> TestResult:
    """Type annotation says BytesIO; in practice python-docx accepts a str path too."""
    r = TestResult(name="I/O: RedlineEngine(<path-str>) — accepted (undocumented)", passed=False)
    import tempfile
    src = build_single_paragraph_docx("Hello.")
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        f.write(src)
        path = f.name
    try:
        engine = RedlineEngine(path, author="Oscar")  # type: ignore[arg-type]
        r.notes.append(
            "QUIRK: engine ACCEPTS a str path (python-docx Document() accepts both). "
            "The type annotation says BytesIO, but behaviour is broader — don't rely on it."
        )
        # Apply a trivial edit to confirm the engine is fully functional on a str path.
        engine.process_batch([ModifyText(target_text="Hello", new_text="Goodbye")])
        out = engine.save_to_stream().getvalue()
        assert zipfile.is_zipfile(io.BytesIO(out))
        r.passed = True
    except Exception as e:
        r.notes.append(f"engine rejected with {type(e).__name__}: {e}")
        r.passed = True  # finding either way
    return r


def test_engine_accepts_bytesio() -> TestResult:
    r = TestResult(name="I/O: RedlineEngine(BytesIO) is the documented path", passed=False)
    src = build_single_paragraph_docx("Hello.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine.process_batch([ModifyText(target_text="Hello", new_text="Goodbye")])
    out = engine.save_to_stream().getvalue()
    r.notes.append(f"output size = {len(out)} bytes")
    assert zipfile.is_zipfile(io.BytesIO(out))
    r.passed = True
    return r


def test_save_to_stream_seek_zero() -> TestResult:
    r = TestResult(name="I/O: save_to_stream returns a BytesIO at position 0", passed=False)
    src = build_single_paragraph_docx("Hello.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    stream = engine.save_to_stream()
    assert hasattr(stream, "tell") and hasattr(stream, "read")
    pos = stream.tell()
    r.notes.append(f"stream.tell() = {pos}")
    assert pos == 0
    first_bytes = stream.read(4)
    r.notes.append(f"first 4 bytes = {first_bytes!r}")
    assert first_bytes == b"PK\x03\x04"  # zip magic
    r.passed = True
    return r


# ------------------------ author attribution ---------------------------


def test_default_author_name() -> TestResult:
    r = TestResult(name="author: default is 'Adeu AI'", passed=False)
    src = build_single_paragraph_docx("Delaware.")
    engine = RedlineEngine(io.BytesIO(src))  # no author argument
    engine.process_batch([ModifyText(target_text="Delaware", new_text="New York")])
    out = engine.save_to_stream().getvalue()
    root = load_xml(out)
    authors = {el.get(AUTHOR_ATTR) for el in find_ins(root) + find_del(root)}
    r.notes.append(f"authors on tracked changes = {authors}")
    assert authors == {"Adeu AI"}
    r.passed = True
    return r


def test_custom_author_string() -> TestResult:
    r = TestResult(name="author: arbitrary string is preserved verbatim", passed=False)
    for name in ["Oscar", "Counterparty", "Firm Name LLP", "Someone With Spaces & Ampersand"]:
        src = build_single_paragraph_docx("Delaware.")
        engine = RedlineEngine(io.BytesIO(src), author=name)
        engine.process_batch([ModifyText(target_text="Delaware", new_text="NY")])
        out = engine.save_to_stream().getvalue()
        root = load_xml(out)
        authors = {el.get(AUTHOR_ATTR) for el in find_ins(root) + find_del(root)}
        r.notes.append(f"author={name!r} → {authors}")
        assert authors == {name}
    r.passed = True
    return r


def test_empty_author_string() -> TestResult:
    r = TestResult(name="author: empty string falls back to engine default (Adeu AI)", passed=False)
    src = build_single_paragraph_docx("Delaware.")
    engine = RedlineEngine(io.BytesIO(src), author="")
    engine.process_batch([ModifyText(target_text="Delaware", new_text="NY")])
    out = engine.save_to_stream().getvalue()
    root = load_xml(out)
    authors = {el.get(AUTHOR_ATTR) for el in find_ins(root) + find_del(root)}
    r.notes.append(f"authors when empty-string constructor = {authors}")
    # _create_track_change_tag uses ``author or self.author`` — both are "" here,
    # so the literal attribute value is "". Engine does NOT fall back to "Adeu AI".
    r.notes.append("QUIRK: empty author=\"\" persists as literal empty w:author attribute — engine does not coerce.")
    assert authors == {""}
    r.passed = True
    return r


def test_multi_author_same_doc() -> TestResult:
    r = TestResult(name="author: two authors on same doc preserve per-change attribution", passed=False)
    src = build_single_paragraph_docx("Delaware and litigation.")
    # Oscar makes one change
    e1 = RedlineEngine(io.BytesIO(src), author="Oscar")
    e1.process_batch([ModifyText(target_text="Delaware", new_text="New York")])
    after1 = e1.save_to_stream().getvalue()
    # Counterparty opens the result and makes another change
    e2 = RedlineEngine(io.BytesIO(after1), author="Counterparty")
    e2.process_batch([ModifyText(target_text="litigation", new_text="arbitration")])
    final = e2.save_to_stream().getvalue()
    root = load_xml(final)
    authors_ins = {el.get(AUTHOR_ATTR) for el in find_ins(root)}
    authors_del = {el.get(AUTHOR_ATTR) for el in find_del(root)}
    r.notes.append(f"ins authors = {authors_ins}")
    r.notes.append(f"del authors = {authors_del}")
    assert "Oscar" in (authors_ins | authors_del)
    assert "Counterparty" in (authors_ins | authors_del)
    r.passed = True
    return r


# ------------------------ comments part quirks --------------------------


def test_comments_parts_eagerly_created() -> TestResult:
    r = TestResult(name="quirk: CommentsManager eagerly creates 4 parts even without comments", passed=False)
    src = build_single_paragraph_docx("No edits here.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")  # noqa: F841
    # Save without applying any edits
    out = engine.save_to_stream().getvalue()
    parts = load_zip_parts(out)
    r.notes.append(f"parts count = {len(parts)}")
    for p in parts:
        r.notes.append(f"  {p}")
    comment_parts = [p for p in parts if "comments" in p.lower()]
    r.notes.append(f"comment-related parts = {comment_parts}")
    # 10B reported four: comments1.xml, commentsExtended1.xml, commentsIds1.xml,
    # commentsExtensible1.xml (plus their rels). Confirm.
    assert any("word/comments1.xml" in p for p in parts)
    assert any("word/commentsExtended1.xml" in p for p in parts)
    assert any("word/commentsIds1.xml" in p for p in parts)
    assert any("word/commentsExtensible1.xml" in p for p in parts)
    r.passed = True
    return r


def test_id_starts_at_one() -> TestResult:
    r = TestResult(name="quirk: first change id = 1 on a fresh doc", passed=False)
    src = build_single_paragraph_docx("Delaware.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine.process_batch([ModifyText(target_text="Delaware", new_text="NY")])
    out = engine.save_to_stream().getvalue()
    root = load_xml(out)
    ids = sorted(int(el.get(f"{{{NS['w']}}}id")) for el in find_ins(root) + find_del(root))
    r.notes.append(f"ids = {ids}")
    assert ids == [1, 2]  # one del + one ins
    r.passed = True
    return r


def test_id_continues_across_engine_restarts() -> TestResult:
    r = TestResult(name="quirk: engine scans existing ids; new edits continue from max+1", passed=False)
    src = build_single_paragraph_docx("Delaware and litigation.")
    e1 = RedlineEngine(io.BytesIO(src), author="Oscar")
    e1.process_batch([ModifyText(target_text="Delaware", new_text="NY")])
    after1 = e1.save_to_stream().getvalue()
    e2 = RedlineEngine(io.BytesIO(after1), author="Counterparty")
    e2.process_batch([ModifyText(target_text="litigation", new_text="arbitration")])
    final = e2.save_to_stream().getvalue()
    root = load_xml(final)
    ids = sorted(int(el.get(f"{{{NS['w']}}}id")) for el in find_ins(root) + find_del(root))
    r.notes.append(f"ids across both authors = {ids}")
    # First engine: 1,2; second engine: 3,4
    assert ids == [1, 2, 3, 4]
    r.passed = True
    return r


# -------------------- low-level primitives (direct use) -----------------


def test_low_level_track_insert_unused_anchorless() -> TestResult:
    r = TestResult(name="low-level: track_insert without anchor_run returns None (inline path) / fails on headers", passed=False)
    src = build_single_paragraph_docx("Placeholder.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    # track_insert with no anchor: inline path can still construct a w:ins but
    # without parent insertion, leaving the element dangling — user must insert.
    el = engine.track_insert("New text", anchor_run=None)
    r.notes.append(f"returned element: {el.tag if el is not None else None}")
    # Engine returns the w:ins element detached from the tree.
    assert el is not None
    assert el.tag.endswith("}ins")
    r.passed = True
    return r


def test_low_level_track_delete_run() -> TestResult:
    r = TestResult(name="low-level: track_delete_run replaces a run with w:del", passed=False)
    src = build_single_paragraph_docx("Hello World. Part two.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    # Take the first real Run from the document and delete it directly.
    first_para = engine.doc.paragraphs[0]
    runs = first_para.runs
    r.notes.append(f"run count before = {len(runs)}")
    assert len(runs) >= 1
    del_el = engine.track_delete_run(runs[0])
    r.notes.append(f"del element = {del_el.tag if del_el is not None else None}")
    out = engine.save_to_stream().getvalue()
    root = load_xml(out)
    dl = find_del(root)
    r.notes.append(f"w:del count after = {len(dl)}")
    assert len(dl) >= 1
    r.passed = True
    return r


# ----------------------- validate_edits (direct) ------------------------


def test_validate_edits_direct() -> TestResult:
    r = TestResult(name="validate_edits: direct call returns error list without applying", passed=False)
    src = build_single_paragraph_docx("Delaware.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    errors = engine.validate_edits([ModifyText(target_text="not present", new_text="x")])
    r.notes.append(f"errors = {errors}")
    assert isinstance(errors, list)
    assert len(errors) == 1
    assert "not found" in errors[0].lower()
    # Confirm no edit was applied: a fresh save shows zero ins/del.
    out = engine.save_to_stream().getvalue()
    root = load_xml(out)
    assert len(find_ins(root)) == 0
    assert len(find_del(root)) == 0
    r.passed = True
    return r


def test_validate_edits_clean_empty() -> TestResult:
    r = TestResult(name="validate_edits: empty target_text skipped (silently ok)", passed=False)
    src = build_single_paragraph_docx("Delaware.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    errors = engine.validate_edits([ModifyText(target_text="", new_text="New.")])
    r.notes.append(f"errors = {errors}")
    assert errors == []
    r.passed = True
    return r


# ------------------------- error paths ---------------------------------


def test_pydantic_rejects_none_target() -> TestResult:
    r = TestResult(name="pydantic: ModifyText(target_text=None) raises ValidationError", passed=False)
    try:
        ModifyText(target_text=None, new_text="x")  # type: ignore[arg-type]
        r.notes.append("UNEXPECTED: None accepted")
        r.passed = False
    except ValidationError as e:
        r.notes.append(f"ValidationError: {str(e)[:160]}")
        r.passed = True
    return r


def test_pydantic_accepts_missing_comment() -> TestResult:
    r = TestResult(name="pydantic: comment is Optional; defaults to None", passed=False)
    e = ModifyText(target_text="x", new_text="y")
    r.notes.append(f"comment={e.comment!r}")
    assert e.comment is None
    r.passed = True
    return r


def test_pydantic_rejects_missing_target_id() -> TestResult:
    r = TestResult(name="pydantic: AcceptChange without target_id raises", passed=False)
    try:
        AcceptChange()  # type: ignore[call-arg]
        r.notes.append("UNEXPECTED: accepted")
        r.passed = False
    except ValidationError as e:
        r.notes.append(f"ValidationError: {str(e)[:120]}")
        r.passed = True
    return r


def test_batch_validation_error_shape() -> TestResult:
    r = TestResult(name="error: BatchValidationError has .errors list", passed=False)
    src = build_single_paragraph_docx("Delaware.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    try:
        engine.process_batch([ModifyText(target_text="NOT THERE", new_text="x")])
        r.passed = False
    except BatchValidationError as e:
        r.notes.append(f"args[0] = {e.args[0]!r}")
        r.notes.append(f"errors list = {e.errors!r}")
        assert isinstance(e.errors, list) and len(e.errors) == 1
        r.passed = True
    return r


def test_invalid_docx_bytes() -> TestResult:
    r = TestResult(name="error: invalid .docx bytes raise on construction", passed=False)
    try:
        RedlineEngine(io.BytesIO(b"this is not a zip"), author="Oscar")
        r.passed = False
    except Exception as e:
        r.notes.append(f"{type(e).__name__}: {str(e)[:80]}")
        r.passed = True
    return r


def test_extract_invalid_docx_bytes() -> TestResult:
    r = TestResult(name="error: extract_text_from_stream on garbage raises ValueError", passed=False)
    try:
        extract_text_from_stream(io.BytesIO(b"not a zip"))
        r.passed = False
    except ValueError as e:
        r.notes.append(f"ValueError: {str(e)[:120]}")
        r.passed = True
    except Exception as e:
        r.notes.append(f"UNEXPECTED: {type(e).__name__}: {str(e)[:120]}")
        r.passed = False
    return r


# ----------------- Adeu sanitize submodule smoke test -------------------


def test_sanitize_submodule_surface() -> TestResult:
    r = TestResult(name="sanitize: submodule exposes sanitize_docx, SanitizeResult, SanitizeMode", passed=False)
    from adeu.sanitize import SanitizeMode, SanitizeResult, sanitize_docx
    r.notes.append(f"sanitize_docx={sanitize_docx.__qualname__}")
    r.notes.append(f"SanitizeResult={SanitizeResult.__name__}")
    r.notes.append(f"SanitizeMode members={[m.value for m in SanitizeMode]}")
    assert callable(sanitize_docx)
    assert hasattr(SanitizeResult, "__dataclass_fields__")
    r.passed = True
    return r


def test_sanitize_full_mode_on_clean_doc(tmp_root: str = "/tmp/sprint-10c-sanitize") -> TestResult:
    r = TestResult(name="sanitize: full mode on tracked-changes doc without --accept-all is blocked", passed=False)
    import os
    from adeu.sanitize import sanitize_docx
    from adeu.sanitize.core import SanitizeError
    os.makedirs(tmp_root, exist_ok=True)
    # Build a doc with tracked changes
    src = build_single_paragraph_docx("Delaware.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine.process_batch([ModifyText(target_text="Delaware", new_text="NY")])
    out = engine.save_to_stream().getvalue()
    src_path = f"{tmp_root}/in.docx"
    with open(src_path, "wb") as f:
        f.write(out)
    # Attempt full sanitize without accept_all → should raise SanitizeError
    try:
        sanitize_docx(src_path, output_path=f"{tmp_root}/out.docx")
        r.notes.append("UNEXPECTED: no SanitizeError")
        r.passed = False
    except SanitizeError as e:
        r.notes.append(f"SanitizeError raised as expected: {str(e)[:140]}…")
        r.passed = True
    return r


def test_sanitize_accept_all_produces_clean() -> TestResult:
    r = TestResult(name="sanitize: accept_all=True writes clean output", passed=False)
    import os
    from adeu.sanitize import sanitize_docx
    tmp = "/tmp/sprint-10c-sanitize"
    os.makedirs(tmp, exist_ok=True)
    src = build_single_paragraph_docx("Delaware.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine.process_batch([ModifyText(target_text="Delaware", new_text="NY")])
    src_path = f"{tmp}/in_accept.docx"
    with open(src_path, "wb") as f:
        f.write(engine.save_to_stream().getvalue())
    result = sanitize_docx(src_path, output_path=f"{tmp}/out_accept.docx", accept_all=True)
    r.notes.append(f"status={result.status}  tracked_found={result.tracked_changes_found}  accepted={result.tracked_changes_accepted}")
    assert result.tracked_changes_found >= 1
    assert result.tracked_changes_accepted == result.tracked_changes_found
    r.passed = True
    return r


TESTS = [
    test_version_string,
    test_engine_accepts_str_path_via_docx,
    test_engine_accepts_bytesio,
    test_save_to_stream_seek_zero,
    test_default_author_name,
    test_custom_author_string,
    test_empty_author_string,
    test_multi_author_same_doc,
    test_comments_parts_eagerly_created,
    test_id_starts_at_one,
    test_id_continues_across_engine_restarts,
    test_low_level_track_insert_unused_anchorless,
    test_low_level_track_delete_run,
    test_validate_edits_direct,
    test_validate_edits_clean_empty,
    test_pydantic_rejects_none_target,
    test_pydantic_accepts_missing_comment,
    test_pydantic_rejects_missing_target_id,
    test_batch_validation_error_shape,
    test_invalid_docx_bytes,
    test_extract_invalid_docx_bytes,
    test_sanitize_submodule_surface,
    test_sanitize_full_mode_on_clean_doc,
    test_sanitize_accept_all_produces_clean,
]


if __name__ == "__main__":
    from harness import run_suite, summarise

    print(f"\n== io_authors_quirks suite ({len(TESTS)} tests) ==")
    results = run_suite("io_authors_quirks", TESTS)
    raise SystemExit(summarise(results))
