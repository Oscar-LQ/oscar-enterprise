# Vibe Legal Redliner — mechanism investigation

## Purpose

This note characterises Vibe Legal Redliner's redlining mechanism by
reading the source directly, so Sprint 10M can be designed against
what the system actually does rather than against a summary
characterisation. Three prior investigations in the 10F–10L arc were
corrected by source reads (OpenClaw-vs-MiniMax, CPM diff-input
characterisation, and 10L's `diff_cleanupSemantic` finding); this note
continues that pattern against the third working reference system
surfaced in the arc.

## Where the system lives

- Upstream: `https://github.com/sarturko-maker/vibe-legal-redliner`
- Local clone: `/sandbox/reference-material/vibe-legal-redliner/`
- Commit at clone time: `ca35f02b323f6b667537ce8f4d23cc560b646643`
- Licence: MIT (`LICENSE`)
- Distribution: Chrome Manifest V3 extension (v1.2.0 per
  `manifest.json:4`)
- Bundled Adeu version: `0.6.7` (`python/adeu/VERSION:1` — older than
  Oscar's `1.1.0`, and older than the 0.7.x CPM was written against,
  so no `DocumentEdit → ModifyText` rename gap applies here)

## Files read

All paths relative to
`/sandbox/reference-material/vibe-legal-redliner/`.

Full reads:

- `README.md`
- `DEVELOPMENT_LOG.md` (25 ADRs, full)
- `RELEASE_NOTES.md` (v1.2.0)
- `DEPENDENCIES.md`, `SBOM.md`, `manifest.json`, `package.json`
- `src/utils/ai-bundle.js` — LLM prompt + request/response
- `src/offscreen.js` — Pyodide init + message handlers
- `src/app.js` — UI entry point + processing driver
- `src/background.js` — service-worker message router
- `src/config.js` — provider/model catalogue
- `src/state.js`, `src/file-processing.js`, `src/api-handler.js`,
  `src/launcher.js`, `src/trusted-html.js`
- `python/pipeline.py` — full orchestration + custom word-diff engine
- `python/doc_analyser.py` — structural context header builder
- `python/styler.py` — post-processing (deterministic)
- `python/format_extractor.py` — formatting map extractor
- `tests/unit/ai-response-parsing.test.js`
- `tests/unit/model-validation.test.js`
- `app.html`, `sidepanel.html`, `offscreen.html`
- `python/adeu/VERSION`

Skipped: bundled Adeu source under `python/adeu/*.py` (vendored Adeu
0.6.7 that serves as the docx runtime; not Vibe-specific pipeline
code), three remaining `tests/unit/*.test.js` (`escape-html`,
`audit-log`, `rate-limit` — security/infrastructure, not
redlining-pipeline), `docs/index.html`, `docs/disclaimer.html`,
`help.html`, `popup.html`, `privacy-policy.html`, `disclaimer.html`
(UX shells).

---

## Finding 1 — Prompt construction

The LLM prompt is assembled entirely in JavaScript in
`src/utils/ai-bundle.js`.

**System prompt = `AI_BASE_PROMPT` + `AI_ANALYSIS_INSTRUCTIONS`**
(`ai-bundle.js:614`):

```javascript
614:    system: AI_BASE_PROMPT + AI_ANALYSIS_INSTRUCTIONS,
```

### 1.1 Persona (`ai-bundle.js:25–26`, verbatim)

```javascript
25: const AI_BASE_PROMPT = `You are a senior commercial lawyer conducting a thorough redline review. You analyze contracts against playbook rules to identify both missing provisions (GAPs) and misaligned language (MISALIGNMENTs), then produce precise edits.
26: Return ONLY a valid JSON object. No markdown, no explanation, no code blocks.`;
```

### 1.2 Analysis instructions (`ai-bundle.js:28–229`, ~200 lines)

The `AI_ANALYSIS_INSTRUCTIONS` template contains six sections, each
cited verbatim below for its key content.

**Step 1 — Structured Reasoning (mandatory, `ai-bundle.js:34–76`):**

```
34: ## Step 1: Structured Reasoning (MANDATORY)
...
44: ### Classification (MANDATORY — every rule must appear)
45: For EACH rule extracted from the playbook:
46: 1. Name the rule (what the playbook requires)
47: 2. Find the corresponding contract clause (or note "None — missing")
48: 3. Classify as MISALIGNMENT, GAP, ADEQUATE, or FLAGGED
49: 4. State what action you took (edit generated, new clause inserted, no edit, or flagged)
50: 5. Explain why in one sentence
51:
52: Status definitions:
53: - **MISALIGNMENT**: Contract addresses this but differs from playbook → surgical edit generated
54: - **GAP**: Contract does not address this at all → new clause inserted
55: - **ADEQUATE**: Contract already meets playbook intent → no edit needed
56: - **FLAGGED**: Requires human judgment (e.g., deleting entire clause, commercial decisions) → flagged for review
57:
58: MANDATORY: If the playbook contains 12 rules, your analysis array must contain 12 entries. Silent omissions are not acceptable.
```

**Output Format (`ai-bundle.js:78–106`, verbatim JSON schema):**

```
79: Return a JSON object with this exact structure:
80: {
81:   "reasoning": {
82:     "document_summary": "Brief description: document type, parties, key terms",
83:     "playbook_rules_found": 12,
84:     "analysis": [
85:       { "rule": ..., "contract_clause": ..., "status": ..., "action": ..., "explanation": ... }
86:     ]
87:   },
88:   "edits": [
89:     {
90:       "rule": "Name of the playbook rule this edit addresses",
91:       "edit_type": "GAP or MISALIGNMENT",
92:       "target_text": "exact text to find in the document",
93:       "new_text": "replacement text (empty string to delete)",
94:       "comment": "brief explanation referencing the playbook rule"
95:     }
96:   ],
97:   "summary": "brief summary of changes (1-2 sentences)"
98: }
```

**Edit Precision Rules (`ai-bundle.js:133–208`).** This is the
surgical-span discipline. Contains section "Surgical Precision" (136–
141) and "Insertion Rules" (142–147), then WRONG/RIGHT examples
(148–190) in two categories:

- `MISALIGNMENT — WRONG (rewriting a whole clause)` at 150–154
- `MISALIGNMENT — RIGHT (surgical insertion)` at 155–158:

```
155: MISALIGNMENT — RIGHT (surgical insertion):
156:   target_text: "shall not disclose it to any third party"
157:   new_text: "shall not disclose it to any third party without the prior written consent of the Disclosing Party"
158:   (Targets only the specific phrase that needs the addition)
```

Note that `new_text` literally begins with `target_text`. The rule at
`ai-bundle.js:144`:

```
144: - When inserting a new sub-clause (e.g., adding 1(d) after 1(c)), anchor to the end of the preceding sub-clause and append. Do NOT delete and reinsert the preceding text — this creates visual noise (a strikethrough and reinsertion of identical words).
```

And at `ai-bundle.js:146`:

```
146: - When modifying a sentence, ensure your target_text includes ALL the text that needs to change. If you are replacing the end of a sentence, include everything from your edit point through to the period. Do not leave orphaned words from the original text.
```

**GAP — RIGHT example (`ai-bundle.js:167–172`):**

```
167: GAP — RIGHT (inserting a missing clause):
168:   edit_type: "GAP"
169:   target_text: "and shall provide written certification of such destruction within 7 days of the request."
170:   new_text: "and shall provide written certification of such destruction within 7 days of the request.\n\nCompelled Disclosure\n\nIf the Receiving Party is required by law..."
```

Again, `new_text` starts with the full `target_text` and appends. The
anchor is preserved in the replacement.

**Insertion-after-existing-clause example (`ai-bundle.js:179–182`):**

```
179: RIGHT — anchoring to the clause BEFORE the insertion point:
180:   target_text: "The parties submit to the exclusive jurisdiction of the English courts."
181:   new_text: "The parties submit to the exclusive jurisdiction of the English courts.\n\n8A. Nothing in this Agreement shall be construed as granting any licence..."
```

Same pattern — the jurisdiction sentence (which is the 10K
transformation-target for litigation→arbitration in a different
sprint) appears verbatim in Vibe's worked examples, but as a GAP
insertion-anchor, not a MISALIGNMENT transformation target.

**Numbering Rules (`ai-bundle.js:192–200`)** instruct the LLM to
consult the DOCUMENT STRUCTURE ANALYSIS block (Finding 1.4 below) for
auto-vs-manual numbering behaviour.

**Track Change Awareness (`ai-bundle.js:202–209`)** frames the output
for the reviewing lawyer:

```
207: - A redline with 5 precise word-level changes is far more useful to a reviewing lawyer than 2 whole-clause rewrites
208: - Heavy edits (deleting and reinserting 30+ words) produce cluttered, hard-to-review documents
```

**CriticMarkup section (`ai-bundle.js:211–221`)** lets the LLM read
prior-round tracked-changes markup in the contract text.

### 1.3 User prompt (`ai-bundle.js:615–625`, verbatim)

```javascript
615:    user: `CONTRACT:
616: ${contractText}
617:
618: ---
619:
620: PLAYBOOK RULES:
621: ${playbookText}
622:
623: ---
624:
625: Analyze the contract above against the playbook rules. You MUST address EVERY rule in the playbook — extract each rule, find the corresponding contract clause, classify it, and explain your decision. Your analysis array must have one entry per playbook rule with no omissions. Then generate edits for every MISALIGNMENT and GAP. Return the complete JSON with reasoning and edits.`
```

### 1.4 Structural context header prepended to contract text

`contractText` is produced by `python/pipeline.py`'s `prepare`
function, which (when `clean_view=False`, the AI-analysis path)
prepends `doc_analyser.build_context_header` output
(`pipeline.py:193–200`):

```python
193:    if not clean_view:
194:        try:
195:            from doc_analyser import build_context_header
196:            context_header = build_context_header(bytes(docx_bytes))
197:            extracted = context_header + "\n\n---\n\nCONTRACT TEXT:\n\n" + extracted
198:        except Exception as e:
199:            print(f"[VL-DEBUG] doc_analyser failed (non-fatal): {e}")
```

`build_context_header` (`doc_analyser.py:23–95`) emits sections
named in its own code:

```python
57:    sections.append("DOCUMENT STRUCTURE ANALYSIS:")
58:    sections.append(f"- Numbering: {numbering_info['scheme']}")
...
71:        sections.append("AVAILABLE STYLES:")
...
78:    sections.append("NUMBERING RULES FOR THIS DOCUMENT:")
...
92:    sections.append("PARAGRAPH MAP:")
```

The numbering-rules subsection is dynamic —
`doc_analyser.py:79–90` writes different guidance to the LLM based
on whether the document is auto-numbered, manually numbered, or
mixed. The PARAGRAPH MAP (lines 281–343) emits one line per non-empty
paragraph: `[index] StyleName [AUTO-NUMBERED, level N, format]: "text preview"`.

No `persona.md` or `authority.md` equivalent exists — there is no
Green/Amber/Red-zone framework, no Opus-style pre-authorisation step.
All authority-like discipline lives inline in the Edit Precision
Rules.

---

## Finding 2 — Orchestration shape

**One LLM call per document against the entire playbook.**

- JavaScript driver (`src/app.js:131–137`):
  ```javascript
  131:    const aiResponse = await analyzeContract({
  132:      provider: state.settings.provider,
  133:      apiKey: state.settings.apiKey,
  134:      model: state.settings.model,
  135:      contractText,
  136:      playbookText: playbook.playbookText
  137:    });
  ```
  One call, whole contract + whole playbook.
- The call lands in `analyzeContract` (`ai-bundle.js:596–635`) which
  calls `sendRequest` once (`ai-bundle.js:613`) and returns a single
  parsed result. No loop, no per-clause decomposition at JS level.
- `analyzeContract` is called exactly twice in the codebase — once
  in `processDocument` and once in `processBatch` (`app.js:131`,
  `app.js:284`). Batch mode is "one LLM call per file," not "per
  clause" — `processBatch` (`app.js:216–344`) iterates files with a
  2000ms gap between them (`app.js:338–339`) but each file is its
  own single LLM invocation.

**Per-edit iteration happens in Python, not in the LLM call.**
`python/pipeline.py:241–250`:

```python
241:    for orig_idx, edit in indexed:
242:        preview = edit.target_text[:50].replace("\n", " ")
243:        a, _s = _apply_edit_with_word_diff(engine, edit)
244:        if a > 0:
...
```

The LLM returns the full edit list; Python iterates and applies
edits one at a time (sort-by-target-length-descending, line 236,
same discipline as CPM's `apply_edits_surgically`).

There is no planner/executor split, no two-LLM pattern, no
subagent dispatch. One API call. Edits flow strictly: LLM → Python →
OOXML.

---

## Finding 3 — Data contract at the LLM boundary

The LLM returns a JSON object with three top-level keys: `reasoning`,
`edits`, `summary`. Each edit is
`{rule, edit_type, target_text, new_text, comment}`.

The parse path is `parseAIResponse` (`ai-bundle.js:414–466`) →
`validateEdits` (`ai-bundle.js:472–531`). Validation filter at
`ai-bundle.js:474–482`:

```javascript
474:   const validEdits = parsed.edits
475:     .filter(edit => typeof edit.target_text === 'string' && typeof edit.new_text === 'string')
476:     .map(edit => ({
477:       rule: edit.rule || '',
478:       edit_type: edit.edit_type || 'MISALIGNMENT',
479:       target_text: edit.target_text.trim(),
480:       new_text: edit.new_text,
481:       comment: edit.comment || ''
482:     }));
```

Confirmed by unit-test fixture (`tests/unit/ai-response-parsing.test.js:4–13`):

```javascript
 4: const VALID_EDITS_JSON = JSON.stringify({
 5:   edits: [
 6:     {
 7:       target_text: 'unlimited liability',
 8:       new_text: 'liability capped at $1,000,000',
 9:       comment: 'Per playbook section 4.2'
10:     }
11:   ],
12:   summary: 'Added liability cap'
13: });
```

The `target_text`/`new_text`/`comment` triple is the same shape as
CPM's `DocumentEdit`/Adeu 1.1.0's `ModifyText` contract. Vibe adds
two fields on top: `rule` (the playbook-rule name the edit
addresses) and `edit_type: "GAP" | "MISALIGNMENT"` — both visible in
`ai-bundle.js:478` (default `"MISALIGNMENT"`), `ai-bundle.js:527–529`
(GAP/MISALIGNMENT count logging).

The `reasoning` object is parsed but not passed downstream to the
redlining pipeline — it is displayed in the UI
(`app.js:143: state.review.reasoning = aiResponse.reasoning || null`)
and logged (`ai-bundle.js:506–512`). The LLM's reasoning is not fed
back into the Python word-diff.

`parseAIResponse` has four recovery layers for malformed output
(`ai-bundle.js:414–466`): direct parse → trailing-comma fix →
truncation-repair (closes open brackets) → regex rescue (extracts
individual edit objects). This is production-defensive parsing, not
a Vibe-specific mechanism.

---

## Finding 4 — Adeu invocation and the diff layer

**There is an intermediate diff layer between the LLM and the OOXML
apply, and it uses `diff_cleanupSemantic` — the same cleanup pass as
CPM and as Oscar's Sprint 10L port.**

The diff layer lives entirely in `python/pipeline.py`, not in the
bundled Adeu. Vibe **does not** route edits through Adeu's
`process_batch`. It calls Adeu primitives at lower level.

### 4.1 The `_apply_edit_with_word_diff` function (`pipeline.py:751–906`)

This is Vibe's application path per edit. Key data flow:

```python
767:    mapper = engine.mapper
768:    start_idx, match_len = mapper.find_match_index(edit.target_text)
...
771:        # Fallback 1: clean mapper (strips CriticMarkup, keeps ** / _)
772:        if not engine.clean_mapper:
773:            engine.clean_mapper = DocumentMapper(engine.doc, clean_view=True)
774:        start_idx, match_len = engine.clean_mapper.find_match_index(edit.target_text)
...
779:        # Fallback 2: plain-text index (strips ALL virtual spans including ** / _)
781:        pti = PlainTextIndex(engine.mapper)
782:        start_idx, match_len = pti.find_match(edit.target_text)
```

Three-layer matching (mapper → clean_mapper → PlainTextIndex) —
structurally identical to CPM's `find_match_three_layer`. The
`PlainTextIndex` class (`pipeline.py:39–122`) is Vibe-local but
serves CPM's purpose.

```python
802:    target_runs = mapper.find_target_runs_by_index(start_idx, match_len)
...
813:    # 6. Extract plain text from resolved runs
814:    runs_plain_text = "".join(run.text or "" for run in target_runs)
815:
816:    # Issue 1: Strip formatting markers from new_text
817:    clean_new_text = _strip_formatting_markers(edit.new_text)
818:
819:    # Issue 4: Strip redundant clause numbers when paragraph has auto-numbering
820:    parent_p = target_runs[0]._element.getparent()
821:    clean_new_text = _strip_redundant_clause_number(clean_new_text, parent_p)
...
848:        diffs = _diff_words(runs_plain_text, first_line)
```

**Confirmed: the diff inputs are `(runs_plain_text, first_line)` where
`runs_plain_text` is the concatenated `.text` of on-disk runs at the
matched region, and `first_line` is the first line of the cleaned
`new_text`.** This is mechanically identical to the data-flow Oscar's
Sprint 10K data-flow clarification note identified in CPM
(`surgical_edit.py:143`'s `diff_words(runs_plain_text, clean_new_text)`).
The diff side from the document comes from the document; the diff side
from the LLM is `new_text`; `target_text` is a locator.

### 4.2 The cleanup pass (`pipeline.py:306–351`)

```python
306: def _diff_words(old_text, new_text):
...
316:    dmp = diff_match_patch()
...
318:    old_tokens = re.findall(r'\S+|\s+', old_text) if old_text else []
319:    new_tokens = re.findall(r'\S+|\s+', new_text) if new_text else []
...
342:    diffs = dmp.diff_main(old_encoded, new_encoded)
343:    dmp.diff_cleanupSemantic(diffs)
```

Tokeniser `r'\S+|\s+'` (line 318–319) — identical to CPM's tokeniser
(Oscar's 10L research note §3, `word_diff.py:~47`). Unicode-char
token encoding (lines 324–340) — identical to CPM. **Cleanup pass:
`diff_cleanupSemantic` — identical to CPM and to Oscar's 10L port.**
No alternative cleanup pass, no raw-diff-with-filtering, no custom
heuristic.

### 4.3 OOXML construction (`pipeline.py:444–511`)

After the diff produces `(op, text)` segments, Vibe does not route
them through Adeu's `process_batch`. It builds OOXML elements
directly:

```python
483:            del_tag = engine._create_track_change_tag("w:del")
...
498:            ins_tag = engine._create_track_change_tag("w:ins")
```

Then performs DOM surgery in place (`pipeline.py:871–882`):

```python
871:                first_run_elem = target_runs[0]._element
872:                parent = first_run_elem.getparent()
873:                insert_idx = list(parent).index(first_run_elem)
874:
875:                for i, elem in enumerate(new_elements):
876:                    parent.insert(insert_idx + i, elem)
877:
878:                for run in target_runs:
879:                    r_parent = run._element.getparent()
880:                    if r_parent is not None:
881:                        r_parent.remove(run._element)
```

This bypasses Adeu's `apply_edits` / `process_batch` entirely for the
inline case. Adeu is called only when delegation triggers fire:
empty-target (line 764), inside-w:ins (line 795), pure-deletion
(line 799), multi-paragraph span (line 811), reconstruction-mismatch
(lines 857–862). The reconstruction safety check
(`pipeline.py:855–859`) ensures accept-all-changes reproduces
`first_line` byte-for-byte; if not, delegate.

Additional compensation layers that do not exist in 10K's port:

- Tab-to-space normalisation (`_normalize_edit_whitespace`,
  `pipeline.py:543–558`)
- Overlapping-edit deduplication (`_deduplicate_edits`,
  `pipeline.py:561–597`)
- Formatting-marker stripping (`_strip_formatting_markers`,
  `pipeline.py:518–540`)
- Redundant-clause-number stripping when the anchor paragraph has
  `<w:numPr>` (`_strip_redundant_clause_number`, `pipeline.py:623–661`)
- Multi-line new_text handling — first line is an inline edit, rest
  become new paragraphs via direct DOM (`_insert_new_paragraphs`,
  `pipeline.py:664–731`)
- Heavy-rewrite ratio monitor (`_check_rewrite_ratio`,
  `pipeline.py:734–748`) — logs a warning at >70% but still applies.
- Character-level formatting preservation through `_build_char_format_map`
  and `_split_by_formatting` (lines 354–441) for EQUAL and DELETE
  segments — preserves bold/italic across the diff.

### 4.4 Post-processing: `styler.py` (opt-in)

If `polishFormatting` is set, `Styler.run()` (`styler.py:784–839`) runs
a deterministic (no-LLM) second pass over the redlined bytes. Fixes:
manual-numbering overlaps, section-header bold, inline-title bold,
body indentation, double numbering (`3.3.` collisions), paragraph
spacing. Warnings for: list-formatting gaps, clause-sequence anomalies,
section-placement anomalies. `pipeline.py:273–278` uses a two-Styler
pattern — extract reference formats from the `_original_bytes` first,
then apply fixes to the redlined document against those references.

---

## Finding 5 — DEVELOPMENT_LOG content

`DEVELOPMENT_LOG.md` contains 25 ADRs framed as a
"Pre-Release Quality Review" (line 1). Grouped into Priority 1–5 (pre-
push), 6–10 (post-push), Infrastructure (11–15), and Future (16–20),
plus 21–25 continuation. The log is predominantly
security/quality/packaging, not redlining-architecture.

The ADRs that touch redlining-architecture substance:

- **ADR-008 — Pin bundled Adeu engine version.** Sets
  `python/adeu/VERSION` to `0.6.7`; logs it at init in the offscreen
  document. Confirms the bundled Adeu version is load-bearing and
  pinned.
- **ADR-020 — Lazy-load Pyodide on demand** (SUPERSEDED by ADR-025):
  "AI analysis takes 20-60s while Pyodide init takes ~10-15s. By
  starting both concurrently, the engine is typically ready before
  it's needed." Superseded because text extraction now requires the
  engine, forcing eager init.
- **ADR-023 — Document runPythonAsync dynamic execution risk.**
  "The offscreen document calls `pyodide.runPythonAsync()` to execute
  the Adeu redlining engine. This is functionally equivalent to
  `eval()` for Python code… Every Python string passed to
  `runPythonAsync` is hardcoded in `src/offscreen.js`. Contract bytes
  are passed as a binary argument, never interpolated into Python
  source."
- **ADR-025 — Eliminate JS text extraction — use Adeu's full pipeline.**
  This is the only ADR that explicitly touches the prompt. Relevant
  verbatim fragments:

  > The JS `extractTextFromDocx` in `file-processing.js` (~320 lines)
  > duplicated Adeu's `ingest.py` text extraction logic, creating
  > format drift risk. … The JS layer also used "clean view" which
  > hid tracked changes from prior negotiation rounds, preventing the
  > AI from seeing document revision history.
  >
  > The AI prompt was updated with a CriticMarkup awareness section
  > explaining `{--del--}`, `{++ins++}`, `{>>comment<<}` syntax so the
  > AI understands document revision history. Playbook creation uses
  > `clean_view=true` to get clean text without revision markers.

No ADR in the DEVELOPMENT_LOG documents the word-diff pipeline, the
`diff_cleanupSemantic` choice, the prompt's structured-reasoning
framing, the GAP/MISALIGNMENT classification, or the `doc_analyser`
context header. The architectural backbone of the redlining mechanism
is undocumented as ADRs — it arrived before the pre-release review.

`RELEASE_NOTES.md` v1.2.0 ships the headline "Precision redlining:
word-level track changes, document structure awareness, and
post-processing formatting fixes," and specifically attributes:

```
10: - Edits now produce minimal, word-level `w:del`/`w:ins` pairs instead of replacing entire phrases
...
12: - Reconstruction safety check: if word-diff produces incorrect output, falls back to engine's proven path
...
19: - Structured reasoning process: Topic Inventory, Playbook Comparison, Edit Plan, Verification
20: - Playbook positions classified as GAP / MISALIGNMENT / ADEQUATE before generating edits
21: - WRONG/RIGHT examples teach the AI surgical precision over heavy-handed rewrites
```

This is the closest the project comes to an architectural decision
record of the redlining mechanism.

---

## Finding 6 — Model and provider configuration

Two providers shipped (`src/config.js:142–164`, verbatim):

```javascript
142: export const AI_PROVIDERS = {
143:   gemini: {
144:     id: 'gemini',
145:     name: 'Google Gemini',
146:     baseUrl: 'https://generativelanguage.googleapis.com/v1beta',
147:     models: [
148:       { id: 'gemini-2.0-flash-exp', name: 'Gemini 2.0 Flash (Latest)', default: true },
149:       { id: 'gemini-1.5-pro', name: 'Gemini 1.5 Pro' },
150:       { id: 'gemini-1.5-flash', name: 'Gemini 1.5 Flash' }
151:     ],
152:     enabled: true
153:   },
154:   openrouter: {
155:     id: 'openrouter',
156:     name: 'OpenRouter',
157:     baseUrl: 'https://openrouter.ai/api/v1',
158:     models: [
159:       { id: 'google/gemini-2.0-flash-001', name: 'Gemini 2.0 Flash', default: true },
160:       { id: 'anthropic/claude-3.5-sonnet', name: 'Claude 3.5 Sonnet' },
161:       { id: 'openai/gpt-4o', name: 'GPT-4o' }
162:     ],
163:     enabled: true
164:   }
165: };
```

Default model per provider: `gemini-2.0-flash-exp` (Gemini),
`google/gemini-2.0-flash-001` (OpenRouter). Flash-tier by default on
both providers.

A second default-selection path exists for live-detected models
(`src/api-handler.js:6–28`). When the user clicks "Test connection,"
the extension calls the provider's model-list endpoint and picks a
default from what's returned. Gemini branch verbatim
(`api-handler.js:7–24`):

```javascript
 8:   if (provider === 'gemini') {
 9:     const ideal = models.find(m => /2\.5-flash/i.test(m.id) && !GEMINI_EXCLUDE.test(m.id));
10:     if (ideal) {
...
14:     const anyFlash25 = models.find(m => /2\.5-flash/i.test(m.id));
...
19:     const newerFlash = models.find(m => /flash/i.test(m.id) && !/lite|1\.0|1\.5/i.test(m.id));
```

Preference order at live-test time: `2.5-flash` excluding
`lite|preview|image|tts|thinking` → any `2.5-flash` → any Flash
excluding lite/1.0/1.5 → first-in-list. Even though the bundled
default list names 2.0 Flash, live detection upgrades to 2.5 Flash
when available. The "smaller model" Arturs referenced maps to
Gemini Flash 2.0 / 2.5 in practice, and whatever OpenRouter routes
to for that slug at request time.

Request parameters for both providers (`ai-bundle.js:242–265`):

- `temperature: 1.0`
- `maxOutputTokens: 65536` (Gemini) / `max_tokens: 65536` (OpenAI-format)

Rate-limit: 10 requests per 60-second sliding window,
client-side (`ai-bundle.js:572–594`).

---

## Comparison with 10F–10L

Differentiating-mechanism candidates from the brief, evaluated:

| Axis | 10F–10L pipelines | Vibe Legal Redliner | Differs? |
|---|---|---|---|
| Cognitive task framing | Transform-by-instruction (§9 litigation → arbitration) | Compare-against-playbook (each rule classified GAP/MISALIGNMENT/ADEQUATE/FLAGGED) | **Yes** |
| Orchestration granularity | One LLM call (10K), or one-draft + substrate (10J/10L) — all whole-document | One LLM call, whole document against whole playbook | No (both single-call whole-document) |
| Prompt scaffolding | CPM's PERSONA + AUTHORITY + Step A–F + D1 + WRONG/RIGHT (confidentiality-clause examples) | Custom: structured-reasoning requirement, per-rule classification forced, Edit Precision Rules with WRONG/RIGHT (same confidentiality examples plus insertion-anchor and sub-numbering examples), DOCUMENT STRUCTURE ANALYSIS header, CriticMarkup awareness, GAP-vs-MISALIGNMENT distinction | **Yes** |
| LLM output shape | `{edits: [{target_text, new_text, comment}]}` | `{reasoning: {analysis: [...]}, edits: [{rule, edit_type, target_text, new_text, comment}], summary}` — adds reasoning object, per-edit rule attribution, GAP/MISALIGNMENT discriminator | **Yes, additively** |
| Diff substrate | CPM-derived: three-layer matcher, word-token diff, `diff_cleanupSemantic`, per-edit scope `(runs_plain_text, new_text)` | CPM-derived: three-layer matcher (incl. PlainTextIndex), word-token diff (same `r'\S+|\s+'` tokeniser, same Unicode encoding), `diff_cleanupSemantic`, per-edit scope `(runs_plain_text, first_line)` | **No** — mechanically identical except that Vibe splits `new_text` on `\n` and diffs only the first line, new paragraphs go via direct DOM |
| Post-diff cleanup choice | `diff_cleanupSemantic` (10L found this was the load-bearing step that collapsed short shared runs) | `diff_cleanupSemantic` | **No** |
| Model interaction | MiniMax-M2.7 primary; Sonnet 4.6 as 10I reference sub-experiment | Gemini 2.0/2.5 Flash default (on both providers); Claude 3.5 Sonnet and GPT-4o available via OpenRouter | **Yes** |
| Application layer | Adeu 1.1.0 `process_batch` (10K) / direct `ModifyText` batching (10L port) | Direct OOXML DOM surgery via `engine._create_track_change_tag` + `_build_diff_elements`, delegating to Adeu only on edge cases (empty target, pure deletion, multi-paragraph span, reconstruction mismatch, inside-w:ins) | **Yes** |
| Compensation layers | Partially present in 10L (block-grouping, anchor-widening) | Extensive — edit dedup, formatting-marker strip, tab normalise, redundant-clause-number strip (numPr-aware), multi-line new-paragraph path, heavy-rewrite monitor, char-level formatting preservation | **Yes** |
| Post-processing styler | None | Deterministic `styler.py` — numbering overlap fix, section-header bold, inline-title bold, body indent, double-numbering fix, paragraph spacing, sequence and placement warnings | **Yes** |

### The crux

**10L's finding that `diff_cleanupSemantic` collapses short shared
runs is correct, and it applies to Vibe too.** The 10L note's
conclusion — that the narrowness lever must be "upstream of the
mechanism — in the LLM's choice of how much original phrasing to
preserve" — is directly supported by Vibe's source. Vibe's mechanism
is the same mechanism. The difference that makes Vibe produce
lawyer-shape output on Flash-tier is **in the LLM's drafting output
shape**, driven by:

1. **Playbook framing forces per-rule decomposition at the reasoning
   stage.** The LLM produces one analysis entry per playbook rule
   (`ai-bundle.js:58: "If the playbook contains 12 rules, your analysis
   array must contain 12 entries"`), then attaches at most one edit to
   each non-ADEQUATE rule. Decomposition happens by the
   playbook-granularity of the task, not by post-hoc LLM judgement on a
   single transformation.
2. **The WRONG/RIGHT examples teach anchor-preservation explicitly.**
   In both MISALIGNMENT-RIGHT (`ai-bundle.js:155–158`) and GAP-RIGHT
   (`ai-bundle.js:167–172`), `new_text` begins with a verbatim copy of
   `target_text`. When the LLM follows this pattern, the diff between
   `runs_plain_text` and `new_text` has a long shared prefix (or suffix)
   that `diff_cleanupSemantic` preserves rather than collapses. The
   narrowness falls out of the substrate naturally.
3. **"Preserve sentence structure"** is an explicit rule
   (`ai-bundle.js:137`). CPM's Step D1 teaches span-sizing (5–15 word
   targets); Vibe additionally teaches phrase-preservation in the
   replacement. This is the behavioural property 10L's note predicted
   would shift the diff output — and Vibe's prompt teaches it directly.
4. **Structural context from `build_context_header`** reduces the
   LLM's need to reason about document structure (numbering scheme,
   paragraph map) while drafting, which reduces bundling-into-one-wide-
   edit tendencies.

The task framing (Axis 1) is also a substantive difference: Vibe's
production load is "check this contract against this playbook — most
rules will be ADEQUATE, a few will produce surgical edits." Oscar's
10F–10L test case is "perform one specific transformation on §9."
These are different cognitive tasks — Vibe's is rule-coverage,
Oscar's is targeted transformation — and the transformation task may
not naturally produce anchor-preservable edits even under Vibe's
prompt. The litigation-jurisdiction sentence appears verbatim in
Vibe's RIGHT example at line 180, but as an insertion anchor, not
a MISALIGNMENT. Vibe's prompt has not been empirically tested on a
single-clause transformation where anchor-preservation has no
natural handhold.

The model dimension (Axis 7) is a confound this investigation cannot
resolve. Gemini Flash 2.x and MiniMax-M2.7 are not equivalent — Flash
is a low-cost variant of a frontier model family, while MiniMax is a
different model. Whether Vibe's prompt framing transfers to MiniMax is
an open question answerable only by running the prompt on MiniMax.

### What this investigation does and does not tell us

**Tells us.**

- Vibe's diff mechanism is mechanically identical to CPM's and to
  Oscar's 10L port — same tokeniser, same cleanup pass, same per-edit
  data flow `(runs_plain_text, new_text)`.
- The narrowness lever is not the cleanup pass.
- Vibe's prompt teaches anchor-preservation (`new_text` starts with
  `target_text`) via WRONG/RIGHT examples.
- Vibe's task framing is playbook-coverage (GAP/MISALIGNMENT/ADEQUATE)
  with mandatory per-rule analysis, not targeted-transformation.
- Vibe adds a structural-context header to the contract before
  analysis (numbering scheme, paragraph map).
- Vibe runs the pipeline on Gemini Flash 2.0/2.5 by default (both
  providers).
- Vibe uses direct OOXML DOM surgery (not Adeu `process_batch`),
  with Adeu delegated only on edge cases.
- Vibe has an extensive deterministic post-processing layer (`styler.py`).

**Does not tell us.**

- Whether Vibe's prompt framing produces narrow edits on MiniMax —
  Vibe has not been empirically tested with MiniMax as the provider
  (no such configuration in the shipped defaults; OpenRouter can route
  to whatever, but the default list does not include MiniMax).
- Whether Vibe's prompt produces narrow edits on a
  litigation→arbitration transformation — Vibe's worked examples use
  the jurisdiction sentence as an insertion anchor for a GAP, not
  as a MISALIGNMENT transformation target. The empirical data point
  Arturs has observed ("lawyer-acceptable redlines") is presumably
  against Vibe's typical playbook-coverage workload.
- Whether Vibe's behaviour on a simpler MISALIGNMENT (within-sentence
  word swap, anchor-preservable) would transfer to a structural
  transformation (litigation→arbitration, no natural anchor).

---

## Implication for Sprint 10M

Sprint 10M's design cleanly separates into two independent questions
that this investigation has surfaced distinctly: (1) does MiniMax
produce narrow edits when handed Vibe's playbook-framed, anchor-
preservation-taught prompt on an anchor-preservable transformation?
(the prompt-framing question — port Vibe's prompt-framing variables
into Oscar's pipeline on MiniMax); and (2) does any frontier or
Flash-tier model produce narrow edits on Oscar's specific §9
litigation→arbitration transformation under Vibe's prompt? (the
transformation-type question — transformations with no shared phrasing
with the target have no anchor for `diff_cleanupSemantic` to preserve,
regardless of framing). The "port Vibe's architecture" option is not
necessary as 10M's primary because Vibe's substrate IS the CPM
substrate 10L already ported; the net architectural addition is
prompt framing + structural-context header + GAP/MISALIGNMENT
task shape. 10M's brief should sequence the cheaper question first
(repurpose Oscar's test harness to run Vibe's prompt on MiniMax
against an NDA+playbook pair, observe whether the edits are
anchor-preserving) before investing in a transformation-specific
prompt or a model-tier experiment.
