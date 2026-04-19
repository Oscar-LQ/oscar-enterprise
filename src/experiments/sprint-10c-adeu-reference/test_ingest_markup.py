"""Sprint 10C — extract_text_from_stream and apply_edits_to_markdown tests.

These two helpers are the SDK's text-level viewing/transforming surface
(the mapper's output is internal; these are the public wrappers). Also
verifies round-trip: edit → extract raw view (CriticMarkup with Chg:N /
Com:N IDs visible) vs extract clean view (as if all edits accepted).
"""

from __future__ import annotations

import io

from adeu import (
    ModifyText,
    RedlineEngine,
    apply_edits_to_markdown,
    extract_text_from_stream,
)

from harness import (
    DEFAULT_AUTHOR,
    TestResult,
    build_multi_paragraph_docx,
    build_single_paragraph_docx,
)


def test_extract_clean_doc() -> TestResult:
    r = TestResult(name="extract: clean .docx round-trips to plain CriticMarkup-free text", passed=False)
    src = build_single_paragraph_docx("Hello World.")
    out = extract_text_from_stream(io.BytesIO(src))
    r.notes.append(f"out={out!r}")
    assert out == "Hello World."
    assert "{" not in out
    r.passed = True
    return r


def test_extract_raw_after_modify() -> TestResult:
    r = TestResult(name="extract: raw view shows {--X--}{++Y++} and [Chg:N] metadata", passed=False)
    src = build_single_paragraph_docx("The governing law is Delaware.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine.process_batch([ModifyText(target_text="Delaware", new_text="New York")])
    after = engine.save_to_stream().getvalue()
    raw = extract_text_from_stream(io.BytesIO(after))
    r.notes.append(f"raw={raw!r}")
    assert "{--Delaware--}" in raw
    assert "{++New York++}" in raw
    assert "[Chg:" in raw
    assert "Oscar" in raw
    r.passed = True
    return r


def test_extract_clean_view_after_modify() -> TestResult:
    r = TestResult(name="extract: clean_view=True emits accepted-view text", passed=False)
    src = build_single_paragraph_docx("The governing law is Delaware.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine.process_batch([ModifyText(target_text="Delaware", new_text="New York")])
    after = engine.save_to_stream().getvalue()
    clean = extract_text_from_stream(io.BytesIO(after), clean_view=True)
    r.notes.append(f"clean={clean!r}")
    assert clean == "The governing law is New York."
    assert "Delaware" not in clean
    assert "{" not in clean
    r.passed = True
    return r


def test_extract_after_deletion() -> TestResult:
    r = TestResult(name="extract: raw shows {--X--}, clean hides it", passed=False)
    src = build_single_paragraph_docx("Keep this. Delete this clause.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine.process_batch([ModifyText(target_text=" Delete this clause.", new_text="")])
    after = engine.save_to_stream().getvalue()
    raw = extract_text_from_stream(io.BytesIO(after))
    clean = extract_text_from_stream(io.BytesIO(after), clean_view=True)
    r.notes.append(f"raw={raw!r}")
    r.notes.append(f"clean={clean!r}")
    assert "{-- Delete this clause.--}" in raw or "{--Delete this clause.--}" in raw
    assert "Delete this clause" not in clean
    assert "Keep this" in clean
    r.passed = True
    return r


def test_extract_after_insertion_prefix_match() -> TestResult:
    r = TestResult(name="extract: prefix-match insertion shows {++ suffix ++}", passed=False)
    src = build_single_paragraph_docx("Clause A. Clause B.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine.process_batch(
        [ModifyText(target_text="Clause B.", new_text="Clause B. Clause C.")]
    )
    after = engine.save_to_stream().getvalue()
    raw = extract_text_from_stream(io.BytesIO(after))
    clean = extract_text_from_stream(io.BytesIO(after), clean_view=True)
    r.notes.append(f"raw={raw!r}")
    r.notes.append(f"clean={clean!r}")
    assert "{++" in raw
    assert "{--" not in raw  # pure insertion → no w:del, no {--...--}
    assert clean == "Clause A. Clause B. Clause C."
    r.passed = True
    return r


def test_extract_with_comment() -> TestResult:
    r = TestResult(name="extract: comments render as [Com:N] blocks in raw, absent in clean", passed=False)
    src = build_single_paragraph_docx("The governing law is Delaware.")
    engine = RedlineEngine(io.BytesIO(src), author="Oscar")
    engine.process_batch(
        [ModifyText(target_text="Delaware", new_text="New York", comment="Prefer NY.")]
    )
    after = engine.save_to_stream().getvalue()
    raw = extract_text_from_stream(io.BytesIO(after))
    clean = extract_text_from_stream(io.BytesIO(after), clean_view=True)
    r.notes.append(f"raw={raw!r}")
    r.notes.append(f"clean={clean!r}")
    assert "[Com:" in raw
    assert "Prefer NY." in raw
    assert "[Com:" not in clean
    assert "Prefer NY." not in clean
    r.passed = True
    return r


def test_extract_multi_paragraph_separator() -> TestResult:
    r = TestResult(name="extract: multi-paragraph joins with two newlines", passed=False)
    src = build_multi_paragraph_docx(["First.", "Second.", "Third."])
    out = extract_text_from_stream(io.BytesIO(src))
    r.notes.append(f"out={out!r}")
    assert out == "First.\n\nSecond.\n\nThird."
    r.passed = True
    return r


def test_apply_edits_to_markdown_modification() -> TestResult:
    r = TestResult(name="apply_edits_to_markdown: modification emits {--X--}{++Y++}", passed=False)
    text = "The governing law is Delaware."
    edits = [ModifyText(target_text="Delaware", new_text="New York")]
    out = apply_edits_to_markdown(text, edits)
    r.notes.append(f"out={out!r}")
    assert "{--Delaware--}" in out
    assert "{++New York++}" in out
    r.passed = True
    return r


def test_apply_edits_to_markdown_deletion() -> TestResult:
    r = TestResult(name="apply_edits_to_markdown: deletion emits {--X--} only", passed=False)
    text = "The term is Delaware."
    edits = [ModifyText(target_text="Delaware", new_text="")]
    out = apply_edits_to_markdown(text, edits)
    r.notes.append(f"out={out!r}")
    assert "{--Delaware--}" in out
    assert "{++" not in out
    r.passed = True
    return r


def test_apply_edits_to_markdown_empty_target_skipped() -> TestResult:
    r = TestResult(name="apply_edits_to_markdown: empty target skipped (no pure insertion in text mode)", passed=False)
    text = "Body text."
    edits = [ModifyText(target_text="", new_text="Title. ")]
    out = apply_edits_to_markdown(text, edits)
    r.notes.append(f"out={out!r}")
    assert out == text  # unchanged — pure insertion not supported in markdown mode
    r.passed = True
    return r


def test_apply_edits_to_markdown_highlight_only() -> TestResult:
    r = TestResult(name="apply_edits_to_markdown: highlight_only emits {==X==}", passed=False)
    text = "Flag this portion."
    edits = [ModifyText(target_text="this portion", new_text="(ignored in highlight mode)")]
    out = apply_edits_to_markdown(text, edits, highlight_only=True)
    r.notes.append(f"out={out!r}")
    assert "{==this portion==}" in out
    assert "{--" not in out
    assert "{++" not in out
    r.passed = True
    return r


def test_apply_edits_to_markdown_include_index() -> TestResult:
    r = TestResult(name="apply_edits_to_markdown: include_index adds [Edit:N] trailer", passed=False)
    text = "Change me."
    edits = [ModifyText(target_text="Change", new_text="Modify", comment="Reason.")]
    out = apply_edits_to_markdown(text, edits, include_index=True)
    r.notes.append(f"out={out!r}")
    assert "{>>Reason. [Edit:0]<<}" in out
    r.passed = True
    return r


def test_apply_edits_to_markdown_unfound_skipped() -> TestResult:
    r = TestResult(name="apply_edits_to_markdown: unmatched target skipped, no error", passed=False)
    text = "Body."
    edits = [ModifyText(target_text="not present", new_text="replacement")]
    out = apply_edits_to_markdown(text, edits)
    r.notes.append(f"out={out!r}")
    assert out == text
    r.passed = True
    return r


def test_apply_edits_to_markdown_multiple_edits() -> TestResult:
    r = TestResult(name="apply_edits_to_markdown: multiple non-overlapping edits apply in reverse position order", passed=False)
    text = "Delaware governs. Term is one year."
    edits = [
        ModifyText(target_text="Delaware", new_text="New York"),
        ModifyText(target_text="one year", new_text="two years"),
    ]
    out = apply_edits_to_markdown(text, edits)
    r.notes.append(f"out={out!r}")
    assert "{--Delaware--}{++New York++}" in out
    assert "{--one year--}{++two years++}" in out
    r.passed = True
    return r


TESTS = [
    test_extract_clean_doc,
    test_extract_raw_after_modify,
    test_extract_clean_view_after_modify,
    test_extract_after_deletion,
    test_extract_after_insertion_prefix_match,
    test_extract_with_comment,
    test_extract_multi_paragraph_separator,
    test_apply_edits_to_markdown_modification,
    test_apply_edits_to_markdown_deletion,
    test_apply_edits_to_markdown_empty_target_skipped,
    test_apply_edits_to_markdown_highlight_only,
    test_apply_edits_to_markdown_include_index,
    test_apply_edits_to_markdown_unfound_skipped,
    test_apply_edits_to_markdown_multiple_edits,
]


if __name__ == "__main__":
    from harness import run_suite, summarise

    print(f"\n== ingest_markup suite ({len(TESTS)} tests) ==")
    results = run_suite("ingest_markup", TESTS)
    raise SystemExit(summarise(results))
