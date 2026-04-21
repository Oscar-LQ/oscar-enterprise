# Sprint 10K — Claude-Plugin-MCP first-pass port: research note

This note is the cross-track durable artefact of Sprint 10K's Phase 1
research. It survives regardless of the sprint's outcome. Future
redline or CoSec sprints that touch document mutation can refer here
instead of re-extracting the same material.

Written per new `CLAUDE.md` §"Cross-Version Porting Research" rule:
when a sprint ports a pattern whose source depends on a third-party
library, Phase 1 must identify the version the source was written
against, compare to the version currently in use, and verify contract
compatibility. Section 5 below records that check.

---

## 1. Where Claude-Plugin-MCP (CPM) lives

Local clone: `/sandbox/reference-material/claude-plugin-mcp/`

Upstream: the repo distributes as `claude-contract-negotiator` on PyPI
(version `2.0.0` at the time of extraction — see
`claude-plugin-mcp/pyproject.toml`).

Relevant files for first-pass redlining:

| Path | Purpose |
|---|---|
| `skills/negotiate-contract/SKILL.md` | System prompt (~800 lines); workflow + rules + examples |
| `defaults/PERSONA.md` | Commercial-solicitor persona (29 lines) |
| `defaults/AUTHORITY.md` | Green/Amber/Red zone framework (53 lines) |
| `src/mcp_server/redline_tool.py` | `redline_document` MCP tool entry; edit-list contract |
| `src/pipeline/first_pass.py` | `run_first_pass_pipeline` — validates paths, calls `apply_edits_surgically`, writes output |
| `src/pipeline/surgical_edit.py` | `apply_edits_surgically` — sort-by-length, three-layer matcher, delegation fallbacks |
| `src/pipeline/word_diff.py` | Per-edit word-level OOXML narrowing via `diff_match_patch` |
| `src/pipeline/word_diff_compensations.py` | Heavy-rewrite ratio detection; delegation triggers |

The counterparty-response workflow lives at `SKILL.md` lines 181–604
and is out of scope for 10K (10K's input is a clean document, no prior
CriticMarkup to handle).

---

## 2. CPM's first-pass flow (one LLM call)

**Entry.** Claude receives SKILL.md as its system prompt plus the
user's negotiation instructions and the clean text of the document.
One call. No tool-call loop for edit generation.

**LLM output shape.** A single JSON reply containing a list of edit
dicts. CPM's MCP tool declares the contract at
`src/mcp_server/redline_tool.py:32–37`:

```python
def redline_document(
    input_path: str,
    output_path: str,
    edits: list[dict[str, str | None]],
    author_name: str,
) -> str:
```

Each edit dict has three fields: `target_text` (exact text to find),
`new_text` (replacement, or `""` for deletion, with `None` accepted
and coerced), `comment` (optional rationale or `None`).

**Decomposition discipline.** The LLM is forced to decompose at the
edit-list level by two mechanisms:

1. Data contract: each list entry must identify one `target_text` span
   and one `new_text` replacement. Decomposition happens before
   `new_text` is generated.
2. Prompt discipline: SKILL.md Step D1 ("Edit Precision Rules", lines
   648–689) explicitly teaches 5–15 word targets, "do not rewrite what
   you are not changing," with WRONG/RIGHT worked examples.

**Per-edit diff.** After the LLM replies, CPM's pipeline computes a
word-level diff BETWEEN each edit's `target_text` and `new_text`
(not document-level). `diff_match_patch` runs inside
`src/pipeline/word_diff.py`, emitting narrow `w:ins`/`w:del` spans for
OOXML. This is the "surgical" part of `apply_edits_surgically` — it
narrows what the LLM gave to the minimum OOXML span.

**Application.** `apply_edits_surgically` (surgical_edit.py) sorts
edits by target-length descending, runs a three-layer text matcher
(full / clean / PlainTextIndex), and applies word-level surgery to the
OOXML runs. Delegation fallbacks cover pure deletions, newlines,
reconstruction mismatches, and heavy rewrites (>70% changed).

**No iteration.** The LLM's single reply is the entire edit list. No
retry. No plan-then-execute split at LLM level. Decomposition lives
in the prompt + contract, not in a multi-call loop.

---

