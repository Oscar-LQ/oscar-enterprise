# Adeu 1.1.0 — API Reference

> Exhaustive operation inventory, grounded in Adeu 1.1.0's installed
> source at `/sandbox/.venv/lib/python3.13/site-packages/adeu/` and in
> the direct-API test battery at
> `src/experiments/sprint-10c-adeu-reference/`.
>
> Every behaviour asserted here is backed by a test that ran clean on
> 2026-04-19 against adeu==1.1.0. Where a behaviour is non-obvious,
> unclear from the docstring, or surprising, it is flagged as a
> **Quirk**. "Quirk" is not a bug — it's a behaviour that a reader of
> the public docstrings alone would not predict.
>
> Sprint 10D's system prompt will be built on this document. Sprint 10E
> will check the agent's output against the companion criteria doc. Both
> must stay true to what the engine actually does.
>
> **Versioning.** Everything below is for adeu 1.1.0 exactly. Adeu is
> API-churn prone (see Sprint 10A finding #2 — 0.9 → 1.0 → 1.1 was
> breaking). If you touch a later Adeu version, re-run the battery
> before trusting this document.

## 1. Package Layout

```
adeu/
├── __init__.py           public exports (see §1.1)
├── models.py             Pydantic models: ModifyText, Accept/Reject/Reply, DocumentChange
├── ingest.py             extract_text_from_stream — raw/clean CriticMarkup view
├── markup.py             apply_edits_to_markdown — text-mode CriticMarkup emitter
├── diff.py               trim_common_context, generate_edits_from_text (internal)
├── redline/
│   ├── engine.py         RedlineEngine, BatchValidationError
│   ├── mapper.py         DocumentMapper (internal, reached via PrivateAttr)
│   └── comments.py       CommentsManager (internal, always constructed)
├── sanitize/             separate public submodule (§10)
├── utils/docx.py         normalize_docx, iterators (internal)
├── cli.py                console_script `adeu` (not used from SDK)
└── server.py             console_script `adeu-server` (MCP; dormant for SDK callers)
```

### 1.1 What `adeu.__all__` exports

```python
from adeu import (
    RedlineEngine,          # the engine; the main SDK surface
    ModifyText,             # edit primitive (Pydantic BaseModel)
    AcceptChange,           # review primitive
    RejectChange,           # review primitive
    ReplyComment,           # review primitive
    DocumentChange,         # Annotated[Union[...], Field(discriminator="type")]
    extract_text_from_stream,
    apply_edits_to_markdown,
    __version__,            # "1.1.0"
)
```

Nothing else in the `__all__` list. `BatchValidationError` must be
imported from `adeu.redline.engine`. `sanitize_docx` from
`adeu.sanitize`.

---

## 2. `RedlineEngine`

**Import:** `from adeu import RedlineEngine`
**Source:** `adeu/redline/engine.py:34-1219`

### 2.1 Construction

```python
engine = RedlineEngine(doc_stream: BytesIO, author: str = "Adeu AI")
```

| Field | Type | Default | Notes |
|------|------|---------|-------|
| `doc_stream` | `BytesIO` | — | **Quirk.** Annotation says `BytesIO`, but `python-docx` accepts str paths and `Path` too. Works, but undocumented — don't rely on it for forward-compat. |
| `author` | `str` | `"Adeu AI"` | Becomes the `w:author` attribute on every `w:ins` / `w:del` / `w:comment` this engine emits. **Quirk.** Empty string (`""`) persists as a literal empty attribute; engine does NOT coerce to default. |

**Side effects on construction:**

1. Calls `normalize_docx(self.doc)` — strips `w:proofErr`, coalesces adjacent
   identically-formatted runs (`adeu/utils/docx.py:362-382`).
2. Constructs a `DocumentMapper` (internal).
3. Constructs a `CommentsManager`, which **eagerly creates four XML parts**
   (`word/comments1.xml`, `word/commentsExtended1.xml`,
   `word/commentsIds1.xml`, `word/commentsExtensible1.xml`) plus their
   relationships, **even if no comments are added**. Confirmed in battery
   `test_comments_parts_eagerly_created`. This inflates every output
   `.docx` to 21 parts. Not a correctness issue; a size-inflation quirk.
4. Scans existing `w:id` attributes on `w:ins`/`w:del` and sets
   `current_id = max_seen`. New edits continue from `max + 1`, so IDs are
   collision-free across round-trip edits by different engines/authors
   (`test_id_continues_across_engine_restarts`).
5. Stamps `self.timestamp` with the current UTC time (used for both
   `w:date` and `w16du:dateUtc` attributes on emitted changes).

