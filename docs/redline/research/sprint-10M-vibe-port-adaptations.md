# Sprint 10M — Vibe Legal Redliner port adaptations: research note

This note is the cross-track durable artefact of Sprint 10M's Phase 1
research. It survives regardless of the sprint's outcome. Future
redline or CoSec sprints that consider porting another working redliner
against Adeu can refer here instead of re-extracting the material.

Written per CLAUDE.md § Cross-Version Porting Research — when a sprint
ports a pattern whose source depends on a third-party library, Phase 1
must verify contract compatibility against the library version currently
in use. Section 3 carries the verification.

Upstream investigation of Vibe Legal Redliner (`docs/redline/research/
vibe-legal-redliner-investigation.md`, commit 38a6a45) established
the mechanism at a high level. This note focuses on what changes during
the port — the three categories of adaptation required, named at the
file-level granularity the port needs.

---

## 1. Vibe source reads: files in full

All paths relative to `/sandbox/reference-material/vibe-legal-redliner/`.

- `src/utils/ai-bundle.js` (680 lines) — LLM prompt assembly, HTTP
  request, response parsing (4-layer fallback), edit validation
- `src/app.js` (720 lines, first 220 read in full, rest summary-skimmed) — UI
  driver, `processDocument` orchestration
- `src/offscreen.js` (207 lines, full) — Pyodide bootstrap, Python
  bridge, `extract-text` / `apply-edits` message handlers
- `src/config.js` (lines 1–164, incl. `DEFAULT_PLAYBOOKS`) — provider
  catalogue + shipped example playbooks
- `python/pipeline.py` (965 lines, key functions read in full:
  `prepare`, `apply_edits`, `_apply_edit_with_word_diff`, `_diff_words`,
  `_build_diff_elements`, `_deduplicate_edits`, helpers)
- `python/doc_analyser.py` (lines 1–120, the `build_context_header`
  public entry)
- `python/adeu/VERSION` — `0.6.7`

Everything cited below is read from these files; nothing is paraphrased
unless explicitly flagged.

---

## 2. The prompt (Vibe source verbatim)

### 2.1 System prompt assembly

`ai-bundle.js:614`:

```javascript
system: AI_BASE_PROMPT + AI_ANALYSIS_INSTRUCTIONS,
```

### 2.2 Persona — `AI_BASE_PROMPT` (ai-bundle.js:25–26, verbatim)

```
You are a senior commercial lawyer conducting a thorough redline review. You analyze contracts against playbook rules to identify both missing provisions (GAPs) and misaligned language (MISALIGNMENTs), then produce precise edits.
Return ONLY a valid JSON object. No markdown, no explanation, no code blocks.
```

Two lines total. No Green/Amber/Red-zone framework (unlike CPM's
`AUTHORITY.md`); no commercial-solicitor persona body text.

### 2.3 Structured reasoning — `AI_ANALYSIS_INSTRUCTIONS` § Step 1 (ai-bundle.js:34–76, verbatim)

```
## Step 1: Structured Reasoning (MANDATORY)

You MUST complete the following analysis BEFORE generating edits. Your reasoning MUST be returned as a structured object (not a plain string).

### Document Scan
Read the entire contract. If a DOCUMENT STRUCTURE ANALYSIS and PARAGRAPH MAP appear at the top of the contract text, use them. If not, determine the structure yourself: what clauses exist, whether numbering is automatic (Word styles) or manual (typed), and the clause hierarchy.

### Rule Extraction
Read the playbook carefully. Extract every distinct rule or position it contains. Count them. Each rule becomes one entry in your analysis array — no exceptions.

### Classification (MANDATORY — every rule must appear)
For EACH rule extracted from the playbook:
1. Name the rule (what the playbook requires)
2. Find the corresponding contract clause (or note "None — missing")
3. Classify as MISALIGNMENT, GAP, ADEQUATE, or FLAGGED
4. State what action you took (edit generated, new clause inserted, no edit, or flagged)
5. Explain why in one sentence

Status definitions:
- **MISALIGNMENT**: Contract addresses this but differs from playbook → surgical edit generated
- **GAP**: Contract does not address this at all → new clause inserted
- **ADEQUATE**: Contract already meets playbook intent → no edit needed
- **FLAGGED**: Requires human judgment (e.g., deleting entire clause, commercial decisions) → flagged for review

MANDATORY: If the playbook contains 12 rules, your analysis array must contain 12 entries. Silent omissions are not acceptable. If you considered a rule and decided not to act, you must still include it as ADEQUATE or FLAGGED with an explanation.
```

