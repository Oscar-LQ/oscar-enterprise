# Adeu 1.1.0 — Idioms & Usage Patterns

> An intent-organised usage guide for Adeu 1.1.0's Python SDK. Companion
> to `adeu-api-reference.md` (which is organised by operation). This
> document is organised by what you're trying to DO.
>
> Every idiom here is backed by a passing test in
> `src/experiments/sprint-10c-adeu-reference/`. When Sprint 10D writes
> the redline-specialist's system prompt, it should quote from this
> document directly; the patterns are phrased to be copyable.
>
> **Read this instead of the engine source for most questions.** The
> engine is 1,219 lines of special cases; this document is the 1%
> that matters for driving it from a prompt.

---

## How to modify existing text

**Pattern.** Build a `ModifyText(target_text=<minimal span>, new_text=<replacement>)`. Pass a list of them to `process_batch`.

```python
from adeu import ModifyText, RedlineEngine

engine = RedlineEngine(io.BytesIO(docx_bytes), author="Oscar")
engine.process_batch([
    ModifyText(target_text="Delaware", new_text="New York"),
    ModifyText(target_text="one year", new_text="two years"),
])
out = engine.save_to_stream().getvalue()
```

### Span size guidance

There is NO internal length cap in Adeu. The engine applies edits at 1
word, 5 words, 15 words, a full sentence, or a full paragraph equally
well — the only constraint is that `target_text` must match exactly one
span.

**What does differ by span size: `trim_common_context` narrowing.** If
you submit a full-sentence edit where only one phrase changed, the
engine will automatically collapse the common prefix and suffix into
unchanged anchors. The redline ends up scoped to the word-level diff.
Example:

- `target_text` = `"This Agreement shall be governed by English law."`
- `new_text` = `"This Agreement shall be governed by the laws of the State of New York."`
- Actual redline emitted: `{--English law.--}{++the laws of the State of New York.++}`

The common prefix (`"This Agreement shall be governed by "`) never
appears in either block. This is the engine being lawyer-shape-friendly
(see `test_span_full_sentence`).

**Practical implication for prompting.** You don't need to laboriously
minimise the span before calling the tool. Submit the enclosing
sentence if that gives you cleaner context for matching; the engine
will narrow. That said, keep spans to **the minimum necessary for
unique match** — see "How to disambiguate ambiguous targets" below.

Prior-art guidance from Claude-Plugin-MCP (5–15 words per target)
remains a sensible upper bound for LLM ergonomics, but it isn't a
hard engine limit.

### Formatting boundaries

`target_text` CAN span formatting boundaries. If your target includes
text that is partly bold, partly plain, the engine emits one `w:del`
per affected run and a single consolidated `w:ins` for the replacement
(`test_modify_spanning_bold_boundary` — 2 `w:del`, 1 `w:ins`).

The replacement run has bold/italic explicitly **suppressed** via
`<w:b w:val="0"/>` unless your `new_text` uses Markdown (`**bold**`,
`_italic_`) to request it. That means modifying inside a bold phrase
produces **plain** replacement text by default.

If you want the replacement to stay bold:

```python
ModifyText(
    target_text="Confidential Information",  # currently bold in source
    new_text="**Proprietary Data**",         # emit as bold
)
```

---

## How to insert new text (pure insertion)

**The SDK does NOT accept `target_text=""`.** The `ModifyText` Pydantic
model allows it, but the engine's heuristic rejects it: it logs
`"Skipping heuristic edit: target_text is empty."` and increments
`edits_skipped`. No exception, no visible output.

**The idiom is prefix-match.** Pick an anchor (the exact text you want
to insert AFTER), and pass `new_text = anchor + " " + your_new_content`:

```python
ModifyText(
    target_text="signed by both parties.",
    new_text="signed by both parties. This Agreement constitutes the entire agreement between the parties.",
)
```

The engine detects `new_text.startswith(target_text)` (`engine.py:739-743`),
narrows the edit to the *suffix* only, and emits a single `w:ins` with
no paired `w:del`. One change id, no deletion, clean insertion.