## 3. CPM's system-prompt structure (verbatim for the critical blocks)

### 3.1 Persona (`defaults/PERSONA.md`, 29 lines verbatim)

Commercial solicitor framing. Emphasises:
- Collaborative but firm posture
- Risk/impact proportionality ("do not spend the same energy on a
  notice period as on a liability cap")
- Preservation of enforcement
- Concise comment style

### 3.2 Authority framework (`defaults/AUTHORITY.md`, 53 lines verbatim)

Three zones:
- **Green** — autonomous (typos, formatting, boilerplate, cross-refs)
- **Amber** — flag and recommend (payment, liability, indemnity,
  warranties, IP, financial thresholds, risk shifts)
- **Red** — escalate (**governing law, jurisdiction/dispute resolution**,
  compliance, sanctions, data protection, unlimited-liability exposure)

Step C of the first-pass workflow classifies proposed changes against
this framework; Red-Zone items do not enter the edit list without user
authorisation.

### 3.3 Step 6 commenting rules (`SKILL.md` 330–420, verbatim)

Most tracked changes have NO comment. Two-bar system:
- First-pass redlines: **0–3 comments per 15-clause contract**
- Counterparty responses: 3–5 comments

With concrete WRONG/RIGHT examples of what to comment on and what to
let the markup speak for. Core bar: don't comment if the reasoning
is inferable from the change itself.

### 3.4 First-pass workflow (`SKILL.md` 606–713, verbatim)

Steps A–F:

- **Step A** — Read user's negotiation instructions. Combine with
  persona, authority framework, playbook.
- **Step B** — Analyse the contract clause by clause using the clean
  text from ingestion. Most clauses will be fine as-is.
- **Step C** — Authority Check. Classify each proposed change. Amber
  or red → present and wait.
- **Step D** — Build the edit list. Create edit dicts as described.
- **Step D1** — Edit Precision Rules (the critical section; quoted in
  full below).
- **Step E** — Commenting rules (defers to Step 6).
- **Step F** — Call `redline_document` with the edit list.

Steps G (Styler) and H (Report) are CPM-local and excluded from the
10K port.

### 3.5 Step D1 Edit Precision Rules — the core discipline (SKILL.md 648–689, verbatim)

This is the key decomposition-forcing section. Quoting in full because
Sprint 10K tests whether this explicit language — with worked examples
— is sufficient to unlock surgical spans on a weaker model:

> When building your edit list, follow these rules to produce precise,
> word-level redlines:
>
> **Target the minimum changed span.** If you need to change one word
> in a sentence, set target_text to a phrase containing just that word
> plus enough surrounding context for unique matching (usually 5-15
> words). Do not set target_text to the entire paragraph or sentence.
>
> **Do not rewrite what you are not changing.** If you need to add a
> proviso to the end of a clause, include the last few words as
> target_text and append your addition in new_text. Do not delete and
> rewrite the whole clause.
>
> **Do not include formatting markers.** Never include ** or _ in
> new_text. Formatting is preserved automatically from the original
> document.
>
> **Keep target_text as short as uniquely matchable.** The engine
> needs to find your target_text in the document. Include enough
> context to avoid ambiguity, but no more. A phrase of 5-15 words is
> usually right.
>
> WRONG -- rewriting a whole sentence to change one word:
>   target_text: "The Receiving Party shall keep all Confidential
>     Information strictly confidential and shall not disclose it to
>     any third party"
>   new_text: "The Receiving Party agrees to maintain the confidentiality
>     of all Confidential Information and shall not disclose such
>     information to any third party without prior written consent"
>
> RIGHT -- targeting just the phrase that needs the addition:
>   target_text: "shall not disclose it to any third party"
>   new_text: "shall not disclose it to any third party without the
>     prior written consent of the Disclosing Party"
>
> WRONG -- replacing a defined term by rewriting the whole definition:
>   target_text: "Confidential Information means any information
>     disclosed by either party to the other party"
>   new_text: "Confidential Information means any information disclosed
>     by the Disclosing Party to the Receiving Party"
>
> RIGHT -- targeting just the phrase that differs:
>   target_text: "disclosed by either party to the other party"
>   new_text: "disclosed by the Disclosing Party to the Receiving Party"

Two things to notice about this section:
- The WRONG/RIGHT examples are concrete and use the same prose
  register as the NDA we're operating on (confidentiality clauses).
- The decomposition guidance is **implicit via examples**, not via a
  numeric count rule ("produce 2–4 edits"). The rule is structural
  ("keep target to 5–15 words; don't rewrite what you're not
  changing") rather than enumerative.

### 3.6 Edit list data contract (recap)

```
{
  "edits": [
    {"target_text": str, "new_text": str, "comment": str | null}, ...
  ]
}
```

LLM produces this as JSON. CPM's tool parses into `DocumentEdit`
pydantic models (Adeu 0.7.x terminology).

---

## 4. Divergence between 10J and CPM (what 10J missed)

Sprint 10J built a pipeline under the label "Shape B — port the
Claude-Plugin-MCP word-diff pipeline". In practice 10J ported the
diff library choice (`diff-match-patch`) but **did not port the
orchestration shape**.

| Axis | CPM first-pass | 10J deterministic pipeline |
|---|---|---|
| LLM output shape | Edit list `[{target, new, comment}]` | Target prose `{current_text, replacement_text}` |
| Decomposition locus | LLM (forced by Step D1 + edit-list contract) | Diff algorithm (block-grouping on fragmented 1–3-word ops) |
| Diff scope | Per-edit (target_text ↔ new_text) | Document (current ↔ draft) |
| Surgical discipline | Explicit (Step D1 + WRONG/RIGHT examples) | Absent |
| Authority framework | Present (Green/Amber/Red zones) | Absent |
| Persona | Commercial solicitor | Absent |
| Commenting rules | 0–3 per 15 clauses for first-pass | Absent |
| Worked examples | 3+ in-prompt | Absent |

10J optimised the question "can the substrate produce narrow edits if
the LLM doesn't decompose?" CPM optimises the question "can the
prompt force the LLM to decompose, and then have the substrate map it
faithfully?" These are different architectures. 10J's Outcome B
(bundling moved upstream from decomposition to drafting) is not a
finding about CPM's pattern — it is a finding about 10J's own
pipeline, which is a different pipeline.

**What 10J got right and 10K keeps**: `diff-match-patch` as the
word-level diff library; Adeu as the OOXML application layer; JSON as
the LLM output format; `verify_output`'s span-width warnings as the
lawyer-shape diagnostic.

**What 10J missed and 10K adds**: persona + authority + Step 6 + Step
A–F + Step D1 surgical discipline + WRONG/RIGHT worked examples,
assembled as the system prompt; edit-list data contract
(`{"edits": [...]}`); per-edit (not document-level) diff handled by
Adeu's internal `trim_common_context`; direct `ModifyText` construction
from the LLM's edit dicts.

---

## 5. CPM ↔ Adeu version-gap analysis

Per new CLAUDE.md §"Cross-Version Porting Research".

**Versions.**

- CPM pins `adeu>=0.7.0` (`claude-plugin-mcp/pyproject.toml:13`).
- Oscar has `adeu==1.1.0` installed
  (`python -c "import adeu; print(adeu.__version__)"` returns `1.1.0`).
- Adeu's reference-material clone under
  `/sandbox/reference-material/adeu/` is also 1.1.0 (same git head).

**The breaking change.** Adeu v0.9.0 ("API Unification & Reliability"
per `reference-material/adeu/AI_CONTEXT.md`) replaced the older
`DocumentEdit` class with a discriminated-union `DocumentChange =
ModifyText | AcceptChange | RejectChange | ReplyComment`. CPM's code
still imports `from adeu import DocumentEdit` (8 sites across
`src/mcp_server/redline_tool.py`, `src/pipeline/first_pass.py`,
`src/pipeline/surgical_edit.py`, `src/pipeline/word_diff_compensations.py`,
`src/pipeline/surgical_helpers.py`) — **CPM will not run against Adeu
1.1.0 without edits**. The class no longer exists.

**What the rename actually changed.**

| Aspect | Adeu 0.7.x (CPM target) | Adeu 1.1.0 (Oscar) |
|---|---|---|
| Class name | `DocumentEdit` | `ModifyText` |
| Field names | `target_text`, `new_text`, `comment` | **identical** |
| Constructor contract | `DocumentEdit(**edit_dict)` | `ModifyText(**edit_dict)` |
| Discriminator | n/a (single class) | `type: Literal["modify"]` (for union membership) |
| Batch entry | `RedlineEngine.process_batch` | `RedlineEngine.process_batch` (same signature) |
| Pre-flight check | `validate_edits` | `validate_edits` (same signature) |

The JSON the LLM produces (`{"target_text", "new_text", "comment"}`)
is **unchanged between the versions**. Only the Python class name on
the receiving side changed. This is already the established idiom on
Oscar main — Sprint 10E's code (`sprint-10e/run.py:88`) imports
`ModifyText` and uses
`ModifyText(target_text=..., new_text=..., comment=...)` as its edit
constructor. 10K inherits that pattern unchanged in its `map_to_adeu`
step.

**Verdict: Finding A — no material contract change.** The LLM↔code
contract survives the version jump. One Python-side class rename;
everything else passes through.

**CPM's delegation fallbacks — scope-excluded, not version-forced.**
CPM's `apply_edits_surgically` wrapper (sort-by-length, pre-match
delegation for pure deletions/newlines, three-layer matching,
post-match delegation for reconstruction mismatches and heavy rewrites
>70%) is **CPM-original compensation logic, not workarounds for
old-Adeu limitations that current Adeu has resolved natively**. Key
evidence:

- `apply_edits_surgically` does not exist anywhere in Adeu 1.1.0
  source (grep returns matches only in CPM's own files).
- Adeu 1.1.0 natively provides: `trim_common_context` (per-edit
  prefix/suffix narrowing), a `mapper` + `clean_mapper` three-layer
  matcher, `validate_edits`, markdown-in-`new_text` support, comment
  attachment.
- Adeu 1.1.0 does not provide: sort-by-length edit ordering,
  pre-match delegation, heavy-rewrite flagging.

For 10K's test case (§9 single-paragraph, clean text, expected 2–5
narrow edits on a straightforward transformation), Adeu 1.1.0's native
surface is sufficient. CPM's compensation layer exists for production
variety (multi-paragraph edits, counterparty markdown, heavy
counterparty rewrites) that 10K deliberately doesn't exercise. 10K
intentionally does NOT port the compensation layer — that's scope
creep beyond "port the first-pass pattern to test decomposition."

If MiniMax produces an edit Adeu can't handle (multi-paragraph,
non-unique target, reconstruction mismatch), the pipeline raises
`BatchValidationError` which is Outcome C with a diagnosable cause.
No silent wrapping.

