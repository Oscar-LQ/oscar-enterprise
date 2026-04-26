# Sprint 10P — counterparty-response feasibility (read-only Phase 0)

Phase 0 research per Arturs's redirection. The first-pass workflow
landed in 10N/10O (Acme reviews + redlines an NDA before sending);
10P moves to the **counterparty response** workflow where the
counterparty has redlined back at us and we decide what to accept,
counter, comment on, or leave.

The Claude Plugin MCP (`/sandbox/reference-material/claude-plugin-mcp/`,
v2.0.0 of `claude-contract-negotiator`) implements this workflow
end-to-end on a single-model architecture (Claude orchestrates
through tool calls). 10K ported its **first-pass** components only;
counterparty-response was scope-excluded. This note re-reads the MCP
source to extract the architecture for adaptation into Oscar's
planner-executor pattern, and reads installed Adeu 1.3.3 source for
the corresponding API surface.

## §1 — MCP counterparty-response pipeline trace

Three tool layers, all in `src/mcp_server/`:

**Layer 1 — Ingestion (read-only):** `ingest_tools.py:26 ingest_document(file_path: str) -> str` (returns clean + annotated CriticMarkup views) and `ingest_tools.py:57 get_state_of_play(file_path: str) -> str` (returns full `StateOfPlay` JSON via `src/ingestion/state_of_play.py:39 build_state_of_play(file_path: str) -> StateOfPlay`).

**Layer 2 — Atomic actions (granular, one operation each):** `action_tools.py` — five MCP tools:
- `accept_changes(input_path, output_path, change_ids: list[str])` (line 41)
- `counter_propose_changes(input_path, output_path, proposals: list[dict], author_name)` (line 78)
- `add_comments(input_path, output_path, comments: list[dict], author_name)` (line 124)
- `reply_to_comments(input_path, output_path, replies: list[dict], author_name)` (line 171)
- `resolve_comments(input_path, output_path, comment_ids: list[str])` (line 208)

**Layer 3 — High-level pipeline:** `pipeline_tool.py:29 execute_pipeline(input_path, output_path, decisions: list[dict], author_name)`. Body:

```python
parsed = [NegotiationDecision(**d) for d in decisions]
config = AuthorConfig(name=author_name)
result = negotiate(
    input_path=input_path,
    output_path=output_path,
    decisions=parsed,
    author_config=config,
)
return result.model_dump_json(indent=2)
```

The IMPORTANT docstring (`pipeline_tool.py:42-51`) names the strategy choice:

> *Choose the right approach for each change:
> 1. counter_propose: disagree with the substance, layer your redline over theirs. More common in early rounds.
> 2. accept + fresh edits + comment: substantially agree but want to tweak specific words. Signals convergence in later rounds. Always comment that you accepted with amendments.
> 3. pure accept + comment: fully agree, comment "Accepted".
> Calibrate to negotiation stage: counter freely early, bias toward acceptance late. Don't counter just because you'd word it differently — only counter when the substance is wrong.*

This framing (counter early, accept late, calibrate per-stage) is the lawyer-judgement substance the Oscar planner needs to internalise.

**Orchestrator — `src/orchestration/negotiator.py:42 negotiate(...)`:**

```python
def negotiate(
    input_path: str,
    output_path: str,
    decisions: list[NegotiationDecision],
    author_config: AuthorConfig,
    styler: StylerCallback | None = None,
    config: NegotiationConfig | None = None,
) -> NegotiationResult:
    validate_decisions(decisions)
    state = build_state_of_play(input_path)
    actions = convert_decisions_to_actions(decisions)
    result = run_pipeline(input_path, output_path, actions, author_config, styler)
    summary = build_decision_summary(decisions, state)
    return NegotiationResult(
        pipeline_result=result, decisions=decisions, summary=summary, config=config,
    )
```

**Pipeline executor — `src/pipeline/orchestrator.py:42 run_pipeline(...)`:**

```python
validate_docx_path(input_path)
_validate_output_path(output_path)
if not actions:
    shutil.copy2(input_path, output_path); return PipelineResult(...)
state = build_state_of_play(input_path)
validate_actions_upfront(actions, state)
sorted_actions = sort_actions_by_execution_order(actions)
document = Document(input_path)
outcomes = execute_action_groups(document, state, sorted_actions, author_config)
clean_empty_ins_elements(document.element.body)
document.save(output_path)
# optional Styler step + validate_docx_output + summary
```

