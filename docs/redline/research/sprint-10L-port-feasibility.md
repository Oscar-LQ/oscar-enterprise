# Sprint 10L — port feasibility research note

This note is the cross-track durable artefact of Sprint 10L's Phase 1
research. It survives regardless of the sprint's outcome. Future
redline or CoSec sprints that consider a Claude-Plugin-MCP (CPM) port
against Adeu can refer here instead of re-extracting the material.

Written per `CLAUDE.md § Cross-Version Porting Research` — when a
sprint ports a pattern whose source depends on a third-party library,
Phase 1 must verify contract compatibility against the library version
currently in use. Section 1 carries over Sprint 10K's version check
(Adeu 0.7.x → 1.1.0) without re-deriving it; sections 2–5 cover the
10L-specific port-feasibility questions.

---

## 1. Version check — carried forward from Sprint 10K

Sprint 10K's research note (`sprint-10k-claude-plugin-mcp-port.md` §5)
established that Adeu v0.9.0 renamed `DocumentEdit` → `ModifyText` as
part of a unified `DocumentChange` union, but preserved field names
(`target_text`, `new_text`, `comment`) and the `RedlineEngine` /
`validate_edits` / `process_batch` surface. CPM's `from adeu import
DocumentEdit` imports are the only Python-side edit; the LLM↔code
contract is unchanged. 10L inherits that finding unchanged and
substitutes `from adeu import ModifyText` at the port boundaries.

---

## 2. `find_match_three_layer` — liftable essentially as-is

**Source:** `reference-material/claude-plugin-mcp/src/pipeline/surgical_helpers.py:40-69`.

**Signature:**

```python
def find_match_three_layer(
    engine,
    target_text: str,
) -> tuple[object, int, int]:
    """Try full mapper, clean mapper, then PlainTextIndex to find target.
    Returns (active_mapper, start_idx, match_len). (None, -1, 0) on miss.
    """