### 2.2 Public methods

#### `process_batch(changes: List[DocumentChange]) -> dict`

The main entry point. Takes a mixed list of `AcceptChange`,
`RejectChange`, `ReplyComment`, and `ModifyText` instances and applies
them in two phases:

1. **Actions first.** Every `AcceptChange`/`RejectChange`/`ReplyComment`
   is applied via `apply_review_actions`. The mapper is rebuilt after
   actions.
2. **Edits validated.** `validate_edits` runs across all `ModifyText`
   instances. If any error, **raises `BatchValidationError`** — no edits
   apply.
3. **Edits applied.** Each `ModifyText` is applied via `apply_edits`.
   Applies survive individual failures (an edit that can't be located
   is reported in `edits_skipped`, not raised).

**Return shape:**
```python
{
    "actions_applied": int,
    "actions_skipped": int,
    "edits_applied":   int,
    "edits_skipped":   int,
}
```

**Raises:**
- `BatchValidationError` if any edit's `target_text` is unmatched or
  ambiguous. `e.errors` is a `list[str]`; `str(e)` is `"Batch validation failed"`.
- Does NOT raise for overlapping edits — those are skipped with a log
  warning. Does NOT raise for nonexistent accept/reject IDs — those
  increment `actions_skipped`.

#### `validate_edits(edits: List[ModifyText]) -> List[str]`

Dry-run validation without applying. Returns a list of error strings —
empty list means the batch is safe to apply. Skips validation for edits
with empty `target_text` (they're "pure insertions" in the engine's
internal vocabulary, though §3 notes this path isn't reachable from the
public SDK in the way the 10A note implied).

Error messages look like:
- `"- Edit 1 Failed: Target text not found in document:\n  \"<target>\""`
- `"- Edit 1 Failed: Ambiguous match. Target text appears N times. Occurrences found at:\n    1. \"...[match]...\"\n  Please provide more surrounding context..."`

#### `apply_edits(edits: List[ModifyText]) -> tuple[int, int]`

Returns `(applied, skipped)`. Applies edits without re-running
validation. Internal two-stage dispatch:
1. Indexed edits first (edits carrying `_match_start_index`), in
   **reverse position order** to avoid index shift. Overlap with
   previously-applied edits causes a skip.
2. Heuristic edits second, sorted by `len(target_text)` descending
   (longer first). Each heuristic call rebuilds the mapper.