**Atomic single-pass discipline:** one `Document(input_path)` load, all mutations in memory, one `document.save(output_path)`. No intermediate files. Action execution order is fixed (`pipeline/actions.py:19`):

```python
EXECUTION_ORDER = {"accept": 0, "counter_propose": 1, "add_comment": 2, "reply": 3, "resolve": 4}
```

Accepts run before counter-proposals (so accepts remove markup before counter-proposals target the same regions); comments run after all text edits.

**Counter-propose at OOXML level — the load-bearing detail.** `src/negotiation/counter_propose_inplace.py:42 counter_propose_on_document(document, resolutions, author_config)` routes per-change through `_counter_propose_single` which:
1. Finds the tracked-change element by `ooxml_id` (the stable w:id)
2. Tries surgical word-level diff first via `can_apply_surgical_diff` + `compute_surgical_diffs` for simple single-`w:r` elements; validates that accepted-view matches replacement before applying
3. Falls back to wholesale `counter_propose_insertion` / `counter_propose_deletion` for complex elements

The wholesale primitives (`src/negotiation/counter_propose_helpers.py:41,100`) are direct OOXML construction:

- **`counter_propose_insertion(ins_element, client_author, timestamp, replacement_text, next_id)`** — *"nest w:del inside w:ins, add sibling w:ins"*. For each direct `w:r` child of the counterparty's `w:ins`: deep-copy the run, convert `w:t` → `w:delText`, wrap in a client-attributed `w:del`. Then add a sibling `w:ins` with the replacement text.
- **`counter_propose_deletion(del_element, client_author, timestamp, replacement_text, next_id)`** — *"add w:ins after w:del at correct nesting level"*. Creates a client-attributed `w:ins` with replacement_text and inserts it adjacent to the counterparty's `w:del` (after the wrapping `w:ins` if `w:del` is nested in one).

Both functions allocate unique `w:id` values via `get_max_revision_id(body) + 1` (line 20).

The **layered-redline visual property** falls out of these patterns: the counterparty's `w:ins` stays visible in the document (now containing nested `w:del` runs), and the client's `w:ins` sits as a sibling. A reviewer in Word sees both edits side-by-side in the Review Pane — full audit trail of what counterparty proposed AND what client pushed back.

## §2 — MCP data contracts (verbatim)

**State-of-play shape — `src/models/change.py:19`:**

```python
class TrackedChangeEntry(BaseModel):
    change_id: str                                       # "Chg:N" or "Com:N"
    change_type: Literal["insertion", "deletion", "comment"]
    author: str
    date: str
    party_role: str = "unknown"                          # populated by Claude post-ingestion
    paragraph_context: str                               # the clean paragraph text
    changed_text: str                                    # the inserted/deleted/commented text
    ooxml_id: str = ""                                   # stable w:id for chained-operation anchoring
    replies: list["TrackedChangeEntry"] = []             # threaded comment replies

class StateOfPlay(BaseModel):
    authors: list[AuthorInfo]
    changes: list[TrackedChangeEntry]
    # computed_field: pending_count
```

The dual-ID pattern matters: `Chg:N` is sequential (for the LLM to reference) but **renumbers** after `accept_changes` or `counter_propose_changes` operations (warning explicitly named in `action_tools.py:58-63, 104-110`). `ooxml_id` is the stable w:id and is the recommended anchor for chained operations and for `add_comments` after preceding accepts. *"After accept_changes or counter_propose_changes, Chg:N IDs are renumbered. Use ooxml:NNN anchors (from the ooxml_id field in get_state_of_play output) to avoid comments landing on the wrong clause."* (`action_tools.py:140-143`)

**Decision shape — `src/orchestration/decision.py:18`:**

```python
class NegotiationDecision(BaseModel):
    change_id: str                                       # "Chg:N" or "Com:N"
    action: Literal[
        "accept", "counter_propose", "comment",
        "reply", "resolve", "no_action",
    ]
    replacement_text: str = ""                           # required for counter_propose
    comment_text: str = ""                               # for comment / reply / accept-with-comment
    reasoning: str = ""                                  # audit trail
    # field_validator enforces change_id starts with "Chg:" or "Com:"
```

**Action discriminated union — `src/pipeline/actions.py:140`:**