### Anchor selection

The anchor must:

1. **Be unique in the document** (otherwise `BatchValidationError: Ambiguous match`).
2. **Appear exactly as in the source text** (case, whitespace, punctuation).
3. **Not collide with another edit's target range** — the engine skips
   overlapping edits silently.

Where possible, pick an anchor that ends with **punctuation**
(full stop, semicolon, comma) — it reads naturally and avoids
truncating mid-word.

### Overlap length

Any overlap length works. The battery confirmed:

- Short: `"survive termination."` (single clause)
- Long: a full 120-character sentence
- Punctuation-bounded: `"Clause C."`
- Full-clause: anchor is the whole last clause

All produce a single `w:ins` with zero `w:del`. Choose the shortest
anchor that's **still unique** in the document.

### Cross-paragraph insertion

To insert a new paragraph, include `\n` in `new_text`:

```python
ModifyText(
    target_text="Body.",
    new_text="Body.\n# Section Title\nSection body.",
)
```

- The `\n` splits into new `w:p` elements.
- A leading `# ` on a new line produces `pStyle="Heading1"`.
- `## `, `### `, etc. produce `Heading2`, `Heading3`, etc. up to level 9.
- Paragraphs without a header marker inherit the anchor paragraph's
  `pPr`.

### Insertion at start of document

Adeu's engine has a special case (`_apply_single_edit_indexed`, `engine.py:804-815`)
for `start_idx == 0` that inserts before the anchor. In practice,
the simplest pattern is to anchor on the first real sentence and put
your new content *after* it — i.e. use the prefix-match idiom against
sentence 1 rather than against the empty string.

---

## How to delete text

**Two options.**

### 1. ModifyText with `new_text=""`

```python
ModifyText(target_text=" Delete this entire clause.", new_text="")
```

The engine routes this through the DELETION path (`engine.py:862-864`):
each affected run becomes a `w:del`, no `w:ins` is emitted.

**Critical quirk: comments are silently dropped on pure deletions.**
If you pass `comment="..."` on a `new_text=""` edit, the engine emits
the `w:del` but does NOT attach the comment (`test_comment_on_pure_deletion`).
**To comment on a deletion, do one of:**

- Attach the comment to a **retained** anchor nearby via a separate edit.
- Replace `new_text=""` with `new_text=" "` (a single space) to route
  through MODIFICATION, which does attach comments. Downside: leaves a
  dangling insertion.
- Accept that comments on pure-deletion intents won't land; do not pass
  `comment` on those edits.

### 2. Let the modification route narrow it for you

If the "deletion" is part of a sentence-level rewrite, pass the full
sentence as `target_text` and the shortened version as `new_text`. The
`trim_common_context` narrowing will automatically make the `w:del`
exactly the removed words.

Example:
- `target_text`: `"The parties agree to resolve disputes through good-faith negotiation before litigation."`
- `new_text`:    `"The parties agree to resolve disputes before litigation."`
- Emitted: `{--through good-faith negotiation --}` (del only) because
  the prefix and suffix are common.

### Counterparty-text "deletion" is not reachable via RejectChange

`RejectChange` cancels tracked changes (`Chg:N`). It cannot make
untracked counterparty text disappear — there's no id to target. The
only way to remove counterparty text is to send a visible `ModifyText`
with `new_text=""`, which shows up as a `w:del` in the redline.
Confirmed by `test_reject_non_tracked_text_unreachable`.

**Be aware** (new finding — see "What NOT to do"): `RejectChange` also
doesn't structurally prevent the counterparty from rejecting YOUR edits.

---

## How to attach comments

**Comment on a modification or insertion.**

```python
ModifyText(
    target_text="Delaware",
    new_text="New York",
    comment="Prefer NY to match HQ.",
)
```

The engine emits `w:commentRangeStart` / `w:commentRangeEnd` /
`w:commentReference` around the modification or insertion, and adds a
`w:comment` to `word/comments1.xml` with the specified text and the
engine's `author`.