Heuristic routing (`_apply_single_edit_heuristic`, `engine.py:707-774`):
- Empty `target_text` → logs `"Skipping heuristic edit: target_text is empty."` and returns False. **This is the path that rejects pure insertions** (see Sprint 10B finding #1).
- `new_text` identical to matched doc text → returns True (no-op).
- `new_text.startswith(matched_doc_text)` → synthesised as INSERTION; the
  suffix becomes the inserted text. **This is the documented pure-insertion
  idiom** (prefix-match).
- Otherwise → `trim_common_context` collapses common prefix/suffix into
  unchanged anchors; the remaining diff becomes an INSERTION, DELETION, or
  MODIFICATION depending on what's left.

#### `apply_review_actions(actions) -> tuple[int, int]`

Returns `(applied, skipped)`. Applies each `AcceptChange`/`RejectChange`/
`ReplyComment` in list order.

- `target_id` may start with `"Chg:"` or `"Com:"`. Strings without a
  prefix are treated as both-change-and-comment candidates.
- `_get_paired_nodes` groups contiguous `w:ins`/`w:del` blocks **by
  author**. So accepting `Chg:1` atomically accepts its paired `Chg:2`
  if both carry the same `w:author`.
- **Quirk (contradicts 10A finding #6).** The author scope is only used
  for *pairing*. The primary node (the `w:ins` or `w:del` with the given
  `w:id`) is found regardless of author. So a non-owning author CAN
  accept or reject another party's changes by id. Confirmed by
  `test_reject_foreign_author_change`. Oscar's audit trail is NOT
  structurally protected — a counterparty that knows the id can cancel
  Oscar's edits. Relevant for sprint 10D's prompt: do not assume the API
  gates cross-author edits.
- `resolved_history` tracks ids already handled in this batch, so paired
  resolutions don't double-count.
- At the end of the batch, if any action was applied, calls
  `normalize_docx` again.

#### `save_to_stream() -> BytesIO`

Serialises the current state to bytes. Returns a `BytesIO` at position 0
(first 4 bytes are the zip magic `PK\x03\x04`), ready for
`.getvalue()` or `.read()`. Confirmed by `test_save_to_stream_seek_zero`.

#### `accept_all_revisions() -> None`

Bulk accept. Walks every `w:ins` and `w:del` in the document, resolves
them atomically, and **additionally purges every comment** from the
four comment XML parts. This is more destructive than the Word UI's
"Accept All" — in Word, "Accept All" keeps comments; Adeu's helper strips
them too. Useful for final-export sanitisation; not appropriate for
delivering a redline to a counterparty. (See also `adeu.sanitize` — §10.)

#### Low-level public methods

These are public on the engine but not on `adeu.__all__`. Prior art
(Claude-Plugin-MCP) used them. 10A flagged that Oscar should prefer the
public SDK surface.

- `track_insert(text, anchor_run=None, comment=None, suppress_inherited=False)`
  — direct insertion via an anchor `Run`. With no anchor, returns a
  detached `w:ins` element. Handles Markdown headers (`# Title`
  produces a new paragraph with `pStyle="Heading1"`) and inline
  Markdown (`**bold**`, `_italic_`).
- `track_delete_run(run: Run) -> Optional[w:del_element]` — wraps a
  `python-docx.Run` in `w:del`. Handles nested `w:ins` correctly by
  splitting the surrounding insertion.
- `_scan_existing_ids` (name-mangled-ish; NOT public) — internal.

### 2.3 Internal attributes worth knowing

- `engine.doc` — the live `python-docx.Document`. Mutations are visible.
- `engine.mapper` — `DocumentMapper` on the Raw view.
- `engine.clean_mapper` — lazily constructed on the Clean view; reached
  when a heuristic match fails on the Raw view and falls back to Clean.
- `engine.comments_manager` — `CommentsManager` with the four parts.
- `engine.current_id` — integer, starts at `max existing w:id` and
  increments with `_get_next_id()`.
- `engine.timestamp` — the timestamp on all emitted changes this session.
- `engine.author` — literal string, used as the default for all
  `w:author` attributes this engine stamps.

---

## 3. `ModifyText`

**Import:** `from adeu import ModifyText`
**Source:** `adeu/models.py:16-49`

Pydantic `BaseModel`. The edit primitive.

### 3.1 Signature

```python
class ModifyText(BaseModel):
    type: Literal["modify"] = "modify"
    target_text: str           # required, non-None
    new_text: str              # required, non-None (may be "")
    comment: Optional[str] = None
```

**Pydantic-level constraints:**
- `target_text=None` → `ValidationError` (`test_pydantic_rejects_none_target`).
- `new_text=None` → `ValidationError` (same shape — required `str`).
- `comment=None` accepted (default).
- `type` defaults to `"modify"`; overriding it silently makes the discriminated union pick a different branch — don't.

### 3.2 What the engine does with ModifyText

Routing runs through `_apply_single_edit_heuristic` (`engine.py:707-774`).
Four paths, distinguished by what `new_text` looks like relative to the
matched document text:

1. **No-op.** `new_text == matched_doc_text` → engine returns True, no
   OOXML emitted. The "same-text" edit is silently collapsed.
2. **Pure insertion.** `new_text.startswith(matched_doc_text)` → engine
   synthesises an INSERTION: anchor is the end of the matched text, and
   `new_text[len(matched):]` becomes the inserted string. **One `w:ins`,
   zero `w:del`, one change id.** This is the documented pure-insertion
   idiom. (Battery: `test_insertion_prefix_match_basic`, `test_insertion_short_overlap`, `test_insertion_long_overlap`.)
3. **Pure deletion.** `new_text == ""` and `target_text` non-empty →
   engine emits one or more `w:del` (one per affected run). No `w:ins`.
   **Quirk.** Comments attached to pure deletions (`ModifyText(..., new_text="", comment="...")`) are **silently dropped** — the DELETION code path at `engine.py:862-864` never calls `_attach_comment`. See `test_comment_on_pure_deletion`.
4. **Modification.** Anything else → `trim_common_context` pulls out the
   common prefix/suffix (word-boundary-aware, markdown-aware), and the
   remaining diff becomes a `w:del` + `w:ins` pair. Each affected run
   inside the target span becomes its own `w:del`; a single `w:ins`
   holds the replacement. **Two change ids per logical modification.**

### 3.3 Input constraints on `target_text`

- **Empty string.** `validate_edits` skips empty-target edits (treats
  them as "pure index-based insertions"). But `apply_edits` rejects them
  at the heuristic path with `"Skipping heuristic edit: target_text is empty."`. **So empty
  `target_text` is silently skipped — `edits_applied += 0`, `edits_skipped += 1`, no exception.** (`test_insertion_empty_target_rejected`.)
- **Must match exactly one span.** Zero matches or two-or-more matches
  → `BatchValidationError` with `"Target text not found"` or `"Ambiguous match"`.
- **Matching strategies in order** (`DocumentMapper.find_match_index`):
  1. Exact substring match on Raw view.
  2. Smart-quote normalisation (`’` → `'`, `“` → `"`).
  3. Stripped-markdown match (strips `**bold**`, `_italic_`, `# headers` from target).
  4. Fuzzy regex match (allows variable whitespace, optional markdown
     markers, structural noise like bullets/numbering).
  5. If all fail on Raw view, fall back to Clean view.
- **Fuzzy regex matches `\n\n` as `\s+`.** **Quirk.** A target spanning
  paragraph boundaries (e.g. `"First paragraph. Second"` across `\n\n`)
  can succeed via fuzzy fallback. The engine will happily apply such a
  cross-paragraph modification. (`test_span_crossing_paragraph_boundary`.)
  New finding; not in 10A/10B.
- **CriticMarkup in target.** The docstring says `"You can include CriticMarkup {==...==} in the target to match text inside existing markup."` This is documented but hard to reach from a clean doc (the battery's `test_critic_markup_in_target_text` confirms it doesn't round-trip obviously).

### 3.4 Behaviour for `new_text`

- **Markdown interpreted.** Leading `# ` / `## ` / `### ` produces a new
  paragraph with `pStyle="HeadingN"`. Inline `**bold**` and `_italic_`
  produce `w:b` / `w:i` runs. `test_markdown_header_in_new_text`, `test_markdown_bold_italic_in_new_text`.
- **Newlines split into paragraphs.** `new_text` containing `\n` splits
  into multiple `w:p` elements, each wrapped in its own `w:ins`.
- **No `{++...++}` syntax.** The docstring warns: "Do NOT try to
  manually write {++...++} tags; the engine handles tracking." Writing
  them will match them literally.
- **Inherited formatting suppressed on modifications.** When the engine
  emits the replacement run, it calls `_apply_run_props(..., suppress_inherited=True)`
  if the original `new_text` had no markdown markers. That zeroes bold
  and italic (`<w:b w:val="0"/><w:i w:val="0"/>`) to prevent the target
  run's styling from leaking into the replacement. Confirmed by
  `test_modify_inside_bold_run`.

### 3.5 `trim_common_context` — how spans narrow

`adeu/diff.py:12-172`. This is the function that makes full-sentence
modifications emit only the *differing* words in `w:del`/`w:ins`, rather
than deleting the whole sentence. The narrowing is:
- **Word-boundary aware.** Prefix/suffix are backed off to whitespace
  boundaries. So `"English law" → "the laws of New York"` on the span
  `"This Agreement shall be governed by English law."` narrows to
  exactly `"English law"` / `"the laws of New York"`, and the common
  prefix `"This Agreement shall be governed by "` never appears in the
  redline.
- **Markdown-aware.** Backs off to avoid splitting `**`, `__`, `_`, `#`
  markers.
- **Absorbs balanced wrappers.** If both sides start and end with the
  same marker pair, the marker is pulled into the unchanged prefix/suffix.

Sprint 10B expected the engine to redline the entire matched span. It
does not — `trim_common_context` is a **lawyer-shape feature, not a
bug**. It's what makes an LLM's "rewrite the full sentence with one word
changed" produce a reasonable redline. Confirmed by `test_span_full_sentence` and `test_span_full_paragraph`.

### 3.6 Output shape on OOXML (by op)

All `w:ins` and `w:del` carry `w:author`, `w:id`, `w:date`, `w16du:dateUtc`.

| Op | `w:ins` count | `w:del` count | IDs emitted | Notes |
|----|---------------|---------------|-------------|-------|
| Modification (1 affected run) | 1 | 1 | 2 | First id on `w:del`, next on `w:ins` |
| Modification (N affected runs, e.g. across formatting) | 1 | N | N+1 | One del per target run; one ins total |
| Pure insertion (prefix-match) | 1 | 0 | 1 | |
| Pure deletion (`new_text=""`) | 0 | ≥1 (one per affected run) | ≥1 | Comments silently dropped |
| No-op (`new_text` == matched doc text) | 0 | 0 | 0 | edits_applied += 1 but nothing emitted |
| Header insertion (`# Title` in new_text) | ≥1 (one per new paragraph) | 0 or 1 (if modification) | varies | New `w:p` with `pStyle`; previous anchor para's `pPr` copied when inheriting |

### 3.7 Overlap / composition

- Non-overlapping edits compose. `test_multi_edit_non_overlapping`.
- Overlapping edits: engine tracks `occupied_ranges`; the second
  overlapping edit is **skipped with a log warning** (`"Skipping overlapping edit at index N"`). No exception. Result: `edits_skipped += 1`. `test_multi_edit_same_location_conflict`.
- Duplicate edits (same target span appearing twice in the doc text)
  surface at validation as ambiguous and raise `BatchValidationError`.
  `test_multi_edit_identical_skipped`.

---

## 4. `AcceptChange`

**Import:** `from adeu import AcceptChange`
**Source:** `adeu/models.py:52-55`

```python
class AcceptChange(BaseModel):
    type: Literal["accept"] = "accept"
    target_id: str              # required; "Chg:N" form, or bare "N"
    comment: Optional[str] = None
```

### 4.1 Behaviour (`engine._accept_change`, `engine.py:1067-1102`)

- Finds `w:ins` + `w:del` elements whose `w:id` == `target_id` (strip
  `Chg:` prefix first).
- Calls `_get_paired_nodes` to pull in adjacent same-author ins/del that
  form one logical modification.
- **Commits each `w:ins` child-by-child into its parent** (the
  replacement becomes permanent).
- **Removes each `w:del`** (the original is dropped).
- Cleans up any comment anchors that tightly wrapped the resolved nodes.

### 4.2 Behaviour quirks

- **Accepting `Chg:1` or `Chg:2` on a modification pair produces the
  same result.** The engine pairs them via `_get_paired_nodes`, so
  either id resolves both. `test_accept_by_second_id_of_pair`.
- **Nonexistent id → `actions_skipped += 1`, no raise.**
- **`AcceptChange` as part of `process_batch` runs before edits** in the
  same batch; the mapper is rebuilt after actions. So accepting then
  modifying is safe. `test_batch_mixes_edits_and_actions`.
- **`comment` field is set to None in the model but is NOT WRITTEN anywhere.** Reading `_accept_change` (`engine.py:1067-1102`) shows no path that reads `act.comment`. **Quirk.** The field exists (matches `ReplyComment`'s shape) but has no effect.

---

## 5. `RejectChange`

**Import:** `from adeu import RejectChange`
**Source:** `adeu/models.py:58-61`

```python
class RejectChange(BaseModel):
    type: Literal["reject"] = "reject"
    target_id: str              # required; "Chg:N" form, or bare "N"
    comment: Optional[str] = None
```

### 5.1 Behaviour (`engine._reject_change`, `engine.py:1104-1141`)

- Finds `w:ins` + `w:del` matching `target_id`.
- `_get_paired_nodes` pairs same-author siblings.
- **Removes each `w:ins`** (the proposed insertion is dropped).
- **Converts each `w:delText` in the `w:del` back to `w:t`** and commits
  it to the parent (the original text is restored).

### 5.2 Behaviour quirks

- **Non-owning author can reject.** As documented in §2.2.
  `test_reject_foreign_author_change`. **New finding extending 10A #6.**
  The prompt layer cannot rely on Adeu to structurally protect Oscar's
  or the counterparty's edits from cross-author rejection.
- **Rejecting text that was never tracked is a no-op** — no
  `Chg:N` id exists. `test_reject_non_tracked_text_unreachable`.
  This is Sprint 10A's "`RejectChange` can't delete counterparty
  untracked text" observation, re-confirmed.
- **`comment` field is not written.** Same as `AcceptChange`.

---

## 6. `ReplyComment`

**Import:** `from adeu import ReplyComment`
**Source:** `adeu/models.py:64-67`

```python
class ReplyComment(BaseModel):
    type: Literal["reply"] = "reply"
    target_id: str              # required; "Com:N" form, or bare "N"
    text: str                   # required
```

### 6.1 Behaviour (`engine._reply_to_comment`, `engine.py:1143-1192`)

- Adds a new `w:comment` to `word/comments1.xml` via
  `comments_manager.add_comment(author, text, parent_id=target_id)`.
- Attempts to locate the parent comment's `w:commentRangeStart` /
  `w:commentRangeEnd` / `w:commentReference` in the body and anchor the
  reply beside them.

### 6.2 Behaviour quirks

- **Reply to a nonexistent `Com:N` silently adds a stray comment.**
  `comments_manager.add_comment` succeeds; the body anchor lookup logs
  `"Parent comment start not found during reply"` at WARNING and returns.
  The new `w:comment` is present in `word/comments1.xml` but has no
  body range. `test_comment_on_nonexistent_target`. **New quirk; relevant for Sprint 10D.**
- **Threading is via `commentsExtended1.xml`.** Modern Word uses
  `w15:paraIdParent` on a `w15:commentEx` entry. Legacy Word used
  `w15:p` on `w:comment` itself. Adeu emits the modern form; legacy is
  only used if `extended_part` is absent (which it isn't in practice,
  since `CommentsManager` creates it eagerly).
- **Initials.** Author "Oscar" → initials "O"; "Someone Withname"
  → initials "SW". Deterministic from whitespace-split first letters.

---

## 7. `DocumentChange`

**Import:** `from adeu import DocumentChange`
**Source:** `adeu/models.py:70`

```python
DocumentChange = Annotated[
    Union[AcceptChange, RejectChange, ReplyComment, ModifyText],
    Field(discriminator="type"),
]
```

A discriminated Pydantic union. Not a class — a type alias. Usage: the
signature of `process_batch` takes `List[DocumentChange]`, which accepts
any of the four concrete types in any order.

Sprint 10A risk R5 flagged that LangChain tool-binding for discriminated
unions is quirky. If the Sprint 10D tool schema needs to expose the
union, prefer `ModifyText` directly and use the other three via separate
tools — don't bind the union.

---

## 8. `extract_text_from_stream`

**Import:** `from adeu import extract_text_from_stream`
**Source:** `adeu/ingest.py:24-55`

```python
def extract_text_from_stream(
    file_stream: BytesIO,
    filename: str = "document.docx",
    clean_view: bool = False,
) -> str: ...
```

### 8.1 Behaviour

- **Opens the stream via `python-docx.Document`, walks every part
  (headers → body → footers), emits text with CriticMarkup annotations.**
- **`clean_view=False` (default — Raw view).** Emits
  CriticMarkup-annotated text:
  - Insertions: `{++text++}`
  - Deletions: `{--text--}`
  - Comments: `{==text==}`
  - Paragraph separator: `"\n\n"`
  - Metadata blocks: `{>>[Chg:N] Author\n[Com:M] Author @ YYYY-MM-DD: text<<}`
    appear after each run of redline state changes.
- **`clean_view=True`.** Simulates "Accept All Changes": deletions are
  hidden, insertions are unwrapped, comments are stripped. Returned text
  equals what the document would read as if every tracked change were
  accepted. `test_extract_clean_view_after_modify`, `test_clean_view_round_trip_three_edits`.

### 8.2 Error paths

- Invalid bytes → `ValueError("Could not extract text: File is not a zip file")`. `test_extract_invalid_docx_bytes`.

### 8.3 Known shape details

- Raw-view Critic block ordering: **changes first, then comments**.
  Inside the metadata block, change ids are listed in source order;
  comments are sorted by id and rendered threaded (reply chains
  recursive).
- Comment metadata includes `@ YYYY-MM-DD` and `(RESOLVED)` if applicable.
- CriticMarkup insertions use `{++...++}`; the trailing space between an
  anchor and a prefix-match insertion ends up *inside* the `{++...++}`
  block. Observed: `"Clause B.{++ Clause C.++}{>>[Chg:1] Oscar<<}"`.

---

## 9. `apply_edits_to_markdown`

**Import:** `from adeu import apply_edits_to_markdown`
**Source:** `adeu/markup.py:365-453`

```python
def apply_edits_to_markdown(
    markdown_text: str,
    edits: List[ModifyText],
    include_index: bool = False,
    highlight_only: bool = False,
) -> str: ...
```

### 9.1 Behaviour

Applies `ModifyText` edits to a plaintext / Markdown string and returns
a CriticMarkup-annotated string. Does NOT touch any `.docx` — pure
text-level transform. Independent codepath from the engine (does not
share the mapper); the matching logic is a simpler variant in
`_find_match_in_text`.

### 9.2 Differences from `RedlineEngine`

- **Pure insertions NOT supported.** Empty `target_text` in text mode
  logs `"Skipping edit N: pure insertion without target_text not supported in text mode"` and skips. No prefix-match shortcut in markdown mode. Unlike the engine. `test_apply_edits_to_markdown_empty_target_skipped`.
- **Unmatched target skipped with a warning; no exception.** `test_apply_edits_to_markdown_unfound_skipped`.
- **Overlaps skipped with a warning.**
- **No multi-run / formatting awareness** — operates on a plain string.
- **Highlight mode.** `highlight_only=True` emits `{==text==}` for the
  target text and ignores `new_text`. Useful for "tag but don't change".
- **Include index.** `include_index=True` adds `[Edit:N]` to the
  metadata block.

### 9.3 Shape of output

| Edit kind | Output fragment |
|-----------|-----------------|
| Modification | `{--target--}{++new++}` |
| Deletion (`new_text=""`) | `{--target--}` |
| No-op | anchor unchanged |
| With `comment` | append `{>>comment<<}` |
| With `include_index=True` and `comment` | append `{>>comment [Edit:N]<<}` |
| `highlight_only=True` | `{==target==}` |

---

## 10. `adeu.sanitize` (separate public submodule)

**Import:** `from adeu.sanitize import sanitize_docx, SanitizeResult, SanitizeMode`
**Source:** `adeu/sanitize/core.py`

Not listed in `adeu.__all__`, but imported-by-name is part of the public
surface. Used for final-export clean-up (strip metadata, accept/resolve
changes, produce audit report). Not needed for redlining; documented
here for completeness.

### 10.1 Signature

```python
def sanitize_docx(
    input_path: str,
    output_path: Optional[str] = None,
    *,
    keep_markup: bool = False,
    baseline_path: Optional[str] = None,
    author: Optional[str] = None,
    accept_all: bool = False,
) -> SanitizeResult: ...
```

### 10.2 Modes

| Mode | How selected | Behaviour |
|------|--------------|-----------|
| `FULL` | default | Accept all track changes, remove all comments, strip metadata. Blocks (raises `SanitizeError`) if unresolved changes exist and `accept_all` is False. |
| `KEEP_MARKUP` | `keep_markup=True` | Keep open tracked changes and comments; strip only metadata. |
| `BASELINE` | `baseline_path=<path>` | Recompute the delta against a baseline doc (word-level diff) and emit tracked changes relative to baseline. |

### 10.3 Output — `SanitizeResult`

Dataclass with fields: `output_path`, `status` ("clean" / "clean_with_warnings" / "blocked"), `tracked_changes_found`, `tracked_changes_accepted`, `comments_removed`, `comments_kept`, `metadata_stripped`, `warnings`, `report_text`.

### 10.4 Error paths

- Missing input or baseline file → `FileNotFoundError`.
- Full mode with unresolved changes and `accept_all=False` → `SanitizeError` (source: `adeu/sanitize/core.py:48-51`).

---

## 11. Errors & Exception Types

| Exception | Raised by | Shape |
|-----------|-----------|-------|
| `BatchValidationError` (from `adeu.redline.engine`) | `process_batch` when any edit's target is unmatched or ambiguous | `e.args[0] == "Batch validation failed"`; `e.errors: list[str]` |
| `ValueError` | `extract_text_from_stream` on non-zip input | `f"Could not extract text: {reason}"` |
| `pydantic.ValidationError` | `ModifyText(...)` / `AcceptChange(...)` / etc. with missing required fields or wrong types | Standard Pydantic error surface |
| `zipfile.BadZipFile` | `RedlineEngine(io.BytesIO(b'not a zip'))` (via python-docx) | `"File is not a zip file"` |
| `SanitizeError` (from `adeu.sanitize.core`) | `sanitize_docx` full mode with unresolved changes | Report text in `str(e)` |
| `FileNotFoundError` | `sanitize_docx` on missing input/baseline path | Standard stdlib |

**Not raised** — skip paths that log warnings instead:
- Empty `target_text` → skip.
- Overlapping edit → skip.
- Nonexistent `target_id` on Accept/Reject → skip.
- Reply to nonexistent `Com:N` → warn but SUCCEED (adds stray comment).
- Unmatched target in `apply_edits_to_markdown` → skip.

---

## 12. Logging

Adeu uses `structlog` internally. Default output goes to stderr at INFO
level and above. Observed log streams during the battery:

- `adeu.utils.docx`: `"Normalizing DOCX structure..."` (INFO) on every engine init.
- `adeu.redline.comments`: `"Initializing CommentsManager"`,
  `"Creating new comments part"`, `"Found existing part by content type"` (INFO/DEBUG).
- `adeu.redline.engine`: `"Applying Edit at [A:B] Op=X"` (DEBUG), `"Skipping overlapping edit..."` / `"Skipping heuristic edit: target_text is empty."` / `"Parent comment start not found during reply"` (WARNING).
- `adeu.markup`: `"Skipping edit N: pure insertion without target_text not supported in text mode"` / `"Skipping edit N: target_text not found"` (WARNING).

**To silence in an agent trace** (Sprint 10B open follow-up), route
structlog through stdlib logging and raise the level to WARNING:

```python
import logging, structlog
logging.basicConfig(level=logging.WARNING)
structlog.configure(
    processors=[structlog.stdlib.filter_by_level, structlog.stdlib.add_log_level,
                structlog.dev.ConsoleRenderer(colors=False)],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
for name in ("adeu", "adeu.redline.engine", "adeu.redline.mapper",
             "adeu.redline.comments", "adeu.ingest", "adeu.markup",
             "adeu.utils.docx"):
    logging.getLogger(name).setLevel(logging.WARNING)
```

This is what `harness.py` in the battery does. Observed to work.

---

## 13. Invariants worth relying on

- `RedlineEngine` with no edits or actions still produces a valid
  `.docx` (21 parts, including the four comment parts).
- Every `w:ins` / `w:del` has `w:author`, `w:id`, `w:date`, `w16du:dateUtc`.
- `w:id` values are globally unique across the document body within a
  given engine's session and across restarts (because of `_scan_existing_ids`).
- `save_to_stream()` is repeatable — calling it twice returns two
  separate `BytesIO`s each at position 0, both equivalent.
- `extract_text_from_stream(..., clean_view=True)` is idempotent with
  `accept_all_revisions()` + `extract_text_from_stream(...)` — same
  text comes out. `test_clean_view_round_trip_three_edits`.
- `normalize_docx` is called at engine construction AND at end of
  `apply_review_actions` if any action applied. So the mapper and the
  document stay in sync after review operations.

---

## 14. Invariants worth NOT relying on

- `RejectChange` does NOT structurally prevent non-owning authors from
  rejecting your edits. Not a safeguard.
- `comment` field on `AcceptChange` / `RejectChange` is accepted by
  Pydantic but never written anywhere.
- Empty `author=""` persists as `w:author=""`; engine does NOT coerce.
- `track_insert` with no anchor returns a detached element — caller
  must insert. Not a high-level helper.
- `apply_edits_to_markdown` is NOT equivalent to what the engine emits —
  different matching strategy, no pure-insertion support.
- The SDK's public surface includes FastMCP in the dep tree, but SDK
  callers never invoke it. Don't confuse MCP server code (in
  `adeu/server.py` and `adeu/mcp_components/`) with the SDK.

---

## 15. Cross-references to earlier sprint findings

| Claim in 10A/10B | This sprint's evidence | Status |
|------------------|------------------------|--------|
| 10A §1.3 "empty target_text = pure insertion" | `test_insertion_empty_target_rejected` — the heuristic path rejects empty targets | **Refuted.** Use prefix-match instead. 10B already noted this. |
| 10A finding #6: "RejectChange only cancels your own prior edits" | `test_reject_foreign_author_change` — Counterparty successfully rejected Oscar's Chg:1 | **Qualified.** Author scope is only for *pairing*, not for primary node access. Prompt discipline must not assume the API gates this. |
| 10B surprise #1: prefix-match is the pure-insertion idiom | confirmed across three different overlap lengths | **Confirmed.** |
| 10B surprise #2: two change IDs per modification | `test_modification_emits_paired_ids` + N-run formatted case gives N+1 | **Confirmed, extended.** |
| 10B surprise #3: CommentsManager creates 4 parts eagerly | `test_comments_parts_eagerly_created` | **Confirmed.** |
| 10B surprise #4: structlog writes to stderr at INFO | silenced via structlog stdlib routing in the harness | **Confirmed + mitigation proven.** |
| 10B surprise #5: edits sort reverse position | implicit in `test_multi_edit_non_overlapping` | **Confirmed.** |

---

## 16. Findings new to this sprint (not in 10A/10B)

1. **Fuzzy regex matches `\n\n` as `\s+`** — targets can span paragraph
   boundaries if unambiguous. `test_span_crossing_paragraph_boundary`.
2. **`trim_common_context` narrows full-sentence edits** to the word-level
   diff. `test_span_full_sentence`. This is the mechanism that makes
   lawyer-shape output achievable without prompt-level engineering.
3. **Comments on pure deletions are silently dropped.**
   `test_comment_on_pure_deletion`. Prompt discipline is needed.
4. **`ReplyComment` on missing parent silently adds a stray comment.**
   `test_comment_on_nonexistent_target`.
5. **Non-owning author can accept/reject by id** (qualifies 10A #6).
   `test_reject_foreign_author_change`.
6. **`comment` field on `AcceptChange`/`RejectChange` is ignored.**
7. **Empty `author=""` persists verbatim**, not coerced.
8. **`apply_edits_to_markdown` does NOT support pure insertions** — no
   prefix-match shortcut in markdown mode.
9. **`accept_all_revisions` purges comments too**, not just track changes.
10. **Markdown in `new_text` generates true OOXML formatting** (bold, italic, headers), not CriticMarkup placeholders. `test_markdown_header_in_new_text`, `test_markdown_bold_italic_in_new_text`.