---

## 6. What this research does and does not tell us

**Tells us.**

- CPM's first-pass pattern is single-call, edit-list-shaped, with
  explicit surgical discipline in the system prompt.
- Sprint 10J's pipeline was structurally different from CPM's (prose
  output + document-level diff) — 10J's findings do not apply to CPM.
- Adeu 1.1.0's API is contract-compatible with CPM's edit-list shape
  except for one class rename.
- The sprint can proceed with a faithful port (no substantial substrate
  adaptation beyond the rename).

**Does not tell us.**

- Whether the pattern transfers down-tier to MiniMax (that's the
  hypothesis under test in Phase 3; the result is recorded in the
  SPRINT_LOG §10K entry).
- Whether CPM's compensation layer is needed for real client
  documents. 10K's NDA is single-paragraph synthetic. Production
  work would need to re-evaluate.
- Whether Adeu 1.1.0's stricter validation (vs 0.7.x) behaves
  differently on edge cases. The contract surface is unchanged, but
  behavioural compatibility wasn't exhaustively tested — if 10K's
  Outcome C lands as `BatchValidationError`, this is a gap to
  investigate in 10L.

---

## 7. Pointers

- Approved plan: `/sandbox/.claude/plans/bright-noodling-liskov.md`
  (local to session; key content reproduced here).
- Run artefacts (feature branch `sprint-10k-claude-plugin-mcp-port`):
  `src/redline/experiments/sprint-10k/`
  (`llm-input.txt`, `llm-output.txt`, `parsed-edits.json`,
  `adeu-calls.jsonl`, `transcript.txt`, `nda-input.docx`,
  `nda-output.docx`).
- Outcome analysis and seven-sprint comparison table: `SPRINT_LOG.md`
  §10K.
