# Sprint 10P — MCP port targets (Phase 0 inventory)

Phase 0 deliverable per the brief. Locates the Claude-Plugin-MCP source
files Oscar will port for 10P's counterparty-response pipeline, names
their dependencies and LoC, and maps each `NegotiationDecision` action
in the planner schema to either a ported MCP primitive or an
Adeu-native primitive. Surface this note to Arturs before Phase 1
begins.

Source repo trace: `/sandbox/reference-material/claude-plugin-mcp/`
(claude-contract-negotiator v2.0.0). All paths in §2–§4 are relative
to `claude-plugin-mcp/src/` unless otherwise stated.

Adeu version trace: installed package is **adeu==1.3.3** (verified via
`adeu.__version__` in the venv). `requirements.txt` on main still
pins **adeu==1.1.0** — the 10N upgrade landed on the feature branch
but the requirements.txt bump never reached main; the SPRINT_LOG
entry on main describing the bump is therefore inaccurate about
requirements.txt state. 10P should fold the requirements.txt bump
into Phase 1's branch (mechanical).

---

## §1 — Port surface summary

10P ports three logically distinct surfaces from MCP into Oscar:

1. **Counter-propose primitives** — the core OOXML construction
   surface for layered tracked changes. Phase 0.5 already verified
   this port is mandatory (Adeu's `RejectChange + ModifyText` and
   `ModifyText`-alone compositions both fail the layered visibility
   shape).

2. **State-of-play extraction** — read a tracked-changed `.docx`,
   produce a structured per-change list with `Chg:N` / `Com:N` IDs.
   Adeu's read primitives (`adeu.utils.docx.iter_document_parts`,
   `get_visible_runs`, `get_paragraph_prefix`, `get_run_text`) cover
   the document-walking layer; the change-enumeration and
   classification logic must be ported from MCP.

3. **Comment-attaching primitives** — **NEW finding for the brief.**
   Adeu 1.3.3's `DocumentChange` discriminated union is
   `accept | reject | reply | modify`. There is no native
   "add a standalone comment to a tracked change" primitive, and
   `AcceptChange.comment` is vestigial (Sprint 10C finding —
   verified in current source: `adeu/models.py:55` declares the
   field but the engine does not act on it). Per Arturs's
   behavioural rule 4 ("accept with a comment, not silently"),
   every accept decision in 10P emits a comment, so comment-attaching
   infrastructure is a mandatory port surface — not optional. The
   Phase 0/0.5 feasibility note did not surface this because rule 4
   was added in the 10P brief after the feasibility note was
   committed.

Total approximate port LoC across all three surfaces: **~1,400 LoC**
across **~14 files** (with adaptation; see §6 budget). The brief's
"~190 LoC" figure refers narrowly to the counter-propose wholesale
primitives (`counter_propose_helpers.py` alone). The full port
surface required to honour the decision schema and behavioural rules
is materially larger — but it composes cleanly out of MCP files
that are themselves small (each well under the 200-line CLAUDE.md
ceiling) and have minimal external dependencies.

---

## §2 — Counter-propose port (mandatory)