```

**Engine-side dependencies.** Reads three attributes from `engine`:
`engine.mapper`, `engine.clean_mapper`, `engine.doc`. All three are
public attributes of Adeu 1.1.0's `RedlineEngine`
(`reference-material/adeu/src/adeu/redline/engine.py:35-45`). The
function lazily constructs `DocumentMapper(engine.doc, clean_view=True)`
for layer 2 — a public Adeu 1.1.0 constructor.

**Mapper-side dependencies.** `mapper.find_match_index(target_text)`
exists on Adeu 1.1.0's `DocumentMapper`
(`reference-material/adeu/src/adeu/redline/mapper.py:492-528`) with
the same signature and internal three-fallback structure (exact →
smart-quote → fuzzy-regex; Adeu 1.1.0 adds an intermediate
strip-markdown layer CPM lacks, but the surface is contract-compatible).
`mapper.find_target_runs_by_index(start_index, length)` exists at
`mapper.py:573-575` returning `List[Run]` of the python-docx Run
objects covering the match span.

**Third-layer dependency.** `PlainTextIndex` is CPM-local
(`src/pipeline/plain_text_index.py`), self-contained, and uses only
`mapper.spans` — a public Adeu attribute. 10L ports it verbatim.

**Port grade: liftable essentially as-is.** Only edit: replace
`from adeu import DocumentEdit` with `from adeu import ModifyText` in
the one sibling module that imports it (`surgical_helpers.py`). 10L
extracts only the function + its deps, not the wider
`apply_edits_surgically` orchestration.

---

## 3. `diff_words` — liftable as-is

**Source:** `reference-material/claude-plugin-mcp/src/pipeline/word_diff.py:27-57`.

**Signature:**

```python
def diff_words(
    old_text: str,
    new_text: str,
) -> list[tuple[int, str]]:
```

Returns a list of `(op, text)` tuples where `op` is -1 (DELETE), 0
(EQUAL), or 1 (INSERT).

**Mechanism.** Tokenises both strings with `re.compile(r"\S+|\s+")`
(words and whitespace runs; legal standard "claims." is one token).
Maps each unique token to a unique Unicode character starting at
U+0100. Runs `diff_match_patch.diff_main` on the encoded strings,
then applies `diff_cleanupSemantic` (the semantic cleanup pass —
**not** `diff_cleanupLossless` or `diff_cleanupEfficiency`). Decodes
the resulting ops back to word-level text segments.

**Dependencies.** `diff-match-patch==20241021` (already pinned from
Sprint 10J's `requirements.txt`). Zero Adeu coupling. Pure Python.

**Port grade: liftable as-is.** 10L copies `diff_words`,
`verify_reconstruction`, `_encode_tokens`, `_decode_diffs` verbatim.

---

## 4. Adeu 1.1.0's `trim_common_context` — fired in 10K, narrowed nothing

The brief's most important Phase 1 question was whether Adeu's
existing `trim_common_context` would have produced narrow output if
Sprint 10K had invoked Adeu differently — i.e., whether the port is
unnecessary because Adeu's native surface already suffices.

**Answer: no.** The port is necessary. `trim_common_context` did fire
in 10K's run and returned `(0, 0)`.

**Source:** `reference-material/adeu/src/adeu/diff.py:12-172`.

**Signature:** `trim_common_context(target: str, new_val: str) -> tuple[int, int]`,
returning `(prefix_len, suffix_len)`.

**Algorithm.** Character-level shared-prefix scan + character-level
shared-suffix scan, with word-boundary backtrack and markdown-marker
awareness. **Prefix/suffix only — does not find arbitrary internal
shared structure.**

**Invocation.** Fires automatically inside
`_apply_single_edit_heuristic` at `engine.py:751`, which
`process_batch` calls via `apply_edits` for each `ModifyText`. It
ran on 10K's edit.

**Manual trace on 10K's inputs.**

```
target  = "The parties submit to ... in connection with this Agreement."
new_val = "Any dispute or claim ... final and binding on the parties."

target[0]  = 'T' ≠ new_val[0]  = 'A' → mismatch at position 0 → prefix_len = 0
target[-1] = '.' = new_val[-1] = '.' → match (suffix_len tentatively 1)
target[-2] = 't' ≠ new_val[-2] = 's' → mismatch →
  word-boundary backtrack: target[-1]='.', target[-2]='t' — not a
  whitespace-safe boundary, so suffix_len decrements to 0.