The four-state classifier is the prompt's load-bearing decomposition
mechanism. GAP/MISALIGNMENT/ADEQUATE/FLAGGED is applied per-rule, and
each non-ADEQUATE rule gets at most one edit attached.

### 2.4 Output schema (ai-bundle.js:78–106, verbatim)

```
## Output Format
Return a JSON object with this exact structure:
{
  "reasoning": {
    "document_summary": "Brief description: document type, parties, key terms",
    "playbook_rules_found": 12,
    "analysis": [
      {
        "rule": "Name of the playbook rule/position",
        "contract_clause": "Clause X(y) or 'None — missing'",
        "status": "MISALIGNMENT | GAP | ADEQUATE | FLAGGED",
        "action": "What was done (e.g., 'Narrowed scope to 12 months', 'No edit', 'Inserted new clause')",
        "explanation": "Why — what the document says vs what the playbook requires"
      }
    ]
  },
  "edits": [
    {
      "rule": "Name of the playbook rule this edit addresses",
      "edit_type": "GAP or MISALIGNMENT",
      "target_text": "exact text to find in the document",
      "new_text": "replacement text (empty string to delete)",
      "comment": "brief explanation referencing the playbook rule"
    }
  ],
  "summary": "brief summary of changes (1-2 sentences)"
}

The analysis array must have one entry per playbook rule. playbook_rules_found must equal analysis.length.
```

The edit shape adds `rule` + `edit_type` on top of CPM / Adeu 1.1.0's
`{target_text, new_text, comment}`. Both extra fields are dropped at the
pipeline.py boundary (see §4 below — `DocumentEdit(target_text=...,
new_text=...)` ignores them).

### 2.5 Edit Precision Rules + WRONG/RIGHT examples (ai-bundle.js:133–190, verbatim)

```
## Edit Precision Rules (CRITICAL)

### Surgical Precision — change ONLY what the playbook requires
- Make ONLY the changes justified by the playbook. Do not "improve", "clean up", or "modernise" surrounding text.
- Preserve sentence structure. If the playbook requires changing "exclusive" to "non-exclusive", edit that one word — do not rewrite the entire clause.
- When adding new language to an existing clause (e.g., adding a carve-out, a proviso, or extending a definition), INSERT at the right point. Include the anchor text + your addition. Do NOT delete and rewrite the whole clause.
- Do not modify whitespace characters (tabs, spaces, extra line breaks) unless the edit substantively requires it. Whitespace-only changes produce confusing visual noise in track changes.
- Never include ** or __ formatting markers in target_text or new_text.

### Insertion Rules (CRITICAL for GAP edits)
- Never delete existing adequate text to make room for new insertions. When inserting new clauses, anchor to the END of the preceding clause and append using \n. The original clauses must remain untouched in the redline.
- When inserting a new sub-clause (e.g., adding 1(d) after 1(c)), anchor to the end of the preceding sub-clause and append. Do NOT delete and reinsert the preceding text — this creates visual noise (a strikethrough and reinsertion of identical words).
- Never produce an edit where target_text and new_text differ only in whitespace. If your only change would be adding or removing spaces, tabs, or line breaks, skip that edit entirely.
- When modifying a sentence, ensure your target_text includes ALL the text that needs to change. If you are replacing the end of a sentence, include everything from your edit point through to the period. Do not leave orphaned words from the original text.

### WRONG vs RIGHT Examples

MISALIGNMENT — WRONG (rewriting a whole clause):
  target_text: "The Receiving Party shall keep all Confidential Information strictly confidential and shall not disclose it to any third party"
  new_text: "The Receiving Party agrees to maintain the confidentiality of all Confidential Information received from the Disclosing Party and shall not disclose such information to any third party without prior written consent"
  (This rewrites the entire sentence when only the consent requirement needed adding)

MISALIGNMENT — RIGHT (surgical insertion):
  target_text: "shall not disclose it to any third party"
  new_text: "shall not disclose it to any third party without the prior written consent of the Disclosing Party"
  (Targets only the specific phrase that needs the addition)

WRONG — rewriting a clause that already achieves the playbook's intent:
  target_text: "keep information confidential using reasonable measures"
  new_text: "maintain the confidentiality of information using commercially reasonable security measures"
  (Same meaning, different words — no edit needed)

RIGHT — no edit produced (the clause already achieves the playbook's intent)

GAP — RIGHT (inserting a missing clause):
  edit_type: "GAP"
  target_text: "and shall provide written certification of such destruction within 7 days of the request."
  new_text: "and shall provide written certification of such destruction within 7 days of the request.\n\nCompelled Disclosure\n\nIf the Receiving Party is required by law, regulation, or court order to disclose any Confidential Information, it shall (to the extent legally permitted) give the Disclosing Party prompt written notice and cooperate to limit the scope of disclosure."
  comment: "GAP: Playbook requires a compelled disclosure provision — no such clause exists in this document."
  (Anchors to the end of a nearby clause and appends the new provision using \n for paragraph breaks)

WRONG — deleting an existing clause to insert new content before it:
  target_text: "9. This Agreement constitutes the entire agreement between the parties..."
  new_text: "9. Nothing in this Agreement shall be construed as granting any licence... 9A. [remedies clause]... 9B. This Agreement constitutes the entire agreement..."
  (This deletes the original clause 9 and recreates it later — produces an alarming strikethrough of the entire clause)

RIGHT — anchoring to the clause BEFORE the insertion point:
  target_text: "The parties submit to the exclusive jurisdiction of the English courts."
  new_text: "The parties submit to the exclusive jurisdiction of the English courts.\n\n8A. Nothing in this Agreement shall be construed as granting any licence..."
  (Inserts new clauses AFTER the preceding clause, leaving all existing clauses untouched)

WRONG — renumbering all clauses after an insertion:
  Multiple edits changing "5.", "6.", "7." to "6.", "7.", "8."
  (Never renumber existing clauses)

RIGHT — using sub-numbering for inserted clauses:
  "4A." inserted between clauses 4 and 5
```