```python
NegotiationAction = Union[
    AcceptAction,            # action_type="accept", change_id (Chg:)
    CounterProposeAction,    # action_type="counter_propose", change_id (Chg:), replacement_text (non-empty)
    AddCommentAction,        # action_type="add_comment", anchor_id, comment_text
    ReplyAction,             # action_type="reply", comment_id (Com:), reply_text
    ResolveAction,           # action_type="resolve", comment_id (Com:)
]
```

`NegotiationDecision` is the LLM-facing layer (verb-flavoured, includes `reasoning`); `NegotiationAction` is the pipeline-facing layer (discriminated union, validated by Pydantic). `convert_decisions_to_actions(decisions)` in `src/orchestration/decision_helpers.py` is the seam that maps one to the other.

**Per-decision result shapes — `src/models/{accept,counter_proposal,comment}.py`:**

```python
# accept.py
class AcceptedChange(BaseModel): change_id, change_type, text
class AcceptResult(BaseModel): accepted_changes: list[AcceptedChange]; validation_warnings: list[str] = []

# counter_proposal.py
class CounterProposedChange(BaseModel): change_id, original_text, replacement_text
class CounterProposalResult(BaseModel): counter_proposals: list[CounterProposedChange]; validation_warnings: list[str] = []

# comment.py
class AddedComment(BaseModel): anchor_id, comment_text, comment_id
class FailedComment(BaseModel): anchor_id, comment_text, reason
class AddCommentResult(BaseModel): added_comments: list[AddedComment]; failed_comments: list[FailedComment] = []
class CommentReply(BaseModel): comment_id, reply_text
class ReplyResult(BaseModel): replies: list[CommentReply]
class ResolvedThread(BaseModel): comment_id, root_comment_id
class ResolveResult(BaseModel): resolved_threads: list[ResolvedThread]
```

Partial-success is normal (e.g. anchor becomes invalid after a preceding accept). Failed items are returned in their own field rather than aborting the batch.

## §3 — Adeu 1.3.3 counterparty-response API surface

`adeu/models.py:70` — the `DocumentChange` discriminated union:

```python
class AcceptChange(BaseModel):
    type: Literal["accept"] = Field("accept", description="Must be 'accept' to finalize a tracked change.")
    target_id: str = Field(..., description="The full ID string from the document text (e.g. 'Chg:12').")
    comment: Optional[str] = Field(None, description="Optional rationale.")

class RejectChange(BaseModel):
    type: Literal["reject"] = Field("reject", description="Must be 'reject' to revert a tracked change.")
    target_id: str = Field(..., description="The full ID string from the document text (e.g. 'Chg:12').")
    comment: Optional[str] = Field(None, description="Optional rationale.")

class ReplyComment(BaseModel):
    type: Literal["reply"] = Field("reply", description="Must be 'reply' to respond to a comment.")
    target_id: str = Field(..., description="The full ID string from the document text (e.g. 'Com:5').")
    text: str = Field(..., description="The content of the reply body.")

DocumentChange = Annotated[Union[AcceptChange, RejectChange, ReplyComment, ModifyText], Field(discriminator="type")]
```

`adeu/redline/engine.py:653` — `process_batch`:

```python
def process_batch(self, changes: List[DocumentChange]) -> dict:
    """
    Processes a unified batch of actions and edits safely.
    Actions are applied first, the Virtual DOM map is rebuilt, and then text edits are validated and applied.
    """
    self.skipped_details = []
    actions = [c for c in changes if isinstance(c, (AcceptChange, RejectChange, ReplyComment))]
    edits = [c for c in changes if isinstance(c, ModifyText)]
    applied_actions, skipped_actions = 0, 0
    if actions:
        applied_actions, skipped_actions = self.apply_review_actions(actions)
        if edits:
            self.mapper._build_map()
            self.clean_mapper = None
    if edits:
        errors = self.validate_edits(edits)
        if errors:
            raise BatchValidationError(errors)
    applied_edits, skipped_edits = 0, 0
    if edits:
        applied_edits, skipped_edits = self.apply_edits(edits)
    return {
        "actions_applied": applied_actions, "actions_skipped": skipped_actions,
        "edits_applied": applied_edits, "edits_skipped": skipped_edits,
        "skipped_details": self.skipped_details,
    }
```

`adeu/redline/engine.py:1128` — `apply_review_actions`:

```python
def apply_review_actions(self, actions: List[Union[AcceptChange, RejectChange, ReplyComment]]) -> tuple[int, int]:
    # For each action: dispatches to _accept_change / _reject_change / _reply_to_comment based on isinstance
    # Strips "Chg:" / "Com:" prefix to get bare target_id
    # Tracks resolved_history so paired del+ins from same revision count once
    # Returns (applied, skipped)
```

The two-phase atomic batch (actions before edits, mapper rebuilt between) matches MCP's execution-order discipline at a different granularity.

**Crucial gap: Adeu has NO counter_propose primitive.** The DocumentChange union is `accept | reject | reply | modify`. To do counter-propose using only Adeu, you would compose:
1. `RejectChange(target_id="Chg:N")` — reverts the counterparty's edit, REMOVING it from the document
2. `ModifyText(target_text=<original text now restored>, new_text=<your replacement>)` — applies your own edit as a fresh client-attributed change

This is not equivalent to MCP's `counter_propose`. MCP keeps the counterparty's `w:ins` visible (now containing nested `w:del` runs) AND adds a sibling client-attributed `w:ins` — a layered redline that preserves the audit trail of what the counterparty originally proposed. Adeu's reject+modify removes the counterparty's edit entirely; no visual record remains in the document body that the counterparty ever proposed it.

For commercial negotiation review where partners want to **see** the back-and-forth in the document (not just in version history), this matters. Word's "show original markup with markup" view shows MCP-style layered redlines clearly; Adeu's reject+modify reads as if the counterparty never made the proposal.

## §4 — Implication for Oscar adaptation

### What becomes the planner's job

Read the state-of-play (per-change list with Chg:N / Com:N IDs, change_type, author, paragraph_context, changed_text, ooxml_id) plus the partner's counterparty-round brief (which positions to soften, which to fight, which to accept), and emit a list of `NegotiationDecision`-shaped instructions — one per change in the state-of-play, including `no_action` for changes it judges to leave alone. Same `preserve` field discipline from 10O extends naturally: when counter-proposing, `preserve` lists qualifiers from the original draft that the counter-proposal must keep.

The planner's load-bearing reasoning is the strategy framing the MCP docstring calls out (`pipeline_tool.py:42-51`): per-change choice between counter-propose, accept-with-comment-and-fresh-edits, pure-accept-with-comment, or no-action — calibrated to the negotiation stage. This is genuine lawyer judgement and is the Pro-tier vs non-Pro-tier question 10P should keep open (separately from the planner-executor architecture question).

### What becomes the executor's job

Take ONE `NegotiationDecision` and apply it via the appropriate Adeu primitive (or via Oscar-side counter-propose helper if that becomes a port — see §4 architectural choice below). One executor call per decision. The executor receives:
- The change being responded to (verbatim from state-of-play including `ooxml_id` for stable anchoring)
- The planner's decision (`action`, `replacement_text` if counter-propose, `comment_text` if relevant, `reasoning`)
- The planner's `preserve` list if applicable (relevant for counter-propose with substantive replacement)

For pure `accept` / `reject` / `reply` / `resolve`, the executor doesn't need an LLM call at all — the operation is mechanical. **A real architectural simplification vs 10O:** the planner's decision is sufficient for pure mechanical actions; only `counter_propose` and complex `comment` / `reply` text actually need the executor LLM call to draft replacement text or comment text. 10O ran an executor call per instruction; 10P could run executor calls only for the subset of decisions that need text-drafting.

### Infrastructure Oscar needs that 10N/10O didn't have

1. **State-of-play extraction.** 10N/10O start from a blank NDA and produce first-pass redlines. 10P needs the inverse: read a `.docx` that has tracked changes in it (the counterparty's response) and structure them per-change for the planner. This requires porting (or substantially reimplementing) MCP's `src/ingestion/` modules: `state_of_play.py`, `state_of_play_helpers.py`, `comment_loader.py`, `author_extractor.py`, `reply_attachment.py`, `sdt_unwrapper.py`, `annotated_helpers.py`, `clean_extractor.py`, `validation.py`. These walk the OOXML using Adeu's `iter_document_parts` / `get_visible_runs` / `get_paragraph_prefix` and produce the `TrackedChangeEntry` list. None of this exists in Oscar today.

2. **Counterparty NDA fixture.** The test input is a tracked-changed `.docx` we received from the counterparty. We need to manufacture one. Two viable approaches:
   - **(a)** Take 10N/10O's `nda-output.docx` (which already has Acme's tracked changes) and rename the author to "Counterparty Counsel" — treat that as the counterparty's response to a hypothetical Acme draft. Easiest to set up but the redlines will read as Acme-positions-from-the-counterparty-side, which is not realistic for a counter-position test.
   - **(b)** Hand-author a `build_counterparty_input.py` that takes a clean NDA and applies tracked-change edits matching what a counterparty would push back with on Acme's first-round redlines (e.g. liability cap LOWER, mutuality narrowed back, arbitration replaced with Singapore SIAC instead of LCIA London). This is the realistic test condition; ~60-90 min of work to author.
   - The brief should pick one; (b) gives a sharper substantive test, (a) gives a faster mechanical test.

