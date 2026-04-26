# Sprint 10Q — Phase 1.3 design note (planner prompt architecture)

Phase 1.3 implements the planner prompt restructure: context-layers
shape with the playbook layer active and direction / state-of-play /
memory layers as named placeholders. This note records the
architectural decisions ahead of implementation. It does not draft the
prompt itself; that is Phase 1.3's implementation deliverable.

Five decisions: (1) planner consultation pattern, (2) clause
anchoring, (3) clause identification, (4) decision schema, (5)
dispatcher behaviour for first-pass. Plus the contract between Phase
1.2 (loader) and Phase 1.3 (prompt consumer) — the loader output
shape and prompt input shape have to align.

---

## §1 — Planner consultation pattern

**Decision: Pattern B — playbook in system prompt, whole document in
one user prompt, planner emits all decisions at once.**

### Candidates

- **Pattern A**: playbook in system prompt; clause-by-clause user
  prompts; planner runs N times per document.
- **Pattern B**: playbook in system prompt; whole document in one user
  prompt; planner emits all decisions at once.

### Reasoning

10P validated coherent reasoning across 18 decisions on a single
counterparty-response pass. Cross-clause logic worked — the planner
correctly flagged dependent positions across separate clauses (e.g.,
indemnity-cap reasoning that referenced confidentiality-breach
super-cap). Token cost is comparable: Pattern A duplicates the system-
prompt playbook N times, Pattern B sends one larger user prompt;
input-token totals come out close given prompt-caching on the system
side.

Pattern A's failure mode is the more serious one: clause-by-clause
isolation loses cross-clause reasoning the playbook explicitly relies
on (§5 indemnity caps reference §6 IP super-caps; §3 SLA tiers
reference §8 termination-on-sustained-failure). The 10P evidence
points the other way — coherence held — so Pattern B is the supported
choice.

### Phase 2 revisit signal

Phase 2 runs the OpenAI–CoreWeave MSA, which has a substantially
larger clause count than the Acme NDA used in 10P. If coherence
degrades on the larger document — decisions that contradict each
other, missed cross-references, or schema-output drift partway through
— that surfaces as a Pattern B limitation and Sprint 10R or later
considers a hybrid (e.g., grouped batches by document section). The
Phase 2 substantive verdict captures whether this revisit is needed.

---

## §2 — Clause anchoring

**Decision: Approach two — planner emits clause reference + intent;
executor stage produces specific text replacement.**

### Candidates

- **Approach one**: planner emits before/after text pairs; dispatcher
  uses surgical anchor matching to apply.
- **Approach two**: planner emits clause reference + intent; executor
  stage produces specific text replacement.

### Reasoning

The planner-executor split is the proven 10O / 10P architecture. GPT-
5.5 non-Pro (planner) is good at policy reasoning — read the clause,
consult the playbook, decide whether to act and why. MiniMax-M2.7
(executor) is good at producing the specific replacement text once the
intent is fixed. Approach one collapses both jobs onto the planner and
asks it to be both negotiator and drafter in the same call.

Approach one is also brittle: planner-emitted before/after text pairs
have to match the OOXML run boundaries the dispatcher anchors on, and
the planner has no view of run-level structure. The 10P surgical
anchor work (Phase 1) and wholesale fallback (Phase 2) already exist
on the executor side and assume an executor-produced replacement. The
prior architecture is the supported architecture.

### Trade-off note

Approach two splits one logical decision into two LLM calls (planner
intent → executor text), which costs latency. The 10P timings were
acceptable; Phase 2 will validate at MSA scale.

---

## §3 — Clause identification

**Decision: Pattern B — planner reads whole MSA in user prompt,
identifies clauses by section markers naturally. Pre-segmentation
deferred.**

### Candidates

- **Pattern A**: pre-segmentation step parses MSA into named clauses
  before planner sees document.
- **Pattern B**: planner reads whole MSA in user prompt, identifies
  clauses by section markers naturally.

### Reasoning

The OpenAI–CoreWeave MSA has structural section markers (numbered
articles, lettered subsections) that the planner can reference
directly when emitting `clause_reference` strings. Pre-segmentation is
real engineering: it requires a parser that handles MSA-specific
conventions (numbered headings, defined-terms, exhibits, signature
blocks), maintains paragraph-id mappings for downstream dispatch, and
fails gracefully on documents that don't match expected structure.
Minimum-viable approach is Pattern B — let the planner do the
identification work.