The load-bearing WRONG/RIGHT pair for anchor-preservation is the second
pair (MISALIGNMENT) — `new_text` literally starts with a verbatim copy
of `target_text` and only appends. CPM's SKILL.md §D1 has analogous
examples (10K research note §3.5 quotes them) but does not enforce the
"new_text begins with target_text" pattern as concretely.

The insertion-anchor example at the bottom uses the jurisdiction
sentence as a GAP anchor — that is the same sentence 10F–10L has been
targeting for MISALIGNMENT. Vibe's own examples do not demonstrate
MISALIGNMENT on this sentence.

### 2.6 Numbering Rules, Track Change Awareness, CriticMarkup (ai-bundle.js:191–221)

Numbering rules (191–200): dynamic guidance keyed to the
DOCUMENT STRUCTURE ANALYSIS header produced by `doc_analyser`. Auto vs
manual numbering discipline.

Track Change Awareness (202–209): teaches the reviewing-lawyer frame —
*"A redline with 5 precise word-level changes is far more useful to a
reviewing lawyer than 2 whole-clause rewrites"* (line 207), *"Heavy
edits (deleting and reinserting 30+ words) produce cluttered, hard-to-
review documents"* (line 208).

CriticMarkup (211–221): instructs the model on how to read prior-round
tracked changes (`{--del--}`, `{++ins++}`, `{>>comment<<}`). Not
load-bearing for a clean NDA.

### 2.7 User prompt template (ai-bundle.js:615–625, verbatim)

```javascript
user: `CONTRACT:
${contractText}

---

PLAYBOOK RULES:
${playbookText}

---

Analyze the contract above against the playbook rules. You MUST address EVERY rule in the playbook — extract each rule, find the corresponding contract clause, classify it, and explain your decision. Your analysis array must have one entry per playbook rule with no omissions. Then generate edits for every MISALIGNMENT and GAP. Return the complete JSON with reasoning and edits.`
```

`${contractText}` is the output of `pipeline.prepare(bytes,
clean_view=False)`, which prepends `doc_analyser.build_context_header`
to the extracted contract text (pipeline.py:193–200, verbatim):

```python
if not clean_view:
    try:
        from doc_analyser import build_context_header
        context_header = build_context_header(bytes(docx_bytes))
        extracted = context_header + "\n\n---\n\nCONTRACT TEXT:\n\n" + extracted
    except Exception as e:
        print(f"[VL-DEBUG] doc_analyser failed (non-fatal): {e}")
```

