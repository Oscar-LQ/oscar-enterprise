# Lawyer-Shape Success Criteria — NDA Transformation Test Battery

> Draft success criteria for the three NDA transformations defined in
> Sprint 10A §3.5, to be used by Sprint 10E to evaluate an agent's
> redlined output.
>
> **Status: DRAFT — awaiting human (Arturs) review before 10E runs.**
>
> The substantive (legal) criteria ultimately need practising-lawyer
> sign-off. Sandbox-Claude's draft below is the starting point,
> grounded in English/common-law drafting norms. Arturs may change
> the substance, add/remove criteria, or re-weight what counts as
> disqualifying. The *structural* criteria are mechanical and should
> be stable under his review.
>
> **Evaluation posture.** Criteria are prose, not a scored rubric.
> Sandbox-Claude-Code (Sprint 10E's evaluator role) writes a verdict
> per transformation — "lawyer-shape" / "close to lawyer-shape, N
> issues" / "not lawyer-shape" — with citations to specific OOXML
> elements or clean-view spans. Human reviewer can override any
> verdict.
>
> **Why three separate criteria documents rolled into one.** The three
> transformations stress different capabilities: (1) coordinated
> mechanical consistency, (2) drafting novel text in a sensible
> location, (3) targeted rewrites with an orthogonal carve-out. Criteria
> are phrased per transformation; common criteria (author attribution,
> .docx validity) appear once in §0.

---

## 0. Common criteria (apply to all three transformations)

### 0.1 Structural (mechanical)

- **The output file is a valid `.docx`.** `zipfile.is_zipfile(path)` is
  True. `python-docx.Document(path)` opens without exception. The
  `word/document.xml` part parses as valid XML.
- **No runtime errors.** The agent's run-trace contains no uncaught
  `BatchValidationError`. Any `edits_skipped > 0` count must be
  explained in the agent's own reasoning — if it isn't, that is an
  evaluation issue (not disqualifying on its own, but material to the
  verdict).
- **Author attribution.** Every `w:ins` and `w:del` has
  `w:author` equal to the supplied client name (e.g. `"Client Ltd"`).
  No `w:ins` or `w:del` carries `w:author=""` (empty string) or
  `w:author="Adeu AI"` (the default — means the engine was constructed
  without an author argument, which is a prompt / tool-implementation
  bug).
- **Date attribution.** Every `w:ins` and `w:del` has a `w:date`
  attribute in ISO 8601 UTC form (`YYYY-MM-DDTHH:MM:SSZ`). Checked via
  regex, not value.
- **Comment parts if present are valid.** If any `w:comment` exists,
  each has a non-empty `w:t` body and `w:author` matching the client
  name.
- **Clean-view round-trip.** `extract_text_from_stream(path, clean_view=True)`
  runs without error and returns sensibly-formed text (non-empty,
  reasonable paragraph structure).

### 0.2 Substantive (legal)

- **Clause numbering is preserved or renumbered consistently.** If the
  agent added a clause, clause numbers after the insertion must
  renumber consistently, OR the agent added a comment explaining a
  deliberate "leave numbering alone" choice.
- **No unrelated edits.** The agent should not have marked any text
  outside the scope of the requested transformation. If it did,
  material to the verdict.
- **Comment discipline: 0–3 comments per transformation.** The
  Claude-Plugin-MCP prior art's rule, restated. More than 3 comments on
  a single-transformation NDA redline is noise; they're either
  restating the tracked change or marking uncertainty the agent should
  have resolved.

### 0.3 Disqualifying (automatic fail)

These override any other merit; if any of these is present, the verdict
is "not lawyer-shape" regardless of everything else.

- **`.docx` won't open** or fails `python-docx.Document()`.
- **Counterparty text silently destroyed.** Text that was in the input
  doc but appears in neither the clean view NOR inside a `w:del` in the
  annotated view. This is the "delete sentences instead of redlining"
  failure mode from prior art; it means the agent either bypassed
  tracked-changes or exploited an Adeu quirk to delete without audit
  trail. Check: diff the clean-view of the output against the input
  minus-deletions; nothing should have disappeared that wasn't
  explicitly `w:del`'d.
- **Large paragraph-level rewrites.** A single `w:del`/`w:ins` pair
  whose spans each exceed **50 words**, OR a pair where the deleted
  and inserted content are ≥80% dissimilar (measured by
  token-overlap). This is a proxy for "rewriting instead of editing".
  50 words is roughly a full long sentence; past that, the redline is
  not reviewable clause-by-clause. (50 is a soft upper bound for
  individual pairs; whole-paragraph rewrites done for a reason — e.g.
  T3's dispute-resolution clause — should be split into multiple
  smaller `w:del`/`w:ins` pairs for review-ability.)
- **Edit author mismatch.** Any `w:ins` or `w:del` carries `w:author`
  that isn't the supplied client identity. Note: non-client author
  strings may appear on existing comments, but new tracked changes
  must all be attributed to the client. A `w:author="Adeu AI"` on any
  tracked change means the agent failed to configure the author
  properly — disqualifying.
- **Over-commented.** More than 5 comments on a single-transformation
  NDA. Indicates the agent is treating comments as scratch space.
- **Keyword-swap style changes without accompanying substantive
  rewrites.** Detailed per transformation below. Means: did the agent
  just find-and-replace "litigation" with "arbitration" without
  rewriting the mechanics? That is disqualifying for T3 specifically.

---

## 1. Transformation 1 — Make the NDA mutual

### 1.1 Structural criteria

- **Every asymmetric-role reference in the operative clauses is
  touched.** Enumerate the occurrences of "Disclosing Party" and
  "Receiving Party" (or equivalent role labels) in the original doc.
  Every occurrence that is part of an *obligation* or *grant* (not
  merely a recital / definition) should appear within a `w:del` block.
  An orphan occurrence — an asymmetric reference that remained
  unedited — flags as a completeness failure.
- **At least one edit lands in each clause that defined a one-way
  duty.** If the original NDA has 8 clauses, and 5 of them are
  unilateral, at least 5 should have `w:ins`/`w:del` activity.
- **Edit count range: 8–40 tracked changes** (rough heuristic). Too
  few (<4) means incomplete; too many (>40) means over-editing or
  renaming a defined term across too many places without using a
  definition.
- **No whole-clause deletions.** No `w:del` should span an entire
  clause's content. Clause structure should remain visible in the
  redline.
- **Defined-term usage is preserved.** If the original had
  `"Confidential Information"` as a defined term with a capital-C, the
  mutualised version should still use that term — not fuzz it into
  `"confidential information"` or `"Information"`.

### 1.2 Substantive criteria

- **Symmetrisation pattern is consistent.** Two acceptable patterns:
  - **"each Party / the other Party"** — the standard modernisation.
    Applied, it replaces `"Disclosing Party"` → `"disclosing Party"` (or `"a Party"`) and `"Receiving Party"` → `"receiving Party"` (or `"the other Party"`), in a way that makes the sentence read as bilateral.
  - **Dual-role retention** — both parties defined as simultaneously
    Disclosing and Receiving. More work, rarely done; acceptable if
    the agent chose it explicitly.

  A hybrid between the two is a failure mode (reads as incoherent).

- **Obligations actually flow both ways after the edit.** Read each
  operative clause in the clean view. Each confidentiality obligation,
  each non-use obligation, each return-of-materials obligation must
  now bind both parties. Not just in the obligations clauses — also
  in:
  - Definitions (if `"Confidential Information"` was scoped to what one party discloses, widen it to "what either party discloses").
  - Exceptions carve-outs (if there's an exceptions clause — "publicly
    known", "independently developed" — these read fine as written but
    the agent should have verified).
  - Remedies clauses (injunctive relief must be available to either
    party).
  - Survival clauses (duration must apply to both sets of obligations).

- **Non-operative clauses untouched.** Recitals, "whereas" clauses,
  and the title ("Non-Disclosure Agreement" vs "Mutual Non-Disclosure
  Agreement") — the agent may or may not amend these; either is
  acceptable if the operative mutualisation is complete. If the title
  says "Mutual" post-edit, the operative clauses MUST be mutualised.
  If the title is untouched but the operatives are mutualised, a
  comment flagging "title change recommended" is appropriate but not
  required.

- **No counterparty-sided language left behind.** For example,
  language that explicitly grants rights only to the client (or only
  to the counterparty) must be symmetrised or be given an explicit
  comment explaining why it was left one-sided. Examples: injunctive
  relief grants, fee-recovery clauses, limitation periods.

### 1.3 Disqualifying (specific to T1)

- **Orphan asymmetric reference** that is clearly an obligation (not
  a recital). E.g. "the Receiving Party shall not disclose" remains
  unedited in a clause where "the Disclosing Party shall provide
  materials" was edited. One such orphan is enough.
- **Definitions mutualised but obligations not**, or vice versa.
- **Defined-term broken** (e.g. `"Confidential Information"` renamed
  to `"Information"` or `"confidentiality"`).
- **The title says "Mutual" but operative clauses remain
  unilateral.**
- **Wholesale replacement of both party-role labels with one
  neutral term like "X"** without preserving capitalisation or the
  referential style of the original. I.e. a keyword-swap approach.

---

## 2. Transformation 2 — Add a limitation of liability

### 2.1 Structural criteria

- **Exactly one new clause inserted** (or, if the agent split it into a
  main cap clause plus carve-outs sub-clause, exactly one main clause
  plus N sub-clauses).
- **Insertion lands in a sensible location.** Locations considered
  sensible (in descending preference):
  1. Between the no-warranty / representations clause and governing law.
  2. Immediately before governing law, as a standalone clause.
  3. Inside a Miscellaneous clause as a sub-clause.
  4. Immediately before signature blocks, as a final substantive clause.

  Other placements (e.g. inside the definitions, or inside a
  confidentiality-obligations clause) are failures. The agent should
  document its placement choice in a comment if it chose anything other
  than #1–#4.

- **No other clauses materially edited.** Acceptable "touch" edits:
  - Renumbering of subsequent clauses if the agent renumbered (required
    if inserting mid-document).
  - Changing a cross-reference in another clause to point at the new LoL
    clause, if any such cross-reference existed.

  Anything else is out-of-scope.

- **Edit count range: 1–5 tracked changes** for the substantive
  insertion, plus 0–N for renumbering depending on where the clause
  lands. Typical total: 2–10.

### 2.2 Substantive criteria

- **The cap is exactly as instructed: the greater of £100,000 or fees
  paid under any related agreement.** The word "greater" must be
  present — not "lesser of", not just "£100,000", not just "fees".
- **The three carve-outs are present and named:**
  1. Fraud.
  2. Wilful misconduct (spelling variant "willful" acceptable for US
     house style; "wilful" is UK/common-law).
  3. Breach of confidentiality / breach of confidentiality obligations.

  The carve-outs must EXCLUDE these from the cap — i.e. liability for
  these is unlimited. Language like "nothing in this clause limits
  liability for..." or "the cap in paragraph (a) does not apply to
  liability arising from..." is correct. Language that merely
  *mentions* fraud or confidentiality without excluding it is wrong.

- **The cap language is professionally drafted.** The clause reads
  like drafting from a law firm's house style; no placeholders like
  "[AMOUNT]", no bracketed "to be discussed", no mention of "per
  instructions above".
- **The cap is bilateral.** The language must apply to both parties'
  liability (the NDA was already, or has just been, mutualised — so
  both parties are potentially liable for breach of confidentiality,
  and the cap should limit both parties' exposure).
- **Applies to damages/losses, not just financial liability.**
  "Liability" alone, or "liability in contract, tort (including
  negligence) or otherwise" are acceptable. "Financial liability"
  alone is too narrow — leaves equitable remedies outside the
  framework.

### 2.3 Disqualifying (specific to T2)

- **New clause is placed inside an unrelated clause** (e.g. inside
  definitions, inside the confidentiality obligations clause itself).
- **Cap is wrong** — wrong amount, wrong currency, "lesser of"
  instead of "greater of", fees referenced to the wrong agreement.
- **Any of the three carve-outs is missing.** All three are essential
  to the instruction.
- **Boilerplate placeholder.** `[LIABILITY CAP GOES HERE]` or similar.
- **Agent attempts to delete existing clauses to "make room".** The
  instruction was to ADD a clause, not replace any other clause.
- **Carve-outs present but worded as "includes" rather than
  "excludes".** E.g. "this cap applies to fraud" rather than "this
  cap does not apply to fraud". Reading inverted is a substantive
  legal error.

---

## 3. Transformation 3 — Convert litigation to arbitration

### 3.1 Structural criteria

- **Exactly one clause rewritten** — the jurisdiction clause. The
  governing-law clause must remain untouched (governing law stays
  English law per the instruction).
- **The rewrite is surgical.** Not the entire clause 10b rewritten as a
  single giant del/ins pair; instead:
  - `w:del` spans the court-reference language (e.g. "the exclusive
    jurisdiction of the courts of England and Wales").
  - `w:ins` contains the arbitration language (LCIA Rules, seat London,
    language English).
  - Any linking phrases that stay in place (e.g. "The parties submit
    to...") remain outside the redline blocks.

  Multiple `w:del` / `w:ins` pairs are acceptable and often better
  (separate change for each distinct idea: (i) replace court with
  arbitration; (ii) add seat/language; (iii) add injunctive relief
  carve-out).

- **A new injunctive-relief carve-out is present.** Either:
  - As an amendment to the rewritten clause (new sub-clause or
    additional sentence), OR
  - As a new separate clause, if that's cleaner.

  The carve-out must preserve the parties' ability to seek injunctive
  relief in court — i.e. it says something like "Notwithstanding
  paragraph (a), either party may seek injunctive relief in any court
  of competent jurisdiction for actual or threatened breach of
  confidentiality."

- **Governing law clause is NOT in any `w:del`.** This is a hard
  structural check — extract the governing-law clause from the input,
  confirm it appears verbatim in the output outside any `w:del`.
- **Edit count range: 3–10 tracked changes.** A few for the
  rewrite, one or two for the carve-out. More than 10 indicates
  over-editing.

### 3.2 Substantive criteria

- **Arbitration language is complete and correct:**
  - **Institution: LCIA.** Not ICC, UNCITRAL, CIETAC, etc. The
    instruction names LCIA explicitly.
  - **Rules: LCIA Rules.** The most current LCIA Arbitration Rules by
    default, unless the agent specified a dated edition.
  - **Seat: London.** Both "seat" and "London" must appear.
  - **Language: English.** Must be explicit; arbitration seat London
    defaults to English de facto but the instruction asks for it to be
    specified.
  - **Number of arbitrators, if specified:** not required by the
    instruction, but "one arbitrator" or "three arbitrators" would be
    acceptable if the agent added it; omission is also acceptable.

- **The arbitration language is professionally drafted.** Reads like
  a professional dispute-resolution clause; no fragments like
  "arbitration in London" alone. A full clause should, at minimum,
  name the rules, seat, and language.

- **The injunctive-relief carve-out is correct.** Language like:
  - "Notwithstanding the foregoing, either party may seek injunctive
    relief in any court of competent jurisdiction for actual or
    threatened breach of this Agreement."
  - "Nothing in this clause shall prevent either party from applying
    to a court of competent jurisdiction for injunctive relief or
    equivalent equitable relief to protect its Confidential
    Information."

  A carve-out that mentions "court" but not "injunctive" is incomplete
  (it might allow any court proceedings, which defeats the point).

- **Governing law clause is truly untouched.** Not just "no `w:del` on
  it" — the text in the clean-view output should equal the input's
  text character-for-character (modulo any whitespace normalisation
  from `normalize_docx`).

### 3.3 Disqualifying (specific to T3)

- **Keyword-swap.** Literal find-and-replace of "litigation" with
  "arbitration", or "courts" with "arbitrators", without rewriting the
  mechanics (rules, seat, language). This is the most likely failure
  mode; it's prose that says "arbitration" but describes a court
  proceeding.
- **Governing law changed.** Any edit that touches the governing-law
  clause. This directly contradicts the instruction.
- **No injunctive-relief carve-out.** The instruction explicitly
  requires preserving the parties' ability to seek injunctive relief
  in court for breach of confidentiality. Its absence is a
  substantive failure.
- **Arbitration institution wrong.** The instruction says LCIA. ICC,
  UNCITRAL, etc. is wrong.
- **No seat specified or wrong seat.** London is the instructed seat.
- **Injunctive-relief carve-out is too broad.** If the carve-out
  allows court proceedings for *any* breach (not just
  confidentiality-related injunctive relief), that defeats the
  arbitration clause's purpose. E.g. "Either party may always go to
  court" is too broad.
- **Carve-out inserted but governing law also changed** (double fail).

---

## 4. Evaluation procedure (Sprint 10E)

### 4.1 Per-transformation

1. **Load inputs.** Original NDA file (`nda_{a,b,c}.docx`), client
   identity, transformation instruction.
2. **Run the agent.** Save the output.
3. **Structural pass.** Check §0.1 and §{1,2,3}.1 mechanically.
   Record each criterion as pass / fail / N/A with an OOXML pointer.
4. **Substantive pass.** Read both the annotated view and the clean
   view. Apply §{1,2,3}.2. Record each criterion with a short
   justification.
5. **Disqualifying pass.** Check §0.3 and §{1,2,3}.3. Any hit →
   verdict is "not lawyer-shape".
6. **Write verdict.** One of:
   - **"Lawyer-shape"** — all structural criteria pass, substantive
     criteria all pass or are minor, no disqualifying hit.
   - **"Close to lawyer-shape, N issues"** — structural pass,
     substantive mostly pass; list the N substantive misses.
   - **"Not lawyer-shape"** — any disqualifying hit, OR structural
     fail, OR ≥3 substantive misses.

### 4.2 Aggregated result for the test battery

Three transformations × three verdicts. Sprint 10E's assessment:

- **3/3 lawyer-shape** — redline-specialist is working; proceed to
  integration tests.
- **2/3 lawyer-shape, 1 close** — material but not blocking; iterate
  on prompt.
- **2/3 lawyer-shape, 1 not** — blocking; the failing transformation
  reveals a gap that needs either a prompt fix or an ADR.
- **0–1 lawyer-shape** — specialist is not ready; significant prompt
  rework needed.

---

## 5. What these criteria DON'T cover

- **Formatting fidelity** beyond the operative edits. If the agent
  preserves the original's bold/italic runs etc., that's great; if it
  doesn't, that's cosmetic and a separate concern. Not disqualifying.
- **Metadata sanitisation.** The `.docx` will still contain Adeu's
  eager comment parts and a UTC timestamp. That's a sanitisation
  concern handled by `adeu.sanitize` at final-export time, not here.
- **Diff against a "ground truth" NDA.** There is no single correct
  mutualised NDA; the criteria above focus on lawyer-shape, not
  identity to a template.
- **Comment quality as legal commentary.** The agent's comments may be
  accurate or misleading; we check quantity and that they are
  substantive, not whether they are sound advice. That's for the human
  reviewer.
- **Ethical / regulatory / jurisdictional soundness.** Out of scope for
  a draft NDA redline. The human reviewer at sign-off stage covers
  this.

---

## 6. Honest-judgement margin

These criteria encode Arturs's stated vision plus Sandbox-Claude's
best reading of English/common-law NDA practice. They will get a real-world test in Sprint 10E; some criteria will survive, some won't, and
the ones that don't will be documented as lessons in the 10E sprint
log. The aim is NOT perfect coverage; the aim is:

- Enough structure that two people looking at the same output agree on
  the verdict.
- Enough specificity that the agent's failure modes show up in the
  criteria rather than in hand-wavy "I don't like this" responses.
- Enough slack that a reasonable drafting choice the agent makes
  doesn't get punished just because the criteria didn't anticipate it.

The **disqualifying criteria** should bear closer scrutiny than the
substantive ones — they're the hard lines. If a criterion is in the
disqualifying list and a reasonable agent output could still hit it,
that criterion is wrong and should move to substantive. Arturs, when
reviewing, should probe §0.3 / §1.3 / §2.3 / §3.3 with particular
care.