| File (MCP path) | LoC | Internal deps | Port destination |
|---|---|---|---|
| `negotiation/counter_propose_helpers.py` | 192 | (none) | `src/redline/lib/counter_propose_helpers.py` (verbatim) |
| `negotiation/counter_propose_inplace.py` | 183 | counter_propose_helpers, counter_propose_surgical, accept_helpers (find only), timestamp, results | `src/redline/lib/counter_propose_inplace.py` |
| `negotiation/counter_propose_surgical.py` | 271 | counter_propose_helpers, pipeline.word_diff | `src/redline/lib/counter_propose_surgical.py` |
| `pipeline/word_diff.py` | 115 | (none) | `src/redline/lib/word_diff.py` |
| `negotiation/accept_helpers.py` (find_tracked_change_element only, lines 20-39) | 20 | (none) | fold into `src/redline/lib/counter_propose_helpers.py` |
| `negotiation/timestamp.py` | 42 | (none) | `src/redline/lib/timestamp.py` |
| `pipeline/results.py` (ActionOutcome only) | 22 | (none) | fold into `src/redline/lib/results.py` (or reuse 10O's edit-result conventions — see §7 Q1) |

**Counter-propose-helpers external deps:** `python-docx` (pinned 1.2.0
in Oscar), `lxml` (pinned 6.1.0). Both already present.

**Counter-propose-surgical external deps:** `diff-match-patch` (pinned
20241021 in Oscar, used by 10L's post_processor.py and 10J's
diff-based pipeline). Already present.

**Adeu coupling:** ZERO. The counter-propose primitives operate on
`docx.document.Document` and `lxml._Element` directly. They do not
import any `adeu.*` symbol. Upgrade-brittleness against Adeu is
indirect: the port layers w:ins / w:del elements that Adeu's
mapper and engine read; if Adeu's OOXML expectations shift in a
future release, the port could produce shapes Adeu's read primitives
mis-classify in state-of-play.

**Surgical word-diff variant — recommendation.** Brief frames the
hybrid as "Composition B as optimisation path for narrow word-swaps".
Phase 0.5 verified Composition B is `ModifyText` alone, which has
partial-attribution-loss semantics (counterparty author preserved on
shared tokens, lost on differing portion). MCP's surgical variant
(`counter_propose_surgical.py`) is a different mechanism — it
preserves full counterparty attribution AND produces narrow
word-level diffs by splitting the counterparty's `w:ins` into
fragments at INSERT boundaries. Recommendation: port the surgical
variant (271 LoC) — it gives the layered-visibility behaviour MCP's
production already validates. Leave Composition B as future work
(potentially optional optimisation when partial attribution loss
is acceptable; not 10P scope).

---

## §3 — State-of-play port (mandatory)

| File (MCP path) | LoC | Internal deps | Port destination |
|---|---|---|---|
| `ingestion/state_of_play.py` | 145 | annotated_helpers, author_extractor, comment_loader, reply_attachment, sdt_unwrapper, state_of_play_helpers, validation, models.change | `src/redline/lib/state_of_play.py` |
| `ingestion/state_of_play_helpers.py` | 169 | annotated_helpers, sdt_unwrapper, models.change | `src/redline/lib/state_of_play_helpers.py` |
| `ingestion/sdt_unwrapper.py` | 49 | (none) | `src/redline/lib/sdt_unwrapper.py` |
| `ingestion/annotated_helpers.py` (extract_run_text, extract_del_text only — lines 117-158) | 42 | sdt_unwrapper | fold into `src/redline/lib/state_of_play_helpers.py` |
| `ingestion/comment_loader.py` | 159 | (none — uses python-docx only) | `src/redline/lib/comment_loader.py` |
| `ingestion/author_extractor.py` | 200 | comment_loader, sdt_unwrapper, validation, models.party | `src/redline/lib/author_extractor.py` |
| `ingestion/reply_attachment.py` | 105 | models.change | `src/redline/lib/reply_attachment.py` |
| `ingestion/validation.py` | 53 | (none) | fold into `src/redline/lib/state_of_play.py` (small enough; or keep separate) |
| `models/change.py` | 56 | models.party | `src/redline/lib/state_of_play_models.py` |
| `models/party.py` | 61 | (none) | fold into `src/redline/lib/state_of_play_models.py` |

**Adeu coupling:** state_of_play.py and author_extractor.py import
four symbols from `adeu.utils.docx`:
- `iter_document_parts(document)` — yields header/body/footer parts
- `get_paragraph_prefix(paragraph)` — Markdown heading prefix
- `get_visible_runs(paragraph)` — accepted-view runs
- `get_run_text(run)` — text from a run (handles tab, br, cr)

These are Adeu's PUBLIC surface (declared in the module header per
10C reference). Port can keep these imports unchanged — same mapping
on Adeu 1.3.3 (verified by `head -80` of `adeu/utils/docx.py`).

**Reply-attachment dead-code in 10P input.** 10P-prep's
`nda-output.docx` was inspected mechanically: it contains 12 `w:ins`,
6 `w:del`, **0 comments** (no `word/comments.xml` part, no
`w:commentReference` runs). The reply-attachment module
(`ingestion/reply_attachment.py`) and the threaded-comment loading
in `comment_loader.py:load_comments_extended` are non-load-bearing
on the 10P input. Port them anyway — keeps state_of_play.py
faithful, future-proofs for inputs that DO have comments, and
the LoC cost is small. Mark them in the port file's docstring as
unexercised by 10P's input fixture.