`build_context_header` emits four sections (doc_analyser.py:56–93):
`DOCUMENT STRUCTURE ANALYSIS:`, `AVAILABLE STYLES:`,
`NUMBERING RULES FOR THIS DOCUMENT:`, `PARAGRAPH MAP:`.

---

## 3. Adeu version-gap analysis (per CLAUDE.md § Cross-Version Porting Research)

**Vibe bundles Adeu `0.6.7`** (`python/adeu/VERSION`). Oscar runs
`adeu==1.1.0` (Sprint 10B installation; confirmed via
`python -c "import adeu; print(adeu.__version__)"`).

Sprint 10K's research note §5 established the one behaviour-visible
change between Adeu 0.7.x (CPM's target) and 1.1.0: `DocumentEdit` was
renamed to `ModifyText` as part of a `DocumentChange` union in v0.9.0.
Field names (`target_text`, `new_text`, `comment`), PrivateAttrs
(`_match_start_index`, `_active_mapper_ref`), and
`RedlineEngine.apply_edits` / `process_batch` signatures are unchanged.
Vibe's 0.6.7 bundle uses the same `DocumentEdit` name as CPM's 0.7.x
target; the same one-class rename applies.

### 3.1 Every Vibe `adeu.*` symbol checked against 1.1.0

| Vibe's usage | Adeu 1.1.0 reference | Action |
|---|---|---|
| `from adeu.models import DocumentEdit` (pipeline.py:25) | `adeu/models.py:16 class ModifyText(BaseModel)` — same fields; `target_text` (24), `new_text` (32), `comment` (41), `_match_start_index` (47), `_active_mapper_ref` (49) | translate import |
| `DocumentEdit(target_text=..., new_text=...)` at pipeline.py:229, 558, 617, 861 (5 call sites including `_delegate_with_match` proxy constructor) | `ModifyText(target_text=..., new_text=...)` | translate 5 constructors |
| `from adeu.ingest import _extract_blocks` (pipeline.py:24) | `adeu/ingest.py:58 def _extract_blocks(container, comments_map, clean_view: bool)` | no change |
| `from adeu.redline.comments import CommentsManager` (pipeline.py:26) + `extract_comments_data()` call | `adeu/redline/comments.py:41 class CommentsManager`, `:427 def extract_comments_data` | no change |
| `from adeu.redline.engine import RedlineEngine` (pipeline.py:27) + `RedlineEngine(stream, author=...)` | `adeu/redline/engine.py:144 def __init__(self, doc_stream: BytesIO, author: str = "Adeu AI")` | no change |
| `from adeu.redline.mapper import DocumentMapper` (pipeline.py:28) + `DocumentMapper(engine.doc, clean_view=True)` | `adeu/redline/mapper.py` — same constructor | no change |
| `from adeu.utils.docx import create_element, iter_document_parts` (pipeline.py:29) | `adeu/utils/docx.py:30 def create_element(name: str)`, `:322 def iter_document_parts(doc: DocumentObject)` | no change |
| `engine._create_track_change_tag("w:del"\|"w:ins")` (pipeline.py:483, 498, 712) | `adeu/redline/engine.py:118 def _create_track_change_tag(self, tag_name: str, author: str = "")` — `author` defaults so 1-arg calls remain valid | no change |
| `engine.apply_edits([edit])` — delegation path for edge cases (pipeline.py:764, 795, 799, 811, 620) | `adeu/redline/engine.py:655 def apply_edits(self, edits: List[ModifyText]) -> tuple[int, int]` — same return shape | no change |
| `engine.save_to_stream()` (pipeline.py:257) | `adeu/redline/engine.py:925 def save_to_stream(self) -> BytesIO` | no change |
| `engine.mapper`, `engine.clean_mapper`, `engine.doc` (many sites) | public attrs (Sprint 10L §2 already verified) | no change |
| `mapper.find_match_index(target_text)` (pipeline.py:768, 774) | `adeu/redline/mapper.py:492 def find_match_index` | no change |
| `mapper.find_target_runs_by_index(start_idx, match_len)` (pipeline.py:802) | `adeu/redline/mapper.py:573 def find_target_runs_by_index` | no change |
| `mapper.get_context_at_range(start_idx, start_idx + match_len)` (pipeline.py:792) | `adeu/redline/mapper.py:671 def get_context_at_range` | no change |
| `mapper._build_map()` (pipeline.py:901) | `adeu/redline/mapper.py:51 def _build_map` | no change — Vibe flags this as "fragile coupling"; remains the same symbol in 1.1.0 |
| `mapper.spans` (via `PlainTextIndex`, pipeline.py:60) | public list attr (Sprint 10L §2 already verified) | no change |
| `edit._match_start_index`, `edit._active_mapper_ref` set on proxy (pipeline.py:618–619) | `ModifyText._match_start_index: Optional[int] = PrivateAttr` (47), `_active_mapper_ref: Optional[DocumentMapper] = PrivateAttr` (49) | no change except class name |

### 3.2 Translation summary

`from adeu.models import DocumentEdit` → `from adeu.models import ModifyText` (pipeline.py:25) plus the five `DocumentEdit(...)` constructor call sites renamed to `ModifyText(...)`. Every other Vibe usage of Adeu passes through to 1.1.0 unchanged.

The `DocumentEdit → ModifyText` idiom is established on Oscar main from
Sprint 10E (`sprint-10e/run.py:88`) and extended in 10K/10L; 10M
inherits that pattern.

---

## 4. Orchestration shape (Vibe source read)

**One LLM call per document against the entire playbook.** Data flow:

1. Browser (`app.js::processDocument`): read `.docx` bytes from File
   API → send to offscreen via Chrome runtime message `extract-text`.
2. Offscreen (`offscreen.js::extractText`) → Pyodide:
   `pipeline_prepare(doc_bytes, clean_view=False)`.
3. `pipeline.prepare` creates `RedlineEngine(stream, author)`,
   normalises via `_extract_blocks`, prepends
   `doc_analyser.build_context_header` when `clean_view=False`.
   Returns contract text + header as one string.
4. Back in the browser: `analyzeContract({provider, apiKey, model,
   contractText, playbookText})` (app.js:131) → `sendRequest` (one
   call) → `parseAIResponse` (4-layer fallback) → `validateEdits`
   (filter + trim + defaults + reasoning-key alt-name restructure).
5. Offscreen receives `apply-edits` message → `pipeline_apply(edits_json,
   fallback_bytes, polish_formatting)`.
6. `pipeline.apply_edits` loops edits sorted longest-target-first,
   calls `_apply_edit_with_word_diff` per edit, delegates to
   `engine.apply_edits([edit])` on edge cases.
7. Output bytes returned to JS → `state.review.result`.

No planner/executor split, no two-LLM pattern, no per-clause LLM loop.
Single call; Python iterates post-reply.

### 4.1 Edit dicts at the Python boundary lose metadata

`pipeline.py:228–231`:

```python
edits = [
    DocumentEdit(target_text=e.get("target_text", ""), new_text=e.get("new_text", ""))
    for e in edits_data
]
```

The `rule`, `edit_type`, `comment` fields the LLM produces never enter
Adeu's edit objects. `comment` is silently dropped; Vibe does not
attach Word comments. The LLM's `reasoning` object never leaves the JS
layer (stored in `state.review.reasoning` for UI display).

Oscar's port preserves this — we capture `reasoning.analysis` to
`classifications-{model}.json` for diagnostics, but do not route it
into Adeu.

### 4.2 Per-edit Adeu invocation surface

Vibe does NOT route through `engine.process_batch` (it does not exist
in bundled 0.6.7, and 1.1.0's version isn't invoked here either). The
per-edit path (`_apply_edit_with_word_diff`, pipeline.py:751–906) uses:

1. `mapper.find_match_index(target_text)` → 3-layer fallback
   (full → clean → PlainTextIndex)
2. `mapper.get_context_at_range(start, end)` — delegate to engine if
   match is inside w:ins
3. Delegate to `engine.apply_edits([edit])` if `new_text=""` (pure deletion)
4. `mapper.find_target_runs_by_index(start, match_len)` → list of runs
5. Delegate if runs span multiple paragraphs
6. `_strip_formatting_markers` + `_strip_redundant_clause_number`
7. Split `new_text` on `\n` — first line for inline diff, rest for new paragraphs
8. `_diff_words(runs_plain_text, first_line)` — tokeniser `r'\S+|\s+'`,
   Unicode-char token encoding, `diff_main` + `diff_cleanupSemantic`
9. `verify_reconstruction` — delegate to engine on mismatch
10. `_build_diff_elements(engine, diffs, char_format_map)` — builds
    `w:ins`/`w:del`/`w:r` via `engine._create_track_change_tag`
11. Direct DOM surgery — `parent.insert()` + `parent.remove()`
12. `_insert_new_paragraphs` for multi-line `new_text`
13. `mapper._build_map()` — private rebuild after DOM surgery

Sprint 10L §4 already established that Adeu 1.1.0's `trim_common_context`
fires at the `engine.apply_edits([edit])` delegation path (engine.py:751)
but returns `(0, 0)` on the 10K inputs. Vibe's inline path sidesteps
`trim_common_context` entirely; delegation paths inherit it.

---

## 5. Playbook format

Vibe's playbook is a **free-form plaintext string** (`state.js` stores
it as `playbook.playbookText`; `ai-bundle.js:621` inlines it into the
user prompt). Format observed across the three shipped examples in
`src/config.js:7–41, 48–89, 96–138`:

- Intro paragraph: "Review this {type} for {posture}. Focus on:"
- Numbered rules: "N. TITLE IN CAPS" followed by indented dashed bullets
- No schema validation, no priorities, no cross-references, no
  categories

Count heuristic at `ai-bundle.js:628–632` logs `playbookLines =
playbookText.split('\n').filter(l => l.trim().length > 0).length`
for telemetry only — not used for validation.

A single-rule playbook is valid and minimal in this format. The LLM is
told *"If the playbook contains 12 rules, your analysis array must
contain 12 entries"* (ai-bundle.js:58) — with one rule, the analysis
array has one entry.

### 5.1 Playbook content for 10M (Arturs-approved)

```
Review this NDA focusing on dispute resolution:

1. DISPUTE RESOLUTION
   - Disputes arising out of or in connection with this Agreement shall be resolved by binding arbitration, not by the courts
   - Arbitration shall be conducted under the LCIA Rules
   - Seat of arbitration: London
   - Sole arbitrator
   - Language of arbitration: English
   - The arbitral award shall be final and binding on the parties
   - The governing-law provision (laws of England and Wales) shall be preserved unchanged
```

**Deviation from Vibe's typical production usage.** This expresses
target prose rather than client positions — closer to a transformation
instruction than a playbook rule. Vibe's production usage is
multi-rule, with rules expressed as commercial positions (e.g., "Cap
liability at reasonable amount"), not transformation scripts. The
single-rule transformation-prose format is used here for direct
comparability with 10F–10L in the nine-sprint table; the five LCIA
elements and the governing-law preservation are named explicitly because
verify_output already checks for them. Noted as an intentional
departure from Vibe's design envelope, not a change to Vibe's code or
prompt.

---

## 6. Substrate-forced port adaptations

### 6.1 JavaScript runtime → Python runtime

| Vibe JS | Oscar Python replacement | File |
|---|---|---|
| `ai-bundle.js::sendRequest(config, prompt)` — fetch to provider | `chat_model.invoke([SystemMessage, HumanMessage])` via `get_chat_model(env_prefix="OSCAR_LLM_REDLINE_EXECUTOR")` (chat_model.py:95) | `run.py` |
| `ai-bundle.js::analyzeContract({provider, apiKey, model, contractText, playbookText})` | Python `analyze_contract(contract_text, playbook_text, chat_model)` | `run.py` |
| `ai-bundle.js::parseAIResponse(content)` — 4-layer fallback | Verbatim-ported Python equivalent | `response_parser.py` |
| `ai-bundle.js::validateEdits(parsed)` | Verbatim-ported Python equivalent | `response_parser.py` |
| `ai-bundle.js::buildProviderConfig`, `PROVIDER_PRESETS`, `REQUEST_FORMATS` | **Not ported** — Oscar's existing chat-model seam handles provider configuration (ADR 008, 011) | — |
| `ai-bundle.js::enforceRateLimit` — 10/60s sliding window | **Not ported** — single-invocation per run | — |

### 6.2 Browser/Pyodide runtime → CPython

| Vibe | Oscar | Note |
|---|---|---|
| `pipeline.py` in Pyodide | `pipeline.py` in CPython | pure Python, lxml / python-docx / diff-match-patch / adeu all in requirements.txt |
| `doc_analyser.py` in Pyodide | `doc_analyser.py` in CPython | pure lxml + stdlib |
| `styler.py` in Pyodide | **Not ported** (polish_formatting=False) | Documented deviation — Vibe's styler is ~800 lines of deterministic visual post-processing (numbering overlaps, bold fixes, spacing). No diagnostic value for 10M's question; candidate for future integration in 10N+ if Outcome A or B lands |
| Module-level `_engine` / `_original_bytes` state (pipeline.py:31–32) | Kept verbatim — no functional change in single-process CPython | Pyodide-reload-safety is vestigial on CPython but keeping the pattern preserves faithfulness |
| Browser `arrayBuffer()` / `downloadFile` | `Path.read_bytes()` / `Path.write_bytes()` | `run.py` |
| `print("[VL-DEBUG] ...")` | Kept verbatim | Silence structlog around the call via 10E's established preamble |

### 6.3 Provider routing

Oscar's `chat_model.py` has `minimax` and `openrouter` provider
factories (ADR 008). Vibe has `gemini` (direct) and `openrouter`.
MiniMax is not in Vibe's shipped catalogue; Gemini is routable via
OpenRouter (`google/gemini-*-flash` model slug).

Per-run config:
- Run 1: `OSCAR_LLM_REDLINE_EXECUTOR_PROVIDER=minimax, MODEL=MiniMax-M2.7, API_KEY=<from .env>`
- Run 2 (conditional): `OSCAR_LLM_REDLINE_EXECUTOR_PROVIDER=openrouter, MODEL=google/gemini-2.5-flash` (with `google/gemini-2.0-flash-001` as fallback if the 2.5 slug is not routable). No new factory, no new env-var triples.

### 6.4 Adeu version translation

Per §3 — `DocumentEdit → ModifyText`. One import + five constructors
in `pipeline.py`.

---

## 7. What this research tells us (and does not)

### Tells us

- Vibe's pipeline is mechanically identical to CPM's diff substrate
  (same `diff_cleanupSemantic`, same tokeniser, same `(runs_plain_text,
  new_text)` diff inputs), with Vibe additionally applying the word-
  diff inline via direct DOM surgery rather than routing through a
  high-level batch API.
- Adeu 1.1.0 is contract-compatible with Vibe's usage with a single
  class rename (`DocumentEdit → ModifyText`). Everything else is
  identical in both name and signature between 0.6.7 and 1.1.0.
- Vibe's prompt teaches anchor-preservation explicitly (MISALIGNMENT-
  RIGHT at ai-bundle.js:155–158 — `new_text` begins with `target_text`)
  and playbook-coverage structure (MANDATORY classification per rule).
  These are absent from CPM's Step D1 in the shape Vibe teaches.