### Failure mode and forward path

If Phase 2 surfaces clause-identification failures — planner emitting
`clause_reference` strings the dispatcher cannot resolve, planner
missing entire clauses because section markers are non-obvious,
planner conflating multiple clauses into one decision — that is the
signal to build a segmenter in Sprint 10R or later. The Phase 2
mechanical verification step records which (if any) decisions landed
with unresolvable clause references.

---

## §4 — Decision schema

**Each planner output is a list of decision objects. Schema:**

| Field | Type | Notes |
|---|---|---|
| `clause_reference` | string | The MSA clause the decision relates to. Free-form per §3 — "Article 5", "§5.2(b)", "Indemnity clause", whatever the planner uses to name it. The dispatcher resolves to a paragraph anchor downstream. |
| `playbook_position` | string | Which playbook position is in play. Free-form — typically a category-name reference like "§5 Indemnity caps" or a quoted position fragment. |
| `playbook_consultation` | string | Free-form rationale: how the playbook position interacts with the clause as drafted. The audit-trail field. |
| `action` | enum | `comment_only` \| `counter_propose` \| `no_action` |
| `comment_text` | string | Populated if `action != no_action`. The text rendered as a Word comment. |
| `intent` | string | Populated only if `action == counter_propose`. The instruction the executor consumes to produce specific replacement text. |
| `divergence_from_playbook` | bool | Always `false` in Phase 2 (no subsequent-pass to diverge from). Present structurally per Phase 0 §6 context-layers design. |
| `divergence_comment_text` | string | Always empty in Phase 2. Present structurally; the dispatcher renders nothing on first-pass. |

### Notes

- **No `accept` action.** First-pass redlining has no pre-existing
  tracked changes to accept. The accept / reject mechanics from 10P
  counterparty-response are deferred until subsequent-pass support
  lands (Sprint 10R or later).
- **Divergence fields present structurally.** Phase 0 §6
  established that the planner output supports
  `divergence_from_playbook` and `divergence_comment_text` in 10Q so
  that subsequent-pass infrastructure does not require a schema
  migration. On first-pass these fields are always populated as `false`
  / `""` and the dispatcher renders nothing because there is no
  divergence to flag.
- **`playbook_consultation` as the audit-trail anchor.** This field
  is the planner's explicit record of how the playbook drove (or
  didn't drive) the decision. Phase 2's mechanical verification reads
  this field to confirm the planner consulted the playbook as
  instructed; substantive review reads it to assess whether the
  consultation reasoning is sound.
- **Comment vs. counter-propose.** `comment_only` for clauses where
  the playbook position warrants flagging but no specific replacement
  text is appropriate (e.g., raising a question, asking for
  clarification, noting a gap that the partner needs to direct on).
  `counter_propose` for clauses where the playbook position is
  specific enough to drive a textual change.

---

## §5 — Dispatcher behaviour for first-pass

| `action` | Dispatcher behaviour |
|---|---|
| `no_action` | Ignore for output purposes; record decision in audit trail only. |
| `comment_only` | Stage C `add_comments_on_document` attaches `comment_text` to the relevant paragraph anchor. No tracked change emitted. |
| `counter_propose` | Executor produces OOXML edit from `intent`; dispatcher applies via the surgical-or-wholesale mechanism from Phase 1 of 10P. Tracked change is attributed to **"Customer Counsel"**. `comment_text` attaches as a comment alongside the tracked change. |

### Notes

- **Author attribution: "Customer Counsel".** Generic, matches the
  abstract test framing. "Acme" doesn't fit when the document parties
  are OpenAI and CoreWeave; per-client real-author labels arrive when
  the playbook directory itself becomes per-client (post-10Q).
- **Divergence rendering: nothing.** Per §4, divergence fields are
  always empty in Phase 2 and the dispatcher emits no comment / no
  flag for them. The branch exists in dispatcher code so subsequent-
  pass support (10R+) can populate it without dispatcher refactoring.
- **Audit trail.** Every decision — including `no_action` —
  serialises into the planner-output metadata captured per dfa1f5c.
  Mechanical verification reads the trail to confirm decision counts
  match the document's clause count and that schema fields are
  populated correctly.

---

