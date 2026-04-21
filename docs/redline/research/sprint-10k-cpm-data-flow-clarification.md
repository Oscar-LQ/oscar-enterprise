# Sprint 10K — CPM data-flow clarification

## Purpose

Arturs's direct description of Claude-Plugin-MCP's (CPM) data flow —
*"The LLM is expected to send back the amended text. The code does the
rest."* — contradicts Sprint 10K's pre-implementation research note
`sprint-10k-claude-plugin-mcp-port.md` §2, which says CPM "computes a
word-level diff BETWEEN each edit's `target_text` and `new_text` (not
document-level)." This note resolves the contradiction by reading the
CPM source directly and reporting what the code does. Sprint 10L's
design depends on the answer; 10L is not drafted until this is
settled.

## Files read

All paths relative to `/sandbox/reference-material/claude-plugin-mcp/`.

- `src/pipeline/word_diff.py` (full)
- `src/pipeline/surgical_edit.py` (full)
- `src/pipeline/first_pass.py` (full)
- `src/mcp_server/redline_tool.py` (full)
- `src/pipeline/surgical_helpers.py` (lines 40–69 — `find_match_three_layer`)
- `skills/negotiate-contract/SKILL.md` (lines 640–714 — Step D, D1, E, F)

## Finding 1 — `word_diff.diff_words` signature

`src/pipeline/word_diff.py:27–41`:

```python
def diff_words(
    old_text: str,
    new_text: str,
) -> list[tuple[int, str]]:
    """Produce word-level diff segments between old_text and new_text.
    ...
    Returns a list of (op, text) tuples where:
        op = -1: DELETE (text present in old, absent in new)
        op =  0: EQUAL  (text unchanged)
        op =  1: INSERT (text absent in old, present in new)
    """
```

Two plain-string inputs named `old_text` and `new_text`. Returns a
list of word-level `(op, text)` segments. The docstring's own example
(lines 15–17) calls it as `diff_words("within thirty days", "within
fourteen days")` — a short on-disk phrase vs a short replacement, both
plain strings. The signature does not name `target_text`; the symbol
`target_text` does not appear in this file.

## Finding 2 — how `diff_words` is called and what's passed

Sole call site: `src/pipeline/surgical_edit.py:143`, inside
`_apply_surgical_diff`:

```python
143:    diffs = diff_words(runs_plain_text, clean_new_text)
```

The two arguments are constructed above:

```python
134:    runs_plain_text = "".join(run.text or "" for run in target_runs)
135:    clean_new_text = strip_formatting_markers(new_text)
...
138:    clean_new_text = strip_redundant_clause_number(clean_new_text, parent_p)
```

Where `target_runs` is resolved by the three-layer matcher
(`surgical_edit.py:101–107`):

```python
101:    mapper, start_idx, match_len = find_match_three_layer(
102:        engine, target_text,
103:    )
...
107:    target_runs = mapper.find_target_runs_by_index(start_idx, match_len)
```

And `find_match_three_layer` (`src/pipeline/surgical_helpers.py:40–69`)
returns `(active_mapper, start_idx, match_len)` — i.e. it uses
`target_text` as a query string into a `DocumentMapper` / `PlainTextIndex`
and returns *indices into the document's own text*. No text from the
LLM is copied into `runs_plain_text`.

Answering the sub-questions explicitly:

- **Is one of the inputs the on-disk document's text content?** Yes —
  `runs_plain_text` is the concatenated `.text` of the OOXML runs that
  cover the match span `[start_idx, start_idx + match_len)` in the
  live document. It is derived from the document, not from the LLM
  reply.
- **Is one of the inputs the LLM's reply (or a field from it)?** Yes —
  `clean_new_text` is `edit.new_text` (cleaned by
  `strip_formatting_markers` and `strip_redundant_clause_number`).
- **Is the diff between (a) two LLM-supplied strings, (b) one
  LLM-supplied + one on-disk, or (c) something else?** **(b).** The
  on-disk side comes from `target_runs`; the LLM side is
  `edit.new_text`. `edit.target_text` is used only upstream as a
  *locator* for the three-layer matcher — it does not participate in
  the diff.