- The playbook format is plaintext, not YAML/JSON/schema-validated.
  Minimum valid content is whatever the LLM can parse as distinct
  rules.
- Vibe's pipeline drops the LLM's `rule`, `edit_type`, `comment`, and
  `reasoning` metadata before reaching Adeu — the LLM's cognitive work
  is recorded in the UI, not in the document's tracked changes.

### Does not tell us

- Whether Vibe's prompt produces narrow edits on MiniMax — this is the
  Phase 3 question.
- Whether Vibe's prompt produces narrow edits on a transformation (as
  opposed to its production use of MISALIGNMENT-shape rule-coverage)
  where the replacement has no natural anchor shared with the target —
  this is the Outcome C diagnostic in the plan.
- Whether the Vibe styler (deliberately not ported) contributes to the
  visual quality of Vibe's output such that Word-review acceptability
  depends on it. Styler-skip is a documented deviation for this sprint.

---

## 8. Pointers

- Plan file (local to session): `/sandbox/.claude/plans/sprint-10M-vibe-legal-redliner-port.md`
- Upstream investigation: `docs/redline/research/vibe-legal-redliner-investigation.md` (commit 38a6a45)
- Prior CPM/Adeu version checks: `docs/redline/research/sprint-10k-claude-plugin-mcp-port.md` §5, `docs/redline/research/sprint-10L-port-feasibility.md` §1
- Adeu 1.1.0 source (read): `/sandbox/reference-material/adeu/src/adeu/`
- Vibe source (read): `/sandbox/reference-material/vibe-legal-redliner/`
- Adeu installed: `adeu==1.1.0` (Sprint 10B)
- diff-match-patch installed: `diff-match-patch==20241021` (Sprint 10J)
- Run artefacts will land on feature branch `sprint-10M-vibe-legal-redliner-port` under `src/redline/experiments/sprint-10M/`.