## §6 — Phase 1.2 / Phase 1.3 interface contract

The loader (Phase 1.2) produces a string. The prompt (Phase 1.3)
consumes that string as a named context-layer section. They have to
agree on shape.

### Loader output shape

- **Single string.** Result of reading `playbook-{document_type}.docx`
  via `python-docx Document(path)` and concatenating the document's
  paragraphs in document order. The output is consumed verbatim by
  the prompt's named context-layer section — no further formatting,
  escaping, or transformation.
- **Headings rendered as markdown.** H1 headings emit as
  `# {heading text}`; H2 headings emit as `## {heading text}`.
  Heading text is preserved verbatim from the .docx style — no
  normalisation, no rewriting. The planner reads `## 5. Indemnity
  caps` as a section marker, matching the prose shape of the source
  playbook.
- **Paragraph break convention.** Double newline (`\n\n`) between
  prose paragraphs — the blank-line separator that conventional
  markdown uses. Single newline (`\n`) immediately after a heading
  line before the first body paragraph of that section — the heading
  attaches visually to its body, which matches the reading rhythm of
  the source .docx. Between consecutive headings (no body in
  between) the rule degenerates to `\n\n` — a heading line followed
  by another heading line is a section transition, not a heading-
  with-body pairing.
- **Empty string on three-level fallback miss** (per MCP loader
  pattern — explicit path → project-dir glob → empty). Empty playbook
  is a valid state; the prompt handles the empty-layer case
  gracefully.
- **No bullets, no tables.** The .docx artefact is mechanical-prose-
  only per Phase 1.1 conversion rules. The loader does not need to
  handle bullets or tables; if the .docx contains them in future, the
  loader emits them as plain text without structural markers.

### Concrete output example

For the Phase 1.1 playbook, the loader output begins:

```
# Customer-Side Compute Capacity MSA Playbook (Draft)
## Preliminary note
The deals this playbook applies to are large compute-capacity
arrangements...

## 1. Data residency and sovereignty
Customer data — inputs, outputs, and provider-generated derivatives —
must remain in jurisdictions the customer names...

The fallback we can live with is a hard commitment for primary
production workloads in named regions...

## 2. Model and weight ownership
...
```

Heading immediately followed by single `\n` then body; body paragraphs
separated by `\n\n`; next heading separated from the preceding
paragraph by `\n\n`. Phase 1.2 implementation produces strings
matching this shape; Phase 1.3 inserts them verbatim.

### Prompt input shape

- **Named context-layer section in system prompt.** Section heading
  identifying the layer (e.g., `<playbook>...</playbook>` or
  `## Playbook layer`); the loader output appears verbatim inside.
- **Sibling placeholder sections** for direction / state-of-play /
  memory layers, each with its own named section heading, each
  populated empty in 10Q first-pass. The placeholders signal to the
  planner that other context layers exist and may be populated in
  future passes; they do not add information on first-pass.
- **Verbatim insertion.** The prompt does not paraphrase, summarise,
  or pre-process the playbook string. The planner reads the playbook
  as-written by the senior counsel.

### Coupling note

The loader and the prompt are loosely coupled: the loader knows
nothing about the prompt's section names, and the prompt knows
nothing about the loader's path-resolution or fallback logic. They
agree only on: (a) the loader returns a string, (b) the prompt
inserts that string verbatim into a named section. Phase 1.2
implements (a). Phase 1.3 implements (b). Either can change
internally without disturbing the other.

---

## Forward path (out of scope for 10Q)

- **Subsequent-pass support (10R+).** Direction layer populated by
  the partner / in-house lawyer's brief on the specific round; state-
  of-play layer populated by extraction from prior-pass tracked
  changes; divergence-from-playbook fields populated and rendered when
  direction conflicts with playbook position.
- **Memory layer (10R+ or later).** Slack-derived addenda or
  accumulated decisions feeding into the playbook-relative context.
- **Pre-segmentation (10R+ if Phase 2 signals it).** Per §3, only
  built if Phase 2 surfaces clause-identification failures.
- **Per-client author attribution.** "Customer Counsel" is the
  generic Phase 2 label; per-client labels follow when the playbook
  directory itself becomes per-client.
- **Hybrid consultation pattern (10R+ if Phase 2 signals it).** Per
  §1, only considered if Pattern B's coherence degrades on the larger
  MSA document.