Result: (0, 0). No narrowing.
```

This is why 10K's output was wide: Adeu's native narrower can only
recover edits with shared boundaries, not interior shared structure.

**No other native narrowing primitive on the edit-application path.**
Adeu 1.1.0 does import `diff_match_patch` at `diff.py:5` but uses it
only in `generate_edits_from_text` (reverse direction: doc diff →
edit list), not during `process_batch` or `apply_edits`.

**Conclusion.** The port is required. Adeu's public surface has no
equivalent to CPM's word-level diff on the application path.

---

## 5. Data flow 10L produces (and why it is a faithful mechanism port)

1. Load 10K's `parsed-edits.json` (copied into 10L's directory via
   `git show` from the 10K feature branch — no branch checkout).
2. Load `nda-input.docx`; instantiate `RedlineEngine`.
3. For each edit: `mapper, start_idx, match_len =
   find_match_three_layer(engine, edit["target_text"])`.
4. `target_runs = mapper.find_target_runs_by_index(start_idx, match_len)`.
5. `runs_plain_text = "".join(run.text or "" for run in target_runs)`.
6. `diffs = diff_words(runs_plain_text, edit["new_text"])`.
7. Block-group diff ops at long-EQUAL boundaries (threshold: 2
   content tokens). Emit one narrower `ModifyText` per block,
   including surrounding EQUAL tokens as anchor context so the
   block's `target_text` is uniquely findable in the document.
8. Apply via `engine.process_batch(narrowed_edits)`.

Steps 3–6 are CPM's mechanism verbatim. Step 7 is the substrate
adaptation (CPM emits OOXML per diff op via direct DOM surgery; 10L
batches into `ModifyText` and routes through Adeu's public
`process_batch`). Step 8 replaces CPM's `perform_dom_surgery` +
`engine._create_track_change_tag` (private API). The mechanism under
test — find + diff — is unchanged; only the application layer differs.

**Not ported (scope-excluded per 10K research note §5).**
`apply_edits_surgically` orchestration (sort-by-length, pre/post-match
delegation, heavy-rewrite flagging). `build_diff_elements` /
`perform_dom_surgery` OOXML construction. These are CPM's
compensation layers for production document variety; 10L's
single-paragraph synthetic NDA does not exercise them.

---

## 6. Phase 3 discovery — `diff_cleanupSemantic` is the load-bearing step

This section documents what Phase 3 revealed, added here because it
refines the port-feasibility finding in a way that affects future
sprints.

**Expected before the run.** Best-guess Outcome B. 10K's `target_text`
and `new_text` share the 10-word substring "arising out of or in
connection with this Agreement" verbatim — that should anchor at
least two logical blocks in `diff_words`'s output, producing two
narrower `ModifyText` edits.

**Actual.** Outcome C. `diff_words` produced exactly two ops:

```
[-1] <full 29-word target_text>
[ 1] <full 56-word new_text>
```

Block grouping produced one block. Output OOXML: `w:del=29 words /
w:ins=56 words` — identical shape to 10K's direct-to-Adeu output.

**Why.** `diff_match_patch.diff_main` (raw, before cleanup) finds 72
tiny token-level ops on 10K's inputs, including shared fragments like
" ", " of ", "arising", " disputes ", "Agreement.". But
`diff_cleanupSemantic` — CPM's cleanup of choice, ported verbatim —
detects these shared fragments as short-runs-surrounded-by-changes
and absorbs them into the neighbouring DELETE + INSERT ops. Its
heuristic judges the "semantic" shape to be one wide bundle.

Raw diff_main (no cleanup) vs. `diff_cleanupSemantic` (CPM's):

| Cleanup pass | ops | widest DEL | widest INS |
|---|---|---|---|
| (none) | 72 | 1 token | 7 tokens |
| `diff_cleanupSemantic` | 2 | 29 words | 56 words |

Emitting per-op OOXML (CPM's direct-DOM path) would produce 72 tiny
spans without cleanup — noisy and noise-intolerant for Word's track
changes. With cleanup, CPM gets 1 DEL + 1 INS — same wide shape 10L
produced via the process_batch route. The narrowness property of
CPM's output on Opus therefore depends on Opus producing `new_text`
with LONGER shared phrasing runs than MiniMax does — long enough that
`diff_cleanupSemantic` preserves them instead of collapsing.

**Implication for the CPM port's utility on MiniMax.** The find+diff
mechanism is mechanically sound but does not, on its own, narrow
MiniMax's wholesale-rewritten output. The narrowness lever is
upstream of the mechanism — in the LLM's choice of how much original
phrasing to preserve — OR orthogonal to CPM's cleanup choice (a
different cleanup pass, or no cleanup, with downstream filtering).
Either direction is outside 10L's scope; both are candidates for
Sprint 10M.

**Implication for future CPM ports.** Any sprint porting CPM's
surgical pipeline should treat `diff_cleanupSemantic` as the first
parameter to probe, not a safe default. Its behaviour is benign on
Opus-style diffs (long shared runs → preserved) and failure-mode on
MiniMax-style diffs (short scattered runs → collapsed). The CLAUDE.md
Cross-Version Porting Research rule should be read more broadly than
"library version check" — cleanup-pass choice in a cross-language
text-processing library is a behavioural dependency worth naming.