## Finding 3 — MCP tool input schema

`src/mcp_server/redline_tool.py:32–50`:

```python
32:def redline_document(
33:    input_path: str,
34:    output_path: str,
35:    edits: list[dict[str, str | None]],
36:    author_name: str,
37:) -> str:
...
45:    Each edit dict has:
46:      - target_text: The exact text to find in the document.
47:      - new_text: Replacement text ("" for pure deletion; None is
48:        also accepted and coerced to "" for backward compatibility).
49:      - comment: Optional rationale text attached as a Word comment,
50:        or None for no comment.
```

And the SKILL.md-side contract that Claude sees (`SKILL.md:642–646`,
Step D):

```
For each clause needing changes, create an edit dict with:
- `target_text`: the exact text from the document to find and replace
- `new_text`: the replacement text (or `""` for a pure deletion)
- `comment`: `None` for most edits. ...
```

Step D1 (`SKILL.md:648–667`) then teaches *target-text sizing*:

```
**Target the minimum changed span.** ... set target_text to a phrase
containing just that word plus enough surrounding context for unique
matching (usually 5-15 words). Do not set target_text to the entire
paragraph or sentence.

**Do not rewrite what you are not changing.** ... Do not delete and
rewrite the whole clause.
...
**Keep target_text as short as uniquely matchable.** ... A phrase of
5-15 words is usually right.
```

So the LLM is asked to provide a list of `{target_text, new_text,
comment}` dicts, **not** a single amended clause/document draft.
Decomposition (how many edits, where each `target_text` anchors) is
the LLM's job. `target_text` is narrow-by-instruction (5–15 words);
`new_text` is the replacement for the region `target_text` locates.

## Finding 4 — end-to-end data flow

From "LLM completes its reply" to "OOXML edit applied":

1. **LLM emits** a JSON payload `{"edits": [{target_text, new_text,
   comment}, ...]}` under Step D/D1 discipline. Data contract:
   three string-or-null fields per edit.
2. **MCP tool parses** (`redline_tool.py:69–72`):
   ```python
   for edit_dict in edits:
       if edit_dict.get("new_text") is None:
           edit_dict["new_text"] = ""
   edit_models = [DocumentEdit(**e) for e in edits]
   ```
   List-of-dicts → list of Adeu `DocumentEdit` pydantic models.
3. **Pipeline entry** (`first_pass.py:71`):
   ```python
   applied, skipped = apply_edits_surgically(engine, edits)
   ```
   Edits are deduped and sorted by `len(target_text)` descending
   (`surgical_edit.py:68–73`), then iterated one at a time.
4. **Per-edit location lookup** (`surgical_edit.py:101–109`):
   `target_text` → `find_match_three_layer` → `(mapper, start_idx,
   match_len)` → `mapper.find_target_runs_by_index(start_idx,
   match_len)` → list of OOXML `Run` objects covering the match span.
   `target_text` exits the pipeline here — it is a locator only.
5. **Per-edit word diff** (`surgical_edit.py:134–143`):
   ```python
   runs_plain_text = "".join(run.text or "" for run in target_runs)
   clean_new_text = strip_formatting_markers(new_text)
   clean_new_text = strip_redundant_clause_number(clean_new_text, parent_p)
   ...
   diffs = diff_words(runs_plain_text, clean_new_text)
   ```
   Word-granularity `(op, text)` segments between **on-disk matched-run
   text** and **LLM's cleaned `new_text`**.
6. **OOXML element build + DOM surgery** (`surgical_edit.py:157–164`):
   `build_char_format_map` + `build_diff_elements` turn the diff
   segments into `<w:ins>`/`<w:del>` elements; `perform_dom_surgery`
   replaces the target runs with them. Reconstruction is
   verified before surgery (`word_diff.verify_reconstruction`,
   `surgical_edit.py:145`); mismatch → wholesale delegation.

## Classification