**State-of-play port simplification — optional.** The author summary
(party.py / author_extractor.py — 261 LoC together) is structured
metadata MCP uses for Claude to assign party roles after ingestion.
Oscar's planner already knows the roles from the brief ("Acme
responds to Zenith"). If we don't need the AuthorSummary surface
for the planner prompt, we can simplify author_extractor.py to a
~30-line author-list extractor (collect unique authors, return list
of names). Recommendation: port faithfully in Phase 1 — the
overhead is small and matches MCP shape; 10Q can simplify if it's
in the way. Surface as Q5 in §7.

---

## §4 — Comment-attaching port (mandatory per behavioural rule 4)

| File (MCP path) | LoC | Internal deps | Port destination |
|---|---|---|---|
| `negotiation/add_comment_helpers.py` | 226 | accept_helpers (find only), reply_helpers (W15_NS, comment_ids_helpers), models.comment | `src/redline/lib/add_comment_helpers.py` |
| `negotiation/add_comments_inplace.py` | 132 | add_comment_helpers, comment_ids_helpers, reply_helpers, timestamp, results, models.author_config, models.comment | `src/redline/lib/add_comments_inplace.py` |
| `negotiation/comment_ids_helpers.py` | 167 | (none — uses python-docx only) | `src/redline/lib/comment_ids_helpers.py` |
| `negotiation/reply_helpers.py` | 289 | comment_ids_helpers (lazy import) | `src/redline/lib/reply_helpers.py` |
| `models/comment.py` (CommentError only) | ~10 | (none) | fold into `src/redline/lib/add_comment_helpers.py` |
| `models/author_config.py` | 62 | (defers to timestamp.py) | `src/redline/lib/author_config.py` |

**Adeu coupling:** ZERO. The comment-attaching primitives operate on
the OPC parts of the `docx.Document` (comments.xml, commentsExtended.xml,
commentsIds.xml, commentsExtensible.xml) directly. They do NOT use
Adeu's `CommentsManager` (which is private surface inside
`adeu.redline.comments`). The port creates the four parts itself if
absent, ensuring Word renders comments correctly.

**Reply-helpers naming.** The file is named `reply_helpers.py` in MCP
because it was originally for threaded reply comments; the helpers
inside (`get_or_create_comments_part`, `allocate_para_id`,
`collect_existing_para_ids`, `get_next_comment_id`) are general OPC
plumbing for ANY comment operation, not reply-specific. Both
add_comment and reply paths import from this file. Keep the MCP
filename for traceability.

**Behavioural-rule-4 implementation shape.** Each "accept" decision
becomes a composite:
1. Apply `AcceptChange(target_id="Chg:N")` via Adeu (removes Zenith
   markup, leaves clean text)
2. Apply standalone Acme comment anchored to that change's *original*
   ooxml_id... but wait — the ooxml_id is gone after AcceptChange
   removes the w:ins/w:del wrapper.

This sequencing problem matches MCP's own `EXECUTION_ORDER`
discipline (`pipeline/actions.py:19`): accepts run BEFORE comments
in MCP's pipeline, and the comment-anchor logic uses the
post-accept text position via text-match
(`anchor_comment_to_text` in `add_comment_helpers.py:58-92`).
Specifically, MCP's accept-with-comment path emits two actions:
`AcceptAction(change_id="Chg:N")` followed by
`AddCommentAction(anchor_id="Chg:N", comment_text="...")`. After
the accept removes the markup, MCP's resolve_add_comment_group
(`pipeline/executor_helpers.py:70-112`) sees `:REMOVED` in the
anchor (sentinel from accept-changes-inplace) and produces a
failed-comment outcome — which means MCP's accept-with-comment is
**broken in the same way** unless the executor receives a
text-match anchor instead of the change_id anchor.

**This is a real issue for Phase 1.** The MCP flow expects the
LLM to emit `AddCommentAction(anchor_id="<paragraph text>")` for
the comment-on-accept case, not `anchor_id="Chg:N"`. Translating to
the 10P decision schema: when the planner emits
`{action: "accept", change_id: "Chg:N", comment_text: "..."}`, the
dispatcher must:
- After the accept resolves, locate the now-clean paragraph by
  using the `paragraph_context` field from the original
  `TrackedChangeEntry` (captured pre-accept in state-of-play)