3. **Counter-propose primitive — architectural decision needed.** Two paths:
   - **Path A — port MCP's counter-propose helpers.** `src/negotiation/counter_propose_helpers.py` (~190 lines, direct OOXML construction) plus `counter_propose_inplace.py` (~180 lines, surgical-then-wholesale dispatch) plus `counter_propose_surgical.py` (word-diff path). Port effort: ~1 day. Gives full layered-redline visibility. Adds another batch of "private OOXML manipulation" code to Oscar — same upgrade-brittleness flag as the existing `pipeline.py` already has against Adeu private surfaces (recorded in `sprint-10O/pipeline.py` docstring; flagged for 10P+ refactor).
   - **Path B — accept Adeu's reject+modify pattern.** Compose two Adeu primitives per counter-proposal. No port required. Loses layered-redline visibility — partners see only the final-state of the rejection and the new client edit, not the counterparty's original proposal alongside.
   - The brief should pick one or surface as a Phase 1 design question. Path B is faster to ship; Path A is closer to MCP's production-validated shape and is what real commercial negotiation review expects in Word.

4. **Decision schema with preserve-list extension.** `NegotiationDecision` from MCP plus 10O's `preserve` field for counter-proposed positions where qualifier preservation matters. Schema sketch:
   ```
   {
     "change_id": "Chg:N" | "Com:N",
     "action": "accept" | "counter_propose" | "comment" | "reply" | "resolve" | "no_action",
     "replacement_text": "<for counter_propose>",
     "comment_text": "<for comment / reply / accept_with_comment>",
     "reasoning": "<lawyer judgement explanation>",
     "preserve": ["<phrases from the change's original context that the counter-proposal must keep>"],
     "preserve_from": "counterparty_change" | "original_draft"
   }
   ```
   The `preserve_from` discriminator names whether the preserved phrases come from the counterparty's proposed text or from the original draft text the counterparty modified — important when counter-proposing a counterparty insertion vs counter-proposing a counterparty deletion.

5. **`partner_brief` for the counterparty round.** The Acme counterparty-round brief is a different artefact from 10N's first-pass brief. It's positions like *"the counterparty's liability cap of GBP 50,000 is too low — push back to GBP 100,000 or carve out specific heads;* *accept their three-year survival but insist on indefinite for trade secrets;* *their move to court litigation is unacceptable, defend the LCIA arbitration we proposed."* The planner reads this brief plus the state-of-play, decides per change.

### What 10P does not need to revisit

- Adeu version (1.3.3 stays).
- pipeline.py inline-path or upgrade-brittleness flag (still relevant; not in scope to fix).
- Executor model (MiniMax-M2.7 stays — same as 10N/10O).
- chat_model env-prefix pattern (unchanged).
- Metadata-capture helper (already wired into 10O's run.py; 10P inherits).
- planner_prompt.txt's general structure — the `preserve`/`cross_clause_notes` shape adapts to the counterparty-response context with field renames, not architectural changes.

### Open questions for the brief

The brief that follows this Phase 0 will need to settle:

- **Counterparty fixture choice:** rename 10N's output (option 2a) or hand-author counter-positions (option 2b)?
- **Counter-propose primitive:** port MCP's helpers (option 3a) or compose Adeu reject+modify (option 3b)?
- **Planner model tier:** GPT-5.5 non-Pro continues from 10O (sufficient if architecture closes the new gaps), or jump straight to GPT-5.5 Pro for the counterparty-response work given lawyer-judgement weight (the original 10P-as-tier-bump motivation now applies to a different test)?
- **Two-hypothesis structure for the SPRINT_LOG entry:** what's being tested independently and how do outcomes A/B/C diagnose?

These questions inform the brief; the brief is a separate exercise per Arturs's directive.

---

## §5 — Counter-propose primitive verification (Phase 0.5)

Per Arturs's behavioural-rules update: **silent rejection is forbidden** (`RejectChange` is structurally excluded from the planner's decision schema; disagreement must be expressed as counter-proposal preserving the layered audit trail). Phase 0.5 verifies whether Adeu 1.3.3's existing primitives produce the layered visibility shape MCP's `counter_propose_helpers.py` was designed for, OR whether the MCP helpers must be ported.