**Comment on a pure deletion: does NOT work.** See above. Attach to a
retained anchor or use a near-empty `new_text` workaround.

**Comment on a reject/accept: field exists, NOT written.** The
`comment` field on `AcceptChange` / `RejectChange` is parsed by Pydantic
but never written anywhere by the engine (`engine._accept_change` and
`_reject_change` don't read it). Do not rely on it for rationale —
either leave the field out or capture the rationale some other way.

### Comment author attribution

The comment's `w:author` is whatever `RedlineEngine` was constructed
with. If you want multi-party attribution, use two engines:

```python
e_oscar = RedlineEngine(io.BytesIO(initial), author="Oscar")
e_oscar.process_batch([ModifyText(..., comment="Oscar's note.")])
after_oscar = e_oscar.save_to_stream().getvalue()

e_cp = RedlineEngine(io.BytesIO(after_oscar), author="Counterparty")
e_cp.process_batch([ModifyText(..., comment="Counterparty's note.")])
```

Author attribution is per-engine, not per-edit.

### Initials

The engine derives initials by whitespace-splitting the author and
taking the first letter of each token, uppercased:
- `"Oscar"` → `"O"`
- `"Firm Name LLP"` → `"FNL"`

---

## How to reply to a comment

```python
ReplyComment(target_id="Com:5", text="Ack. Agreed.")
```

The reply is added to `comments.xml` as a new `w:comment` with
`parent_id` threaded via `commentsExtended1.xml` (`w15:paraIdParent`).
Modern Word renders it as a threaded reply.

**Quirk: replying to a nonexistent `Com:N` silently succeeds.** The
comment gets added to the comments part, but the anchor lookup logs a
warning and returns without attaching a body range. The resulting doc
has a stray comment with no selection. **Avoid this** — validate your
`Com:N` ids (extract via `extract_text_from_stream`, read the
`[Com:N]` metadata blocks) before submitting replies.

Obtain the parent id by:

```python
raw = extract_text_from_stream(io.BytesIO(docx_bytes))
# Parse raw for "[Com:N] Author @ DATE: text" substrings.
```

---

## How to accept or reject a tracked change

### Accept

```python
AcceptChange(target_id="Chg:1")
```

Commits the proposed text. Adeu's `_get_paired_nodes` groups
contiguous same-author `w:ins`/`w:del` into one logical modification —
so accepting `Chg:1` also atomically accepts `Chg:2` if they were
emitted as a pair. You can pass either id; the result is the same
(`test_accept_by_second_id_of_pair`).

### Reject

```python
RejectChange(target_id="Chg:1")
```

Removes the proposed insertion, restores the original text, cleans up
paired `w:del`.

### Finding the right id

Use `extract_text_from_stream` (raw view) to see the metadata blocks:

```
{--Delaware--}{++New York++}{>>[Chg:1] Oscar\n[Chg:2] Oscar<<}
```

`Chg:1` and `Chg:2` are the paired change ids. Use either.

### Nonexistent id

An Accept or Reject of a nonexistent `Chg:N` is silently skipped
(`actions_skipped += 1`). No exception.

### Comments on the AcceptChange/RejectChange are dropped

As noted above — the `comment` field on these models is parsed but not
written anywhere. Capture rationale elsewhere.

---

## How to handle a multi-edit document

### Edit order

- Non-overlapping edits compose. Submit them in one `process_batch` call.
- The engine sorts heuristic edits by `len(target_text)` descending
  (longer first), then applies indexed edits in reverse position order.
  You don't need to pre-sort.
- **If two edits overlap** (their target spans intersect), the second
  is silently skipped with `edits_skipped += 1`. Budget for this:
  check the return dict after `process_batch`.

### Change IDs across edits and engines

- First tracked change on a fresh doc is `Chg:1`.
- A modification emits **two** ids (del first, ins second) — see `test_modification_emits_paired_ids`.
- A pure insertion (prefix-match) emits **one** id.
- A pure deletion emits **one id per affected run**.
- On reopening a doc with a fresh engine, `current_id` is initialised
  to `max existing id` — new edits continue from `max + 1`, so no
  collisions.

### Mix actions and edits in one batch

```python
engine.process_batch([
    AcceptChange(target_id="Chg:1"),       # accept existing proposal
    ModifyText(target_text="...", new_text="..."),  # add new edit
    ReplyComment(target_id="Com:3", text="Ack."),
])
```

Actions run first (in list order), then the mapper rebuilds, then edits
validate and apply. Reading back: `rv["actions_applied"]` and
`rv["edits_applied"]` are separate counters.

### Disambiguating ambiguous targets

If `target_text` matches more than once, `BatchValidationError` fires
with each occurrence's context. Fix by adding surrounding context:

- Ambiguous: `target_text="The party"` (matches many times)
- Fixed: `target_text="The party shall first notify the Receiving Party"`

Use enough context to make the match unique but no more.

---

## How to round-trip edits (iterative work)

The standard cycle:

1. Open: `engine = RedlineEngine(io.BytesIO(current_bytes), author="Oscar")`
2. Apply: `rv = engine.process_batch(edits)`
3. Save: `out = engine.save_to_stream().getvalue()`
4. Next iteration: `RedlineEngine(io.BytesIO(out), ...)` — a fresh engine.

The same engine is NOT designed for multiple `process_batch` calls in
sequence; use a fresh engine on each iteration. (Multiple calls on one
engine probably work but are untested here.)

### Verifying a round trip

At any point you can sanity-check:

- `extract_text_from_stream(io.BytesIO(out), clean_view=True)` — what
  the doc reads as if all edits were accepted. Compare against your
  expected final text.
- `extract_text_from_stream(io.BytesIO(out), clean_view=False)` — raw
  CriticMarkup view. Inspect the `[Chg:N]` / `[Com:N]` metadata blocks
  to find ids for subsequent Accept/Reject/Reply.

`test_clean_view_round_trip_three_edits` confirms that
`extract_text_from_stream(..., clean_view=True)` == `accept_all_revisions()` then `extract_text_from_stream(...)`.

### Binary handling in Deep Agents

Deep Agents' `StateBackend` stores files as strings (Sprint 6 / 10A R4).
A `.docx` is binary. Two options:

1. **Keep the bytes out of the graph state** — pass a filesystem path
   through the graph, use the path in the tool implementation, let
   the filesystem handle the binary.
2. **Base64 through the state** — encode before put, decode before use.

Option 1 is simpler and is what Sprint 10D should adopt. Not an Adeu
decision — an integration decision.

---

## How to produce a CriticMarkup text view

### From a .docx

```python
from adeu import extract_text_from_stream

# Raw (with {--X--}{++Y++} markers and [Chg:N] metadata)
raw = extract_text_from_stream(io.BytesIO(docx_bytes))

# Clean (accepted-view text, no markup)
clean = extract_text_from_stream(io.BytesIO(docx_bytes), clean_view=True)
```

### From plain Markdown

```python
from adeu import apply_edits_to_markdown

out = apply_edits_to_markdown(
    "The governing law is Delaware.",
    [ModifyText(target_text="Delaware", new_text="New York", comment="Prefer NY.")],
    include_index=True,   # adds [Edit:N] to metadata
    highlight_only=False, # True → {==...==} instead of {--..--}{++..++}
)
# out: "The governing law is {--Delaware--}{++New York++}{>>Prefer NY. [Edit:0]<<}."
```

**Unlike the engine, `apply_edits_to_markdown`:**

- Does NOT support pure insertions. Empty `target_text` → skipped.
- Does NOT have prefix-match shortcuts.
- Skips unmatched targets silently (no exception).

Useful for preview / diff display to a user; NOT useful as a primary
edit pipeline.

---

## What NOT to do

### Don't pass `target_text=""` expecting insertion

It's silently dropped (`edits_applied=0`, `edits_skipped=1`). Use the
prefix-match idiom.

### Don't assume `RejectChange` gates by author

A counterparty who knows the `Chg:N` id can reject YOUR edits, and vice
versa. Author scope is for pairing only, not for primary node access.
`test_reject_foreign_author_change`. If you need cross-party protection,
it must live above Adeu (diff the final state against your own last
output, or sign the output).

### Don't attach comments to pure-deletion edits

They're silently dropped. Attach the comment to a retained anchor near
the deletion instead.

### Don't pass `comment` on AcceptChange / RejectChange

The field exists but is never written. The comment is effectively
ignored.

### Don't over-broad `target_text`

Even though the engine narrows via `trim_common_context`, an over-broad
`target_text`:

- Gives the engine more material to accidentally delete if the
  replacement doesn't overlap as expected.
- Makes fuzzy regex fall-back more likely to span unintended regions
  (including across paragraph boundaries).
- Increases the chance of ambiguous matches.

**Rule of thumb: the shortest unique match that includes both the
changed content and enough anchor to make the match unique.** 5–15
words is the practical sweet spot for LLM use.

### Don't delete a whole sentence to replace it

If the replacement is mostly the same as the original, pass the full
sentence as `target_text` and the modified sentence as `new_text`. The
engine will narrow. **Do NOT** manually split: that loses context and
produces worse redlines. (This is the prior-art rule from
Claude-Plugin-MCP restated in terms of the engine mechanics.)

### Don't rely on the CriticMarkup-in-target feature

The `ModifyText` docstring says you can include `{==...==}` in the
target to match inside existing markup. This is documented but not
reachable from a clean-doc workflow in any straightforward way. If you
hit a case where you need it, treat it as an edge case and verify
empirically before prompt-ing an agent to use it.

### Don't reach into `adeu.redline.mapper` or `adeu.redline.comments` from prompt-level code

Those are internal; prior-art used them, which is why Claude-Plugin-MCP
broke at 0.9 → 1.1. The Oscar agent should stay inside the
`adeu.__all__` public surface. If the public surface genuinely can't
express something, raise it as a question for human decision — do NOT
introduce a wrapper around the internals unilaterally.

### Don't trust the type annotation on `RedlineEngine.__init__`

It says `BytesIO`; it also accepts a str path (via python-docx). Don't
rely on this — adopt `BytesIO` in your code.

### Don't forget that every output has four comment XML parts

Even with zero comments. If you diff output sizes for sanitisation or
regression purposes, expect 21 parts minimum.

---

## Minimal end-to-end example

```python
import io
from adeu import ModifyText, AcceptChange, RedlineEngine, extract_text_from_stream

# 1. Open and apply
with open("input.docx", "rb") as f:
    src = f.read()
engine = RedlineEngine(io.BytesIO(src), author="Oscar")

rv = engine.process_batch([
    ModifyText(
        target_text="Delaware",
        new_text="New York",
        comment="Prefer NY for tax residency.",
    ),
    ModifyText(
        target_text="one (1) year",
        new_text="two (2) years",
    ),
    ModifyText(
        target_text="This Agreement is governed by the laws of the State of New York.",
        new_text="This Agreement is governed by the laws of the State of New York. Any dispute shall be resolved by binding arbitration administered by JAMS in New York.",
    ),
])

print(rv)
# => {'actions_applied': 0, 'actions_skipped': 0,
#     'edits_applied': 3, 'edits_skipped': 0}

out_bytes = engine.save_to_stream().getvalue()
with open("output.docx", "wb") as f:
    f.write(out_bytes)

# 2. Verify clean view reads as expected
print(extract_text_from_stream(io.BytesIO(out_bytes), clean_view=True))
# => "The governing law is New York. The term is two (2) years..."

# 3. Verify raw view shows the right structure
print(extract_text_from_stream(io.BytesIO(out_bytes)))
# => "The governing law is {--Delaware--}{++New York++}{>>[Chg:1] Oscar\n[Chg:2] Oscar\n[Com:1] Oscar @ ...: Prefer NY for tax residency.<<}. ..."
```

This is the pattern Sprint 10D's tool implementation should match.
