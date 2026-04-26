# Sprint 10N — Adeu upgrade and B1/B2 system-prompt comparison

Phase 1 research note. Two parts: §1 documents the Adeu 1.1.0 → 1.3.3
upgrade verification (no breaking changes for Oscar's pipeline). §2
reports the B1 vs B2 prompt comparison findings — both runs against
MiniMax-M2.7 on the Acme NDA with the Sprint 10N solicitor's brief.
§3 recommends the system prompt for Phase 3.

---

## §1 — Adeu 1.1.0 → 1.3.3 upgrade verification

### Method

Created a fresh venv at `/sandbox/.venv-adeu133-test/` with
`adeu==1.3.3`. Verified every Adeu import 10M's `pipeline.py` uses,
then introspected the installed source for signature changes vs 1.1.0.
Once clean, upgraded `/sandbox/.venv/` and bumped `requirements.txt`
from `adeu==1.1.0` to `adeu==1.3.3`.

### Findings

**No breaking changes for Oscar's redline pipeline.** Every API surface
10M depends on is preserved across the 1.1 → 1.3.3 jump.

| API surface | 1.1.0 | 1.3.3 | Change |
|---|---|---|---|
| `from adeu.ingest import _extract_blocks` | present | present | none |
| `from adeu.models import ModifyText` | present | present | none — same fields `target_text`, `new_text`, `comment`; same private attrs `_match_start_index`, `_internal_op`, `_active_mapper_ref` |
| `from adeu.redline.comments import CommentsManager` | present | present | none |
| `from adeu.redline.engine import RedlineEngine` | present | present | none — `__init__(doc_stream: BytesIO, author: str = 'Adeu AI')` unchanged |
| `from adeu.redline.engine import BatchValidationError` | present | present | none |
| `from adeu.redline.mapper import DocumentMapper` | present | present | none — `__init__(doc, clean_view=False)` unchanged |
| `from adeu.utils.docx import create_element, iter_document_parts` | present | present | none |
| `engine._create_track_change_tag(tag_name, author='')` | present | present | none — 1-arg-callable form preserved |
| `engine.apply_edits(edits) -> tuple[int, int]` | present | present | none |
| `engine.save_to_stream() -> BytesIO` | present | present | none |
| `mapper.find_match_index(target_text)` | present | present | none |
| `mapper.find_target_runs_by_index(start_idx, length)` | present | now `(start_idx, length, rebuild_map=True)` | new optional kwarg with default — backward compatible |
| `mapper.get_context_at_range(start, end)` | present | present | none |
| `mapper._build_map()` | present | present | none |
| `_parse_inline_markdown` / `_parse_markdown_style` | present | present | none — already in 1.1.0 |
| `trim_common_context` (module-level in `adeu.redline.engine`) | present | present | none |

The 1.1.0 → 1.3.3 jump is internally a major-version-equivalent (skips
1.2.x which added live Word integration and expanded multi-paragraph
markdown handling, and 1.3.x which added email tools), but the
redline-pipeline-relevant signatures are stable. The expansion in
v1.2.0 of multi-paragraph markdown to "tracked as one logical
revision" is a behaviour available on the delegation path
(`engine.apply_edits([edit])`), not on Vibe's inline word-diff path.
**10M's pipeline only fires the delegation path on edge cases, so most
Markdown-bearing edits in 10N will go through the inline path's
existing `_strip_formatting_markers` — see §1.2 caveat.**

PyPI confirms 1.3.0, 1.3.2, 1.3.3 in the 1.3.x line; the latest two
patches (1.3.2, 1.3.3) have no GitHub release notes. Per Arturs's
Q3 answer, installed 1.3.3 (latest) rather than 1.3.0 verbatim.

### §1.2 caveat — inline-path Markdown stripping persists

10M's `pipeline.py:_strip_formatting_markers` (line 518–540) strips
`**`/`_` from `new_text` before the inline word-diff. Adeu 1.3.x's
native markdown parsing only fires when the pipeline delegates to
`engine.apply_edits([edit])` — which it does only on edge cases
(empty target, pure deletion, multi-paragraph span, in-w:ins,
reconstruction mismatch). Inline edits in 10N will lose
bold/italic markers if MiniMax produces them. This is the documented
inline-path behaviour from 10M, not a parser bug. SPRINT_LOG §10N
must trace any "lost formatting" finding to this architectural
choice — 10O addresses inline-vs-delegation if Arturs flags it as
material.

### §1.3 production state

- `/sandbox/.venv/` adeu = 1.3.3 (upgraded from 1.1.0)
- `/sandbox/oscar-enterprise/requirements.txt` adeu pin = 1.3.3
- `/sandbox/.venv-adeu133-test/` retained for reference; can be
  removed once 1.3.3 is bedded in.

---

## §2 — B1 vs B2 system-prompt comparison

### Method

Single MiniMax-M2.7 call per variant against the Sprint 10N user
message: solicitor's brief + NDA full text + data contract note. No
Adeu involvement — `phase1_capture.py` stops after `parse_ai_response`
and writes the parsed edit list to JSON.

- **B1** = trimmed Vibe system prompt (10M's `system_prompt` minus
  the `## Output Format` section and `### edit_type Values` —
  preserves persona, structured-reasoning instructions, edit-precision
  rules, WRONG/RIGHT examples, numbering rules, track-change
  awareness, CriticMarkup awareness). Length: 11,814 chars.
- **B2** = the four-sentence solicitor system prompt verbatim from the
  10N brief. Length: 281 chars.

User message identical across both (9,832 chars). Same NDA.

### Mechanical results

| Metric | B1 (trimmed Vibe) | B2 (short solicitor) |
|---|---|---|
| Raw response chars | 4,664 | 5,567 |
| Markdown fence in reply | no — bare JSON | yes — `\`\`\`json … \`\`\`` |
| Parse method | direct (layer 1) | direct (layer 1) |
| Top-level key produced | `changes` | `changes` |
| Edit count | 4 | 4 |
| Reasoning object present | no | no |
| Elapsed | 34.3 s | 20.7 s |

Both runs honoured the data contract (`changes` key); neither
produced Vibe's `{reasoning, edits, summary}` schema even though B1's
prompt asks for structured reasoning. The data contract note in the
user message dominates over the trimmed system prompt's reasoning
scaffolding.

### Coverage — which clauses each variant edited

| Solicitor instruction | B1 | B2 | Notes |
|---|---|---|---|
| Mutual obligations throughout | **MISSED** | **MISSED** | Neither flagged the one-way framing in clauses 2 and 6. Substantive gap in both runs. |
| Three-year confidentiality survival | not edited | not edited | Correctly identified — clause 5 already says "three (3) years". |
| Liability cap carve-outs (fraud, wilful misconduct, breach of confidentiality) | clause 7 inline insertion | clause 7 wholesale rewrite + new bullet list | Both substantively addressed. Shape differs sharply (see below). |
| Independent development exclusion | clause 4 inline append (item (e)) | clause 4 inline append (item (e)) | Both produced near-identical surgical edits. |
| Group companies disclosure | clause 3 inline phrase insertion in Representatives definition | clause 3 wholesale rewrite + new sentence | Both substantively addressed. Shape differs. |
| LCIA arbitration (preserve gov law) | clause 9 — only the jurisdiction sentence replaced; governing law sentence untouched | clause 9 — entire clause text replaced including heading | B1 surgically preserved governing-law sentence; B2 included it in the target as part of a wholesale clause rewrite. |
| "Apply your judgement / flag what you'd want my input on" | one comment with explicit "Please confirm…" partner-input request | no partner-input flags | B1 produced the requested partner-flag idiom; B2 did not. |
| "Don't over-mark" | edits stay anchored, surrounding text preserved | one edit ("also tightened wording from…") explicitly admits scope creep | B2 over-marked. |

### Shape — the headline finding

**B1's edits are surgically anchored. B2's edits are wholesale clause
replacements.**

The Limitation of Liability edit illustrates the difference cleanly:

- **B1** target = the existing sentence body. New_text = same sentence
  with the carve-out inserted after `applicable law,`. About 90% of
  the new_text is verbatim from target — `diff_cleanupSemantic` will
  preserve the long shared prefix and produce a tight word-level
  diff. WRONG/RIGHT MISALIGNMENT-RIGHT pattern applied.
- **B2** target = `## 7. Limitation of Liability\n\n` + entire clause
  body (heading anchored). New_text = heading + restructured
  introduction + new paragraph + bullet list of carve-outs. The
  heading is in both target and new but as the leading prefix; about
  60% of the prose was rewritten. In Word this will appear as a large
  strikethrough block on the original clause and a fresh insert.

The dispute resolution edit is even more diagnostic:

- **B1** target = only the 27-word jurisdiction sentence. New_text =
  the four-sentence LCIA arbitration paragraph. The governing-law
  sentence (which the brief instructs to preserve) is **not in the
  target at all** — it stays untouched in the document. B1's redline
  on §9 will look like one wide insertion replacing one sentence.
- **B2** target = `## 9. Governing Law and Dispute Resolution\n\n` +
  the whole §9 body (governing law sentence + jurisdiction sentence).
  New_text = the same heading + governing law sentence (preserved
  verbatim) + a new paragraph break + LCIA arbitration paragraph. B2's
  redline on §9 will appear as the entire clause being struck through
  and a new clause inserted, even though the governing law text is
  byte-identical in both target and new — `diff_cleanupSemantic`
  *should* preserve it (~80 word shared prefix), but the heading and
  the structural paragraph break create more diff noise than B1's
  one-sentence target.

B2 also includes heading prefixes (`## 3.`, `## 7.`, `## 9.`) in three
of four targets — these come from the doc_analyser's PARAGRAPH MAP
header that the LLM is using as a navigation aid. B1 went straight to
sentence-level targets without anchoring to clause headings.

### Comment quality

- **B1**: comments use Vibe's `MISALIGNMENT:` / `GAP:` prefix,
  reference the brief instruction explicitly, and one carries the
  "Please confirm…before we send" idiom the solicitor's brief asked
  for ("Comments where you have a concern but want my input").
- **B2**: comments are conversational and brief. One ("Added
  disclosure to group companies as requested") gives no rationale. One
  ("also tightened wording from 'cannot be limited or excluded by
  applicable law' to specific carve-outs") openly admits a change the
  brief did not authorise — direct violation of "Don't over-mark."

### Did Vibe's classification scaffold force-fit awkwardly?

The brief asked: did B1's structured-reasoning scaffold force-fit the
naturalistic tactical instructions into GAP/MISALIGNMENT/ADEQUATE/
FLAGGED buckets awkwardly?

Answer: **no, because the LLM dropped the reasoning scaffold
entirely.** Neither run produced a `reasoning` object. The MiniMax
response in B1 went straight to `{changes: [...]}` per the data
contract, ignoring the system-prompt instruction to produce a
structured reasoning. The classification framework's only visible
influence is the `MISALIGNMENT:` / `GAP:` comment prefixes that bled
into B1's `comment` strings — and even those were applied somewhat
loosely (clause 4's edit is technically a MISALIGNMENT of the
exclusions list to add an item, but B1 commented `GAP:` because the
item itself is missing).

The Edit Precision Rules and WRONG/RIGHT examples did fire — visibly
in the surgical anchoring of B1's targets and the partner-input
"Please confirm…" comment idiom.

### Did B2 under-mark without the scaffold?

Same edit count (4), similar coverage. So B2 did not under-mark in
volume. B2 did under-flag — no partner-input requests despite the
solicitor's brief asking for them on uncertain calls — and B2
over-marked in scope (the unrequested cap-language tightening). Edit
shape was wider (wholesale clauses) rather than narrower.

---

## §3 — Phase 3 system-prompt recommendation

**Recommendation: B1 (trimmed Vibe).**

The mechanical metrics are nearly equal (same edit count, same
coverage of four solicitor instructions, same parse path, same
mutual-obligations gap). The substantive difference is shape:

1. B1 preserves anchor text in `new_text` where the brief allows,
   yielding word-level diffs that read as surgical amendments. B2
   produces wholesale clause rewrites that will read as cluttered
   strikethrough + reinsertion blocks in Word.
2. B1's dispute resolution edit isolates the jurisdiction sentence
   and leaves governing law untouched — exactly the shape the brief
   asked for. B2 wraps the governing law sentence into the target
   even though it doesn't change.
3. B1 honours "Comments where you have a concern but want my input"
   with one explicit partner-input request. B2 produces no
   partner-input flags.
4. B1's only over-mark risk is the comment-prefix discipline
   bleeding through. B2 over-marks substantively (admits scope
   creep on cap-language tightening that the brief did not
   authorise).

The Vibe scaffolding's visible influence is in shape, not in
structured-reasoning output. Even with the output-schema section
trimmed, the WRONG/RIGHT examples and Edit Precision Rules
demonstrably shape the LLM's anchoring choices.

**Caveat to flag for Arturs's substantive review:**

- Both B1 and B2 missed the "mutual obligations throughout"
  instruction. Neither flagged the one-way framing in clauses 2 and
  6 of the NDA. This is a substantive gap that will surface when
  Arturs reviews the .docx. If the gap matters, it is a content
  issue (LLM didn't notice the framing) rather than a prompt-shape
  issue (B2 didn't notice it either). 10O could address it via a
  more directive system prompt or by a planner-pass that explicitly
  enumerates clause-by-clause review.
- B1 added a heading-only structural change in the LCIA edit (replaced
  one sentence with a four-sentence paragraph). The pipeline's
  `_insert_new_paragraphs` will fire here — Adeu 1.3.3's native
  multi-paragraph-as-one-revision behaviour would only fire on the
  delegation path, which the inline word-diff path bypasses. If the
  Word redline shows the four arbitration sentences as four separate
  insertions rather than one logical revision, that is the
  inline-path-vs-delegation behaviour from 10M, not a 10N regression.

Phase 3 plan: use B1 as `system_prompt.txt`. Run end-to-end via
`pipeline.apply_edits`, capture .docx, push to GitHub feature branch,
defer substantive judgement to Arturs.