- Anchor the comment to a text snippet within that paragraph
  (some unambiguous span — possibly the verbatim
  `paragraph_context` itself, or a planner-supplied
  `comment_anchor_text` field)

Surface as Q2 in §7. This is the most architecturally consequential
finding from Phase 0.

---

## §5 — Adeu mapping per `NegotiationDecision` action

The 10P decision schema has six actions: accept, counter_propose,
comment, reply, resolve, no_action. Per Arturs's brief, accept /
reply / resolve / comment use Adeu's native primitives; the brief
also forbids RejectChange (rule 3, structurally excluded from the
schema). Mapping:

| Action | Path | Mechanism |
|---|---|---|
| `accept` | Adeu native + ported comment | `AcceptChange(target_id=Chg:N)` via `RedlineEngine.process_batch`; then post-accept `anchor_comment_to_text` via ported `add_comments_on_document` for the comment that rule 4 mandates |
| `counter_propose` | Ported MCP | `counter_propose_on_document(document, [(entry, replacement_text)], author_config)` — wraps wholesale + surgical paths; comment if any goes through the same post-counter add_comment path as accept |
| `comment` | Ported MCP | Standalone — `add_comments_on_document(document, [(anchor, text, ooxml_id, None)], author_config)`; anchor by ooxml_id of the Zenith change being commented on (no edit applied) |
| `reply` | Adeu native | `ReplyComment(target_id=Com:N, text=...)` via `RedlineEngine.process_batch`. **Dead code on 10P-prep input** (no comments present). Keep the path for future inputs. |
| `resolve` | None | **Adeu has no resolve primitive.** Port MCP's `resolve_inplace.py`+`resolve_helpers` if needed. **Dead code on 10P-prep input** (no comments present). Recommendation: omit from Phase 1; surface as Q3 in §7. |
| `no_action` | None | Skip — entry is preserved in state-of-play but no operation runs. Decision recorded in the audit trail. |

The Adeu native + ported MCP composition runs in two stages:
1. Stage 1: collect all `AcceptChange` actions, apply via
   `process_batch`. Mapper rebuilds. Audit `process_batch` result.
2. Stage 2: collect all counter_propose + comment actions, apply
   via ported helpers on the same in-memory `Document`. Save once.

This matches MCP's `EXECUTION_ORDER` (`pipeline/actions.py:19`):
accepts → counter_proposes → add_comments → replies → resolves.
Oscar's dispatcher in Phase 2 can implement the same ordering with
two batched calls (Adeu process_batch for accepts/replies, then
ported helpers for counter_propose + comment), saving once at the
end.

---

## §6 — External dependencies

All required external packages are already pinned in
`requirements.txt`:
- `python-docx==1.2.0` — used throughout the port for OPC parts and
  Document object
- `lxml==6.1.0` — used by all OOXML manipulation paths
- `diff-match-patch==20241021` — used by `counter_propose_surgical`
  and `word_diff`
- `pydantic` (transitively pinned via Adeu and Deep Agents) —
  TrackedChangeEntry, StateOfPlay, AuthorConfig, NegotiationDecision

**No new pinning required** for the port. Phase 1 should bump
`adeu==1.1.0` → `adeu==1.3.3` in requirements.txt as housekeeping
(installed venv is already at 1.3.3; this is reconciliation, not
an upgrade).

---

## §7 — Architectural decision points for Arturs

These are the questions Phase 0 surfaces before Phase 1 begins.
None block reading the source; all need a decision before the port
goes from research to code.