### Method

Built a synthetic tracked-changed `.docx` with one paragraph and one counterparty-attributed insertion:

```
The cap on liability shall be [Counterparty Counsel inserted: "GBP 50,000"].
```

The counterparty's `w:ins` carries `w:author="Counterparty Counsel"` and `w:id="100"`. Acme's counter-position is "GBP 100,000". Acme runs as `author="Acme Counsel"`. Two compositions tested:

- **Composition A** — `RejectChange(target_id="Chg:100", comment="Disagree with the cap level")` followed by `ModifyText(target_text="shall be ", new_text="shall be GBP 100,000", comment="Counter-propose GBP 100,000 instead")` in one `process_batch` call. Tests the *literal* reject-then-modify pattern §3 named.
- **Composition B** — `ModifyText(target_text="GBP 50,000", new_text="GBP 100,000", comment="Counter-propose GBP 100,000")` alone, no `RejectChange`. Tests whether Adeu's word-diff path produces layered output when targeting text *inside* a counterparty's `w:ins`.

Verification artefacts saved to this directory for Arturs to inspect in Word:
- `sprint-10P-counter-propose-verification-input.docx` — synthetic input
- `sprint-10P-counter-propose-verification-A-reject-plus-modify.docx` — Composition A output
- `sprint-10P-counter-propose-verification-B-modify-only.docx` — Composition B output

### Composition A result — total visibility loss

`process_batch` returned `{"actions_applied": 1, "actions_skipped": 0, "edits_applied": 1, "edits_skipped": 0}`. Output XML (paragraph body):

```xml
<w:r><w:t>The cap on liability shall be </w:t></w:r>
<w:ins w:id="101" w:author="Acme Counsel" w:date="...">
  <w:r><w:t>GBP 100,000</w:t></w:r>
</w:ins>
<w:r><w:t>.</w:t></w:r>
```

The counterparty's `w:ins[author="Counterparty Counsel"]` is **gone entirely**. Search results from the inspection script:

```
output w:ins count: 1 | w:del count: 0
  w:ins[id=101] author='Acme Counsel' content='GBP 100,000' nested_w:del=0
all w:t text in output: 'The cap on liability shall be GBP 100,000.'
all w:delText text in output: ''
does 'GBP 50,000' appear ANYWHERE in output? False
```

A reviewer opening this in Word sees only "Acme Counsel inserted GBP 100,000". No record that the counterparty ever proposed GBP 50,000 — the audit trail of the counterparty's position is destroyed. **`RejectChange` literally removes the counterparty's tracked-change element from the document body** before `ModifyText` runs (`process_batch` semantics: actions before edits, with mapper rebuild between).

This is the hard fail Arturs's behavioural rule 1 was screening for. Composition A cannot be used.

### Composition B result — partial visibility, with attribution leakage

`process_batch` returned `{"actions_applied": 0, "edits_applied": 1}`. Output XML (paragraph body, namespaces stripped for readability):

```xml
<w:r><w:t>The cap on liability shall be </w:t></w:r>
<w:ins w:id="100" w:author="Counterparty Counsel" w:date="2026-04-26T...">
  <w:r><w:t>GBP </w:t></w:r>
</w:ins>
<w:commentRangeStart w:id="1"/>
<w:del w:id="101" w:author="Acme Counsel" w:date="...">
  <w:r><w:delText>50,000</w:delText></w:r>
</w:del>
<w:ins w:id="102" w:author="Acme Counsel" w:date="...">
  <w:r><w:t>100,000</w:t></w:r>
</w:ins>
<w:commentRangeEnd w:id="1"/>
<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="1"/></w:r>
<w:r><w:t>.</w:t></w:r>
```