**(C).** The LLM provides edit dicts whose `target_text` is a
*locator* and whose `new_text` is an amended span for the located
region. `diff_match_patch` runs post-LLM-output, *inside* the matched
region, between **on-disk runs text** and **LLM's `new_text`**.

Not (A): (A) says the diff narrows "within each edit's text-pair"
meaning `target_text` vs `new_text`. The code does not do that — it
diffs `runs_plain_text` (from the document) vs `new_text`.
`target_text` is used by `DocumentMapper.find_match_index` upstream
and then discarded. `word_diff.py` imports no symbol called
`target_text` and the string `target_text` does not appear in
`word_diff.py` at all.

Not (B): (B) says the LLM supplies only amended text (a whole clause /
document) and the diff algorithm derives edit dicts. The code requires
structured edit dicts (`redline_tool.py:35`, `DocumentEdit(**e)` on
line 72); `target_text` is mandatory for anchoring. No mechanism in
`first_pass.py` or `surgical_edit.py` derives edits from a
whole-clause amended draft.

## Implication for the prior research note

The prior note (`sprint-10k-claude-plugin-mcp-port.md`) is *structurally*
right about CPM's pattern (one LLM call, edit-list data contract,
single-call per-edit-aware surgical wrapper, narrow `target_text`
discipline in Step D1) but *mechanically imprecise* about the diff's
inputs in two places:

- **§2 "Per-edit diff"** (lines 77–81):
  > "After the LLM replies, CPM's pipeline computes a word-level diff
  > BETWEEN each edit's `target_text` and `new_text` (not
  > document-level)."

  Correction: the diff is between **the on-disk document's text at
  the matched runs** (`runs_plain_text`) and the edit's `new_text` —
  not `target_text` vs `new_text`. In practice, when `target_text` is
  narrow and uniquely-matched (Step D1's 5–15 words), `runs_plain_text`
  closely tracks `target_text` modulo run boundaries, so the effective
  behaviour *looks like* target/new diffing. The mechanism is still
  document/new diffing.

- **§4 divergence table, "Diff scope" row**:
  > "CPM first-pass: Per-edit (target_text ↔ new_text)"

  Correction: "Per-edit (on-disk runs text at matched region ↔
  new_text)". Still per-edit, still not document-level; but one side
  is the document, not the LLM's `target_text`.

Arturs's description — *"the LLM is expected to send back the amended
text; the code does the rest"* — is accurate about the diff's mechanics
(the LLM-supplied side is `new_text`; the on-disk side comes from the
document, i.e. "the code does the rest" with respect to locating and
extracting the old text). It is loose about the LLM's output shape:
the LLM does still emit structured edit dicts with `target_text`
anchors, not a free-form amended clause. Both characterisations can
stand if read charitably: the prior note describes the data-contract
shape (what the LLM emits), Arturs's description describes the diff's
mechanics (which side of the diff the LLM owns). The imprecision
that needs correcting is specifically the *diff-input characterisation*
in §2 and §4 of the prior note.

## Implication for Sprint 10L

Sprint 10K's Outcome C is correctly located. MiniMax emitted one wide
edit (`target_text` = 29 words, `new_text` = 56 words); in CPM's
actual data flow, the code then diffed a ~29-word on-disk span against
a ~56-word `new_text` with little shared structure, so
`diff_match_patch` produced one wide delete + one wide insert. The
width failure is jointly a function of (i) LLM-side `target_text`
width and (ii) the extent of preserved prose between the matched
region and `new_text`. On frontier models the diff narrows
effectively *because* Opus-class models both pick narrow `target_text`
spans *and* produce `new_text` that conservatively preserves
unchanged phrasing from the matched region. On MiniMax the second
property (conservative rewriting) is the observed ceiling — even when
`target_text` is wide, a `new_text` that reproduces the unchanged
phrasing would let the diff narrow anyway. 10L's design question
becomes: can MiniMax's `new_text` be steered toward *phrase
preservation* (which the diff exploits) separately from
*`target_text` narrowing* (which the prompt teaches directly)? That is
a different axis from the sprints 10F–10K have probed and is the
substantive 10L choice. Design work for 10L should be drafted in a
separate session with this note as input.