**Q1 — ActionOutcome reuse vs port.** MCP's `pipeline/results.py`
defines `ActionOutcome` as a thin Pydantic record (action_type,
target_id, status, reason, original_text, new_text, method).
Oscar's 10O `pipeline.py` has its own edit-result conventions
(`edits_applied`, `edits_skipped`, `skipped_details` returned from
`process_batch` per Adeu's contract). Two paths:
- (a) Port `ActionOutcome` verbatim and use it for counter_propose
  and add_comment outcomes; keep Adeu's native dict for accepts /
  replies. Mixed-shape audit trail; minor readability cost.
- (b) Define an Oscar-specific outcome type that wraps both shapes
  uniformly. Cleaner audit trail; more code.
- Recommendation: (a) for Phase 1 simplicity. Surface mixed shapes
  in transcript.txt; refactor in 10Q if it's confusing.

**Q2 — Accept-with-comment anchor mechanism (LOAD-BEARING).** Per
§4, the accept primitive removes the change wrapper, so the comment
cannot anchor by Chg:N or ooxml_id post-accept. The MCP-faithful
path is `anchor_comment_to_text(body, paragraph_text, comment_id)`.
Two paths:
- (a) Use the `paragraph_context` field from the pre-accept
  `TrackedChangeEntry` as the comment anchor text. Word will wrap
  the entire post-accept paragraph with the comment range. Wide
  anchor.
- (b) Have the planner emit a `comment_anchor_text` field with a
  specific phrase from the now-accepted text. Narrow anchor; richer
  prompt; one more field for the planner to drop / hallucinate.
- Recommendation: (a) for Phase 1. The planner already has the
  paragraph_context in state-of-play; using it as anchor is a
  zero-extra-prompt-fields path. If reviewer-experience suffers in
  Word, 10Q switches to (b).

**Q3 — Resolve path scope.** No comments in 10P-prep's input means
`resolve` is dead code in 10P. Port MCP's `resolve_inplace.py`
(estimated ~150 LoC; not yet read in Phase 0) for completeness, or
omit and have the planner emit `resolve` as a no-op?
- Recommendation: OMIT for Phase 1. Schema retains `resolve` for
  future-proofing; dispatcher raises `NotImplementedError` if the
  planner emits one (signal to 10Q that an input with comments
  arrived). Keeps the port surface tight.

**Q4 — Reply path scope.** Same as Q3. No comments in input. But
the Adeu primitive is native (`ReplyComment` — first-class in
DocumentChange union); cost of supporting the path is approximately
one `if` branch in the dispatcher. Recommendation: support it via
Adeu native, even if unexercised by 10P-prep input. Trivial cost.

**Q5 — AuthorSummary scope.** Port MCP's full author_extractor.py
(200 LoC) which produces per-author insertion / deletion / comment
counts plus date ranges, or simplify to ~30-line author-name list?
- Recommendation: faithful port. Cost is small; matches MCP shape;
  state-of-play.json artefact reads more like MCP's for cross-port
  comparison. 10Q simplifies if needed.

**Q6 — Surgical word-diff variant scope.** Port the surgical
variant (271 LoC, splits counterparty's w:ins into fragments at
INSERT boundaries — preserves full counterparty attribution AND
produces narrow word-level diffs)? Or wholesale-only first
(simpler, validated in Phase 0.5)?
- Recommendation: PORT BOTH. The surgical variant is what gives
  MCP's production-validated narrow-edit shape on word-level
  counter-proposals; wholesale alone would force every Acme
  counter-proposal to wrap the entire Zenith change wholesale.
  `counter_propose_inplace.py` already handles routing
  (surgical-when-simple, wholesale-when-complex); porting both
  in one go is cheaper than splitting.

**Q7 — `requirements.txt` adeu pin.** Bump `adeu==1.1.0` →
`adeu==1.3.3` on Phase 1's branch as housekeeping?
- Recommendation: YES. Installed venv is already at 1.3.3 (verified
  via `adeu.__version__`). The 10N feature branch bumped it but the
  bump did not reach main. Phase 1 folds the bump into the
  sprint-10P-counterparty-response branch.

---

## §8 — Upgrade-brittleness flag

The port introduces ~720 LoC of private OOXML construction (counter-
propose helpers + comment-attaching helpers + their adjacent
plumbing) into Oscar's tree. Same shape as the existing 10M-derived
inline path in `sprint-10P-prep/pipeline.py` (and earlier sprints):
the port reaches under Adeu's public surface to the OOXML primitives
directly. Adeu's `DocumentChange` union does not expose `counter_propose`
or `add_comment` natively; if Adeu adds these primitives in a future
release, the port retires and the affected files delete cleanly.

**Defensive flagging convention** (matches `sprint-10P-prep/
pipeline.py:15-50` and 10O's flag in same file):
- Each ported file's module docstring names the source MCP file +
  line range, the Adeu version it was ported against (1.3.3), and
  the upgrade-retirement path.
- Phase 1 closing commit references this section.
- 10P's SPRINT_LOG entry should include a TODO line: "file feature
  request to Adeu (Dealfluence/Mikko Korpela) for native
  counter_propose + standalone-comment primitives". Don't block
  10P on the upstream request.

Private surfaces touched by the port:
- `python-docx`'s OPC internals (`docx.opc.part.XmlPart`,
  `docx.opc.constants.RELATIONSHIP_TYPE`, package serialization
  hooks) — public-ish but internal layout known to shift
- `lxml.etree._Element` — stable public API
- OOXML w:ins / w:del / w:commentReference / w:commentRangeStart
  / w:commentRangeEnd / commentsIds.xml / commentsExtensible.xml
  schemas — Microsoft-specified; structurally stable
- Adeu's `iter_document_parts` / `get_visible_runs` /
  `get_paragraph_prefix` / `get_run_text` from `adeu.utils.docx`
  — declared public per 10C reference; verified present and
  signature-compatible in adeu==1.3.3

---

## §9 — Out of scope for the port

- **MCP's pipeline orchestrator** (`pipeline/orchestrator.py:42
  run_pipeline`). Oscar builds its own dispatcher in Phase 2,
  routing decision-by-decision through Adeu native (accept / reply)
  or ported helpers (counter_propose / comment). MCP's orchestrator
  is built around `NegotiationAction` discriminated union with
  upfront-validation, action-grouping, and id-remapper — Oscar's
  10P dispatcher is simpler because the planner emits decisions
  already validated against state-of-play.

- **MCP's executor + executor_helpers** (`pipeline/executor.py`,
  `pipeline/executor_helpers.py`). Same reason as above — Oscar's
  dispatcher is fresh.

- **MCP's id_remapper** (`pipeline/id_remapper.py`). MCP's
  ooxml_id-bridge pattern is the right abstraction for chained
  operations (accept → comment-on-accepted-text needs the pre-accept
  ooxml_id to find the post-accept paragraph). Oscar's dispatcher
  needs the same bridge but builds it inline from state-of-play.

- **MCP's empty_ins_cleaner** (`pipeline/empty_ins_cleaner.py`).
  Cleanup pass after counter-proposals leave empty `w:ins` wrappers.
  Small (~50 LoC). Port if Phase 2 verification finds zero-width
  artefacts in Word; otherwise omit.

- **MCP's first_pass + first_pass_result + accept_changes**
  (`pipeline/first_pass.py`, `negotiation/accept_changes.py` etc).
  These are the FIRST-PASS workflow (MCP's original Sprint 10K
  research) — already covered by Oscar's existing pipeline for
  10N/10O/10P-prep first-pass redlining.

- **MCP's Styler step** (`pipeline/styler.py`,
  `styler_extraction.py`). Out of scope for 10P; first-pass tracks
  separately if needed.

---

## §10 — Surface to Arturs

Port-targets analysis complete. Phase 0 inventory locates 14
MCP files for porting across counter-propose, state-of-play, and
comment-attaching surfaces, totalling ~1,400 LoC adjusted. The
brief's "~190 LoC" figure was the counter-propose wholesale
primitive subset; Phase 0 surfaces that the comment-attaching
infrastructure (~700 LoC across 4 files) is also a mandatory
port target — driven by behavioural rule 4 ("accept with a
comment, not silently"), which the Phase 0/0.5 feasibility note
predates.

Q2 (accept-with-comment anchor mechanism) is the load-bearing
architectural question for Phase 1 — recommend Q2(a)
(`paragraph_context` as anchor text). Q3 / Q4 / Q5 / Q6 / Q7 have
default recommendations that Arturs can leave as-is unless he
flags otherwise. Q1 is a code-style choice with no functional
impact.

If Arturs approves the inventory (with whatever Q-overrides he
calls), Phase 1 proceeds: branch `sprint-10P-counterparty-response`
off main, fresh; port the 14 files; bump requirements.txt to
adeu==1.3.3; integration-test the counter-propose subset against
Phase 0.5's synthetic input; surface the integration-test artefact
before Phase 2.