What Adeu's word-diff did:
- `target_text="GBP 50,000"` matched inside the counterparty's `w:ins`
- Word-diff identified "GBP " as common prefix (preserved); "50,000" as the differing tail
- The "GBP " portion **stayed inside the counterparty's original `w:ins`** — attribution preserved
- The "50,000" portion was **emitted as a fresh `w:del[author="Acme Counsel"]`** (containing `w:delText`) — counterparty attribution LOST
- The replacement "100,000" was emitted as a fresh `w:ins[author="Acme Counsel"]` — correct
- The Comment field on `ModifyText` produced a `commentRangeStart` / `commentRangeEnd` pair anchored around the del+ins region — comment visibility works

A reviewer in Word sees:
- Counterparty inserted "GBP " (preserved attribution)
- Acme deleted "50,000" (← but the counterparty was the one who proposed "50,000" — Acme didn't *delete* it, Acme is *rejecting* it; the document misattributes the original authorship)
- Acme inserted "100,000"

**The visibility is partial: anywhere the counter-proposal happens to share words with the counterparty's text, those words keep counterparty attribution; anywhere it differs, the differing portion gets re-attributed to Acme.** For a clean word-swap this is mostly fine; for a substantive position swap (where the counterparty's full text differs from the client's full counter), most of the counterparty's authorship is lost in the resulting `w:delText` — which renders as Acme-attributed strikethrough, not as counterparty-attributed-then-struck-through.

### MCP's layered shape for comparison

What MCP's `counter_propose_insertion` (`src/negotiation/counter_propose_helpers.py:41`) would produce on the same input:

```xml
<w:r><w:t>The cap on liability shall be </w:t></w:r>
<w:ins w:id="100" w:author="Counterparty Counsel" w:date="...">
  <w:del w:id="N" w:author="Acme Counsel" w:date="...">
    <w:r><w:delText>GBP 50,000</w:delText></w:r>
  </w:del>
</w:ins>
<w:ins w:id="N+1" w:author="Acme Counsel" w:date="...">
  <w:r><w:t>GBP 100,000</w:t></w:r>
</w:ins>
<w:r><w:t>.</w:t></w:r>
```

Reading: counterparty's `w:ins` wraps an Acme `w:del` containing the FULL counterparty-original "GBP 50,000". Word renders this as "Counterparty Counsel inserted ~~GBP 50,000~~" (struck through by Acme) followed by "Acme Counsel inserted GBP 100,000". Both authors present, full attribution preserved end-to-end.

### Conclusion

Per Arturs's verification rule (*"If layered visibility fails: port MCP's counter_propose_helpers.py (~190 LoC) into Oscar"*):

**Layered visibility fails on both compositions tested. Port MCP's `counter_propose_helpers.py` into Oscar** for use as the executor's counter-propose primitive. The 10P brief should scope the port: ~190 LoC for the wholesale primitives (`counter_propose_insertion` + `counter_propose_deletion` + `get_max_revision_id` + `_create_tracked_change` + `_create_run_with_text` + `_convert_run_text_to_del_text`), plus optional ~150 LoC for the surgical word-diff variant if narrow within-clause counters are wanted. The wholesale primitives alone are sufficient for the behavioural-rule-1 requirement.

The port adds another batch of "private OOXML manipulation" code to Oscar — same upgrade-brittleness flag as `pipeline.py` already carries against Adeu private surfaces (recorded in `sprint-10O/pipeline.py` docstring; flagged for 10P+ refactor). 10P's port would extend that flag. Both private-surface batches should eventually be refactored onto Adeu's public surface — but Adeu doesn't expose a counter-propose primitive today, so the refactor depends on Adeu adding one (an upstream feature request worth flagging in Adeu's GitHub if it isn't already).

**Composition B is *not nothing.*** For pure word-swap counter-proposals (where counterparty's text and client's text share most tokens), Composition B preserves attribution on the shared tokens and only re-attributes the differing portion. If Arturs's review of `sprint-10P-counter-propose-verification-B-modify-only.docx` finds the partial-attribution shape acceptable for a meaningful subset of counter-proposals (and the 10P planner can route narrow word-swaps to ModifyText-only and substantive-position swaps to the ported MCP primitive), Composition B + Path A together produce a hybrid that minimises private-OOXML surface area while still delivering full layered visibility where it matters most.

The brief should pick the architecture: pure Path A (port MCP, use it for all counter-proposals), or hybrid (port MCP for substantive position swaps, route narrow word-swaps through Composition B).
