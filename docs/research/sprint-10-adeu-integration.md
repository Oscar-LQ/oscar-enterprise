# Sprint 10A — Adeu Integration Research

> Research-only sprint. This note is the deliverable. No code lands in Oscar this
> sprint. Sprint 10B (and likely 10C and 10D) implements.

## Summary

Oscar's first capability is contract redlining (PROJECT.md § Capability Stages).
Sprint 10 introduces Adeu, the third-party OOXML redlining library that will
apply edits to `.docx` files as native Word track changes. This note captures
three things: (1) what Adeu actually is as of the current release, read from
source; (2) what the prior-art Claude-Plugin-MCP project does that makes its
output lawyer-shaped instead of text-editing-shaped, read from its skill
definitions and source; (3) a concrete plan for how Oscar should wire Adeu in,
including the specialist's system prompt.

**Headline findings.** Adeu 1.1.0 is on PyPI, is MIT-licensed, and exposes
three interfaces (Python SDK, CLI, FastMCP server) over one engine. The SDK is
the smallest fit for Deep Agents. Claude-Plugin-MCP's prior art is not a prompt
so much as a prompting *discipline*: it separates *clean-document* and
*counterparty-response* workflows, forbids rejecting counterparty changes in
favour of layered counter-proposals, and constrains edit precision to
5–15-word targets. Those three rules are the anti-dote to the "delete
sentences instead of redlining" failure mode.

**Recommendation.** Wrap Adeu's `RedlineEngine` as a single Deep Agents tool
under a new `redline-specialist` subagent beneath Head of Commercial. Split
Sprint 10's implementation into three sprints (substrate → wiring →
verification) rather than one, to protect the prompt-iteration loop from
substrate churn. Proposed specialist system prompt is in Part 3 §3.

---

## Part 1 — Adeu as it exists today

Read from the cloned source at `/sandbox/reference-material/adeu/` (Git
`main`, HEAD of clone). Cross-referenced with `README.md`, `AI_CONTEXT.md`,
`ARCHITECTURE.md`, `spec.md`, `pyproject.toml`, and PyPI version index.

### 1.1 Distribution

- **Package name:** `adeu`. On PyPI.
- **Current version:** `1.1.0` (per `pyproject.toml` and
  `pip index versions adeu`). PyPI shows 28 historical versions; the jump from
  `0.9.0` → `1.0.0` → `1.1.0` is recent. Pre-2.0 but over the 1.0 line.
- **Install:** `pip install adeu==1.1.0` (or unpinned for development).
  Prerequisite `uv` in the README is only needed for the `uvx adeu init`
  zero-install path for Claude Desktop — not needed for SDK consumers.
- **License:** MIT (see `LICENSE`). Commercial use allowed without reciprocity.

Pin-posture for Oscar: we are a stable consumer of an actively-evolving
dependency. Pin to an exact version in `requirements.txt`. Expect to bump
every sprint or two; the prior-art Claude-Plugin-MCP's `adeu>=0.7.0` pin is a
cautionary tale (it now imports `DocumentEdit`, a symbol that no longer exists
in 1.1.0 — see §1.3 below).

### 1.2 Interface surfaces

Adeu exposes the same redlining engine through three surfaces. All three sit
on top of `adeu.redline.engine.RedlineEngine`.

| Surface | Entrypoint | Purpose |
|---------|-----------|---------|
| **Python SDK** | `from adeu import RedlineEngine, ModifyText, ...` | In-process library calls for programmatic pipelines |
| **CLI** | `adeu = "adeu.cli:main"` (console script) | `adeu extract`, `adeu diff`, `adeu markup`, `adeu apply`, `adeu sanitize`, `adeu init` — human-terminal use or subprocess invocation |
| **MCP server** | `adeu-server = "adeu.server:main"` (console script) | FastMCP server exposing `read_docx`, `process_document_batch`, `accept_all_changes`, `diff_docx_files`, `sanitize_docx`, `validate_documents` tools to MCP-speaking agents |

The MCP server's tool set is in `src/adeu/mcp_components/tools/` (`document.py`,
`sanitize.py`, `validation.py`, `auth.py`, `email.py`). It ships a FastMCP
provider registered via `FileSystemProvider(root=...)`, so tools are discovered
at server start.

**Stable public surface:** the Python-SDK exports in `src/adeu/__init__.py` —
`RedlineEngine`, `ModifyText`, `AcceptChange`, `RejectChange`, `ReplyComment`,
`DocumentChange`, `extract_text_from_stream`, `apply_edits_to_markdown`,
`__version__`. These are the names the library publicly commits to.
Submodule imports (`adeu.redline.mapper.DocumentMapper`, `adeu.anchor.*`) are
internals — the prior art Claude-Plugin-MCP reaches into
`adeu.redline.mapper` and `adeu.anchor` and as a result is tightly bound to
internal shape. Oscar should stay inside the `__all__` surface.

**For Oscar (Sprint 10B):** use the Python SDK. Rationale:
- **Prior art does this.** Claude-Plugin-MCP imports Adeu as a library and
  wraps its own MCP server around it. No subprocess, no MCP client layer.
- **Deep Agents' tool idiom fits it.** A `@tool`-decorated Python function
  that takes a path and an edit list and returns a path. One round-trip,
  no transport.
- **CLI** adds subprocess management, JSON file marshalling, and error
  stringification for an unclear benefit — we would write the same wrapper
  in Python either way.
- **MCP server** adds transport, requires running a second process
  (`adeu-server`) inside the sandbox, and requires configuring the Deep
  Agents side as an MCP client — which LangChain supports but is heavier
  than one Python function call.

### 1.3 Primitives for redlining

The public edit model is a discriminated union in `src/adeu/models.py`:

```python
DocumentChange = Annotated[
    Union[AcceptChange, RejectChange, ReplyComment, ModifyText],
    Field(discriminator="type"),
]
```

| Type | Fields | Purpose |
|------|--------|---------|
| `ModifyText` | `target_text`, `new_text`, `comment?` | Search-and-replace. Empty `new_text` = pure deletion. Empty `target_text` + non-empty `new_text` = pure insertion at anchor. |
| `AcceptChange` | `target_id` (e.g. `"Chg:12"`), `comment?` | Finalise an existing tracked change from the document. |
| `RejectChange` | `target_id`, `comment?` | Revert an existing tracked change. |
| `ReplyComment` | `target_id` (e.g. `"Com:5"`), `text` | Thread-reply to an existing comment. |

Operations on a `.docx`:

- **Ingest**: `extract_text_from_stream(stream, clean_view=False)` returns
  the document as text with inline CriticMarkup (`{++ins++}`, `{--del--}`,
  `{==highlight==}{>>comment<<}`) when changes exist. `clean_view=True`
  returns the "accepted" flat text, no markup. The LLM reasons on this
  representation.
- **Apply edits**: `RedlineEngine(stream, author="...").process_batch(changes)`
  validates target-text uniqueness, applies actions first, then text edits in
  reverse index order to avoid shift. Raises `BatchValidationError` listing
  per-edit failures.
- **Save**: `engine.save_to_stream() -> BytesIO`.
- **Accept-all**: `engine.accept_all_revisions()` flattens all pending
  tracked changes into clean text.
- **Diff two `.docx`s**: `generate_edits_from_text(orig, mod)` produces a
  `list[ModifyText]` (word-level diff, powered by `diff-match-patch`).
- **Sanitize**: strip metadata, rsids, author names — separate module in
  `src/adeu/sanitize/`. Relevant for Sprint 10's OUTPUT sanitisation before
  sending to counterparty, not for core redlining.

What Adeu does NOT offer as a primitive:

- **Paragraph/block-level restructuring** (table row moves, cell merges,
  section reorders). Edits inside tables work; edits *of* tables do not.
  `spec.md` § 5 flags this as a known limitation.
- **"Reject" as a vanish operation.** `RejectChange.target_id` requires an
  existing `Chg:N` — you cannot "reject" a clause by passing its text; you
  cancel *one of your own previously-proposed* changes. This is structural,
  not prompt-level: the model CAN'T delete text by passing it to
  `RejectChange`, only to `ModifyText(target_text=..., new_text="")`.
- **Formatting-only changes** not driven by a text delta. Insertions can
  carry limited markdown (`**bold**`, `_italic_`, `# Heading`); broader style
  changes require sibling tooling (the prior art's "Styler pass" exists
  outside Adeu — see §2.4).

**Fuzzy matching and ambiguity handling.** `target_text` is matched through
`DocumentMapper.find_all_match_indices(...)` with fallbacks for whitespace
drift. If a target matches multiple spans, `validate_edits` rejects the
whole batch with an error reporting each occurrence and its surrounding
context, and requires the caller to re-submit with more surrounding context.
Zero matches likewise fail the batch. The model is expected to include
enough context that each `target_text` is unique.

### 1.4 Dependencies and runtime requirements

From `pyproject.toml`:

```toml
requires-python = ">=3.12"
dependencies = [
    "python-docx>=1.1.0",
    "structlog>=24.0.0",
    "pydantic>=2.0.0",
    "lxml>=5.0.0",
    "diff-match-patch>=20230430",
    "keyring>=25.7.0",
    "fastmcp[apps]>=3.1.1",
    "jinja2>=3.1.6",
]
```

- Oscar runs **Python 3.13**. `>=3.12` satisfied.
- `pydantic>=2.0.0`: Oscar already has `pydantic 2.13.2`. No conflict.
- `lxml>=5.0.0`, `python-docx>=1.1.0`: not currently installed. Will pull
  binary wheels on first install. No system-library build step expected.
- `structlog>=24.0.0`, `jinja2>=3.1.6`, `diff-match-patch>=20230430`: small,
  pure-Python.
- `keyring>=25.7.0`: OS-integration dep for cloud-auth features in
  `src/adeu/mcp_components/desktop_auth.py`. If we only use the SDK
  (not `adeu-server`), `keyring` is still installed as a top-level dep
  (pyproject lists it outside any extra). Should be dormant at our
  call sites — flag as a risk (§4).
- `fastmcp[apps]>=3.1.1`: FastMCP + Apps-UI extra for the MCP server. This
  pulls `mcp`, `starlette`, `uvicorn`, `httpx` (already present), and
  possibly a few UI-only deps. Even SDK consumers get this footprint
  because it's a hard dep, not an extra. Flag as a risk (§4).

No Java, no native binaries beyond the `lxml` wheel. No LLM API requirement
at the Adeu layer — Adeu neither calls nor wraps an LLM; it receives edits
from the caller.

**Runtime behaviour.** Adeu does not open network sockets in the SDK path.
The MCP-server path can make outbound calls (to `api.adeu.ai` for cloud
validation); those do not execute during SDK usage. No sandbox policy
widening is required for the SDK path. Confirming this empirically is
a Sprint 10B task.

### 1.5 Versioning and stability

- **Current version:** 1.1.0 (released recently per PyPI index).
- **History:** 28 versions shipped; `0.1.0 → 0.7.3 → 0.8.x → 0.9.x → 1.0.0 → 1.1.0`.
- **API churn signal:** Claude-Plugin-MCP was built against `adeu>=0.7.0` and
  imports `DocumentEdit` as its central type. That symbol no longer exists
  in 1.1.0; the equivalent is `ModifyText`, with `AcceptChange`,
  `RejectChange`, `ReplyComment` factored out of it, united behind the
  `DocumentChange` discriminator. This means the `0.9.0 → 1.0.0` bump was
  a breaking API release, and any future major-version bump should be
  treated the same way.
- **Changelog:** no `CHANGELOG.md` in the repo. `AI_CONTEXT.md § Current
  Status` is a single-line status of the latest release. Breaking changes
  are discovered by reading the Git log or by tests failing after a bump.

Posture: pin to `adeu==1.1.0` in Sprint 10B's `requirements.txt`. Budget
a future sprint for version bump when one is needed.

### 1.6 Adeu's own agent guidance

Adeu ships a skill file at `skills/adeu-redlining/SKILL.md` (21 lines). Its
own description:

> Use this skill for reviewing, editing, or negotiating existing Word
> documents (.docx) where "Track Changes" or precise redlining is required.
> Use it to propose edits, accept/reject changes, or reply to comments.
> Do NOT use for creating new blank documents from scratch (use docx skill
> for that).

The README advertises a "Document Specialist" system-prompt snippet:

> **Role:** Document Specialist — `read_docx(clean_view=True)`,
> `process_document_batch` (commit & negotiate), `sanitize_docx` (pre-send
> scrub).

`AI_CONTEXT.md` spells out invariants important to callers:

- **Search-and-replace first.** Adeu intentionally hides pure
  insert/delete primitives from the LLM; all text modifications are
  ModifyText so the engine has sufficient anchoring context.
- **No manual CriticMarkup.** The LLM should not wrap its own `{++ ++}`
  tags — the engine does it.
- **No manual formatting markers inside runs.** `new_text` supports
  markdown (`#`, `**`, `_`) but formatting is otherwise carried from
  the document.

Adeu does not prescribe *how* an LLM should reason about redlining — only
what API contract it must respect when calling.

---

## Part 2 — Claude-Plugin-MCP as reference

Cloned to `/sandbox/reference-material/claude-plugin-mcp/` (v2.0.0 per
`pyproject.toml`, HEAD of `main`). Not a dependency of Oscar; read-only
reference.

### 2.1 Architecture

Claude-Plugin-MCP is a **Claude Code plugin** that exposes 11 MCP tools to
Claude. The tools wrap `adeu>=0.7.0` as a Python library and layer their own
pipeline on top (ID remapping, validation, action ordering, the "Styler" pass,
surgical word-level diffing). The prompting lives in two skill files:

- `skills/negotiate-contract/SKILL.md` (805 lines) — the primary command.
- `skills/yolo-negotiation/SKILL.md` (121 lines) — full-autonomy variant
  referencing the first.

The MCP server itself is the plugin's own (`src.mcp_server`), not Adeu's.
Claude Code loads the plugin via `--plugin-dir`, reads the skill files,
discovers the MCP server via `.mcp.json`, and then Claude (the model) is
the agent that reasons through the skill's step-by-step workflow.

Architecturally this is a **single-agent** pattern: one model (Claude),
multiple tools, a long skill-file prompt. No orchestrator, no sub-agents,
no routing.

### 2.2 The system prompt — what it says, why it works

The negotiate-contract skill file is *not* a single system prompt. It is a
step-by-step workflow broken into two branches:

- **Clean document → First-Pass Redlining Workflow** (Steps A–H).
- **Document with tracked changes → Counterparty Response Workflow**
  (Steps 3–10).

Branch selection is mechanical: detect CriticMarkup markers (`{++`, `{--`,
`{>>`) in the annotated-view output of `ingest_document`. No markers →
clean. Markers → existing markup.

**The rules that produce lawyer-shape (extracted verbatim or near-verbatim
from the skill file):**

1. **Never reject a tracked change in Word.** Rejection makes markup vanish
   with no trace. The lawyer-correct response is to **layer** a counter:
   delete the counterparty's text *through your own redline* (attributed to
   the client) and insert your alternative (also attributed). The
   counterparty opens Word and sees their original proposal, your deletion
   of it, and your counter. Full audit trail. (Skill file, "How Lawyers
   Negotiate Contracts" section and Step 5 "Approach 1".)

2. **Minimum changed span — word-level, not paragraph-level.** Target 5–15
   words of surrounding context, just enough to make the match unique. Do
   not rewrite entire sentences because one word changed. (Skill file,
   Step D1 "Edit Precision Rules".)

3. **Do not rewrite what you are not changing.** Adding a proviso to the
   end of a clause: include the last few words as `target_text`, append
   your addition in `new_text`. Replacing a defined term in a definition:
   target the phrase that differs, not the whole definition.

4. **Comment sparingly.** Most tracked changes have no comment — the markup
   speaks for itself. First-pass redlines of a 15-clause contract should
   produce 0–3 comments; counterparty-response redlines 3–5. Comment only
   when the reasoning isn't visible from the markup alone, or when
   replying to an existing counterparty comment thread. Over-commenting
   "signals inexperience to the counterparty."

5. **No formulaic comment headers.** Never write "BUYER'S POSITION:" or
   "RATIONALE:". Write like a solicitor: concise, professional, no
   structural template.

6. **Accept when the substance is acceptable; counter only when the
   substance is wrong.** Do not counter just because you'd have worded it
   differently.

7. **Calibrate posture to round.** Round 1 — counter freely, set positions.
   Round 2+ — narrow gaps, accept-with-amendments for near-agreement.
   Final round — bias heavily toward acceptance, counter only on
   deal-breakers.

8. **Apply the materiality test first.** Does this change shift risk,
   financial exposure, or commercial balance? High-impact clauses
   (liability, indemnity, IP) warrant detailed counter-proposals. Low-impact
   clauses (notice mechanics, boilerplate admin) warrant light-touch or
   acceptance.

9. **Author attribution is load-bearing.** All client edits are attributed
   to the client's name. This is how Word distinguishes rounds; it is also
   how the OOXML audit trail is built.

10. **The output must open in Word without a repair dialog.** Validation
    is a post-step gate, not a nice-to-have.

### 2.3 Rule-style guardrails (the difference between lawyer-shape and
text-editing-shape)

The prior-art brief cites a previous project that failed by "deleting
sentences instead of redlining like a lawyer". In Adeu's API this looks
like: passing a whole-sentence `target_text` with `new_text=""`, which
Adeu dutifully deletes as a single `w:del` block. The resulting document
loses the surgical, word-level redline pattern a lawyer would produce.

The Claude-Plugin-MCP skill file's Step D1 is the direct anti-dote. Both
the WRONG and RIGHT examples in that step show exactly this failure mode
being prevented:

> **WRONG — rewriting a whole sentence to change one word:**
> target_text: "The Receiving Party shall keep all Confidential Information
> strictly confidential and shall not disclose it to any third party"
> new_text: "The Receiving Party agrees to maintain the confidentiality of
> all Confidential Information..."
>
> **RIGHT — targeting just the phrase that needs the addition:**
> target_text: "shall not disclose it to any third party"
> new_text: "shall not disclose it to any third party without the prior
> written consent of the Disclosing Party"

The skill file puts this rule inline with two WRONG/RIGHT pairs — a
defined-term change and a proviso addition. It is the most concrete
guardrail in the entire skill file. Oscar's redline specialist must carry
the same guardrail into its prompt.

### 2.4 Architecture — beyond prompting

Three architectural patterns in the plugin matter beyond the prompt text:

- **Two workflows, mechanical routing.** Ingest → check for CriticMarkup
  markers → route to first-pass or counterparty-response. Deterministic;
  no LLM judgement involved. Oscar's Sprint 10B should do the same.
- **State-of-play as a precondition for counterparty-response.** Before
  any decisions, the agent calls `get_state_of_play` and gets a JSON
  listing of every `Chg:N` and `Com:N` with author, date, paragraph
  context. The model reasons on this catalogue, not on raw CriticMarkup.
  Not needed for first-pass (no existing markup to catalogue).
- **Styler pass (post-engine).** After Adeu applies edits, inserted text
  may not carry the surrounding paragraph's full formatting (font, size,
  spacing). The plugin extracts triplets (target paragraph + neighbours),
  corrects the OOXML, and splices back. This is **outside Adeu's own
  capability**. Oscar's Sprint 10B does not need this — structural
  validation ("opens in Word") is a lower bar than formatting fidelity —
  but a future sprint may revisit it.

### 2.5 Documented failure modes

No explicit post-mortem in the repo. The skill file's WRONG examples are
the record of what previous iterations got wrong, encoded as rules. Reading
backwards from those examples:

- **Whole-sentence deletions** (the "deleting sentences" failure the brief
  names directly).
- **Over-commenting** ("more than 0–3 comments on a 15-clause contract is
  inexperience").
- **Formulaic comment structures** ("BUYER'S POSITION:" style).
- **Accepting where the model would have worded it differently** (vs.
  accepting where the substance is acceptable).
- **Rejecting counterparty changes** (treating rejection as disagreement,
  rather than the vanish-operation it actually is in Word).

### 2.6 How Adeu was invoked

Direct Python library imports at three call sites in
`src/pipeline/`:

```python
# src/pipeline/first_pass.py
from adeu import DocumentEdit, RedlineEngine

# src/pipeline/surgical_helpers.py
from adeu import DocumentEdit
from adeu.anchor import apply_anchored_edit
from adeu.redline.mapper import DocumentMapper
```

`RedlineEngine(stream, author=...)` + `.apply_edits([...])` +
`.save_to_stream()` is the main loop. No subprocess, no MCP client.

**Compatibility note for Oscar.** `DocumentEdit` is the v0.7.x name for
what is now `ModifyText` in v1.1.0. The `adeu.anchor` submodule referenced
in `surgical_helpers.py` may have been renamed or reorganised; Oscar
should not rely on internal submodules. Oscar's edit construction goes
through `ModifyText` and the union-discriminator `DocumentChange`.

---

## Part 3 — Proposed plan for Sprint 10B+

### 3.1 Adeu integration architecture

**Decision: wrap Adeu as a Python library, exposed to Deep Agents via
one or two `@tool`-decorated functions.**

- **What the tools look like.** A primary tool `apply_redline(input_path,
  output_path, edits, author_name) -> ApplyResult` is sufficient for
  first-pass redlining. `edits` is a list of `ModifyText`-shaped dicts
  (target_text, new_text, optional comment). The tool materialises a
  `RedlineEngine`, calls `process_batch`, saves, and returns a result
  dict (applied count, skipped count, validation errors, output path).
  A companion tool `read_contract(path, clean_view=False) -> str` wraps
  `extract_text_from_stream` so the specialist can ingest the document
  to reason over it.
- **Why SDK, not CLI, not MCP.** See §1.2. SDK is what the prior art
  does, what Deep Agents' tool idiom expects, and what keeps the
  integration thin.
- **Where it lives in the repo.** `src/adeu_tools/` (new package).
  One module, around 100 lines. Models and engine imported from `adeu`.
  No wrapper of our own over Adeu's types — we pass `ModifyText` through.
- **No ADR required for this *direction*** (dependency install within
  the already-authorised framework stack). The *choice between SDK /
  CLI / MCP* does warrant an ADR, written at the point of decision in
  Sprint 10B.

### 3.2 Which agent calls Adeu

**Decision: a new specialist `redline-specialist` under Head of Commercial.**

- **Not the existing `accept-reject-reasoner`.** That specialist decides
  accept/reject/counter on *one* proposed edit against *one* playbook rule,
  and returns a structured `AcceptRejectDecision`. Its scope is a single
  decision, not a document transformation. Adding edit-application to it
  would violate its single-responsibility shape from ADR 013 + ADR 016
  and make its test surface too large.
- **Not Head of Commercial directly.** HOC is the routing layer (ADR 016).
  Giving it substantive tools would blur its role.
- **Not a top-level role under General Counsel.** Contract redlining is
  Commercial work; the three-level org chart (GC → HOC → specialist) is
  the right shape.
- **Three-level delegation via `CompiledSubAgent`** (ADR 014) —
  `redline-specialist` is built as its own `create_deep_agent(...)` and
  plugged under HOC as a `CompiledSubAgent` wrapper. Same pattern as
  `accept-reject-reasoner`.
- **Model allocation** (ADR 010). Specialist tier. DEV config starts with
  MiniMax-M2.7 via the existing chat-model seam
  (`OSCAR_LLM_REDLINE_SPECIALIST_*`). If MiniMax's lawyer-shape output
  quality is weaker than we want, swap to `openai/gpt-5.4` via OpenRouter
  through the DI seam — provider swap is env-var only, ADR 011 established
  the pattern.
- **HOC routing extension.** One new entry in HOC's specialist-routing
  prompt (ADR 016): "For full-document redlining work — applying tracked
  changes from a client instruction — delegate to `redline-specialist`."

### 3.3 The redline-specialist system prompt (proposed)

Aim: a specialist prompt long enough to carry the lawyer-shape rules from
§2.2–§2.3 but short enough to remain crisp. First-pass workflow only for
Sprint 10B; counterparty-response workflow deferred.

> **Role**
>
> You are Oscar's redline specialist. You receive (a) a contract in a
> `.docx` file and (b) a client instruction describing how the contract
> should be redlined. You produce a redlined `.docx` as native Word track
> changes attributed to the client.
>
> **Tools**
>
> - `read_contract(path, clean_view=False)` — read the document as text.
>   Use `clean_view=False` (default) so any existing tracked changes and
>   comments are visible in CriticMarkup form.
> - `apply_redline(input_path, output_path, edits, author_name)` —
>   commit a batch of edits. Each edit is a dict with `target_text`,
>   `new_text`, and optional `comment`.
>
> **Workflow**
>
> 1. Read the document with `read_contract`. Confirm it is a clean
>    document — no existing `{++`, `{--`, or `{==` markers. If existing
>    tracked changes are present, return a structured response stating
>    the document is a counterparty response and is out of scope for this
>    sprint.
> 2. Read the client instruction. It describes the transformation
>    desired — e.g. "make this NDA mutual", "add a limitation of
>    liability clause", "convert litigation to arbitration for dispute
>    resolution." The instruction is the spec; do not improvise beyond
>    it.
> 3. Plan the edits. Identify every span of text that must change to
>    implement the instruction. Be exhaustive — if the instruction is
>    "make this NDA mutual", every asymmetric reference to "Disclosing
>    Party" and "Receiving Party" likely needs touching for consistency.
> 4. Call `apply_redline` once with the full edit list.
>
> **How to build edits — the rules that matter**
>
> Redline like a lawyer, not like a text editor. A lawyer's redline
> shows a surgical change — the minimum span deleted, the minimum span
> inserted — with the surrounding clause intact. A text editor's
> "redline" rewrites whole sentences.
>
> - **Target the minimum changed span.** For each edit, set
>   `target_text` to 5–15 words: just the phrase that must change, plus
>   enough surrounding context to make the match unique. Never set
>   `target_text` to a whole sentence or whole clause when you are
>   changing one term.
> - **Do not rewrite what you are not changing.** If you need to add a
>   proviso to the end of a clause, the `target_text` is the last few
>   words of that clause; `new_text` is those same words plus your
>   addition. If you need to replace a defined term inside a clause,
>   the `target_text` is the defined term (plus enough context for a
>   unique match); `new_text` is the replacement term.
> - **Never delete a whole sentence or paragraph to replace it.** If
>   the change is a substantive rewrite of a clause, still target only
>   the span that differs — use multiple edits if the differences are
>   not contiguous. Only use a full-clause deletion when the instruction
>   is explicitly to remove a clause.
> - **New clauses are `ModifyText` with empty `target_text` is not
>   supported — use an anchor.** To insert a new clause, set
>   `target_text` to the last line of the preceding clause (with enough
>   context to uniquely identify it); set `new_text` to that same line
>   followed by `\n\n` and the full new clause text. The new clause
>   becomes an `w:ins` appended after the anchor.
> - **No manual CriticMarkup.** Do not write `{++`, `{--`, or `{==`
>   tags inside `new_text`. The engine produces them from your edit.
>
> **Commenting**
>
> Most edits carry no comment. The markup is self-explanatory — a
> solicitor reading the redline sees what changed and why it matters.
> Comment only when (a) the commercial rationale is non-obvious from
> the markup alone and materially affects review, or (b) you are
> flagging a material risk the recipient might not otherwise spot.
> Do not restate the tracked change in prose. Do not use formulaic
> headers. For a ~10-clause NDA, aim for 0–3 comments total. If you
> are writing more than that, you are over-commenting.
>
> **Author attribution**
>
> All edits are attributed to the client (the `author_name` arg). This
> is how Word records who made what change. Do not pass `author_name`
> as anything other than the client identifier supplied in the
> instruction.
>
> **Output**
>
> Return a short plain-English report: how many edits were applied,
> how many skipped (and why), where the output file was saved, and
> any validation warnings. If `apply_redline` returned validation
> errors, fix them and call again — the most common failure is an
> ambiguous `target_text` matching multiple spans, fixed by including
> more context.

Word count: ~520 words. At the upper end of the 300–500 target; defensible
given the weight of the guardrails being encoded.

**Deliberate omissions** from the 10B prompt:

- **Counterparty-response workflow** — Sprint 10B tests first-pass only.
- **Materiality test + posture-calibration** — those are counterparty-round
  disciplines. First-pass edits flow from the client instruction, not from
  a posture heuristic.
- **Authority zones** — amber/red-zone escalation is a capability Oscar
  does not yet have. The AcceptRejectDecision path (ADR 013) is the
  nearest precedent; integrating authority gating is a future sprint.
- **Styler pass** — out of scope for substrate-proving.
- **LangGraph HITL** — `interrupt_on` does not inherit through
  `CompiledSubAgent` (Sprint 9 surprise 3); ignored this sprint.

### 3.4 Three test NDAs — proposed shapes

Three synthetic NDAs, committed to `tests/fixtures/ndas/` as `.docx`. Each
NDA is 1–2 pages, ~8–12 clauses, numbered. Plain commercial language. No
real parties; fictional disclosing and receiving party names.

**NDA A — unilateral NDA (target for "make this NDA mutual").**

Clauses (numbered):
1. Parties (Disclosing Party = "Client Ltd"; Receiving Party = "Vendor Inc").
2. Purpose recital.
3. Definition of Confidential Information.
4. Obligations of the Receiving Party (confidentiality, restricted use,
   standard of care). Asymmetric throughout — only the Receiving Party has
   duties.
5. Permitted disclosures (to employees on a need-to-know basis).
6. Compelled disclosure carve-out (law / regulator).
7. Return or destruction upon request.
8. Term (3 years from the Effective Date).
9. No licence / no warranty.
10. Governing law & jurisdiction (England and Wales, English courts).
11. Counterparts / execution.

The asymmetry — "Disclosing Party shall...", "Receiving Party shall..." —
is dense enough that a mutualising transformation touches many spans for
consistency.

**NDA B — mutual NDA, no liability clause (target for "add LoL
clause").**

Clauses:
1. Parties (Party A, Party B — both disclosing and receiving).
2. Purpose recital.
3. Definition of Confidential Information.
4. Mutual confidentiality obligations (both parties).
5. Permitted disclosures.
6. Compelled disclosure.
7. Return or destruction.
8. Term.
9. No licence / no warranty.
10. Governing law & jurisdiction.
11. Notices.
12. Counterparts.

No existing liability-limitation clause. The transformation inserts one
(typically between the no-warranty clause and governing law, or as part
of a "Miscellaneous" block), with carve-outs for fraud, wilful misconduct,
and IP/confidentiality breach.

**NDA C — mutual NDA with a litigation clause (target for "convert
litigation to arbitration").**

Same structure as NDA B, with an expanded dispute-resolution clause:

- Clause 10a: "Governing law. This agreement is governed by English law."
- Clause 10b: "Jurisdiction. The parties submit to the exclusive
  jurisdiction of the courts of England and Wales to resolve any dispute
  arising out of or in connection with this agreement."

Nothing about arbitration. The transformation rewrites clause 10b to
refer disputes to arbitration (e.g. LCIA, seat of London, English
language), and may adjust service-of-process language if any. A
well-shaped redline here changes the jurisdiction clause, possibly
adds a specific injunctive-relief carve-out, and leaves governing law
untouched.

All three NDAs are drafted to be short enough to inspect in a minute and
realistic enough to stress the agent's pattern-matching for asymmetric
language, clause insertion, and substantive clause rewrite.

### 3.5 Three test transformations — prompt shape and success criteria

Each transformation is delivered to Oscar as a single user message.

**Transformation 1 — "Make this NDA mutual."**

Prompt (to Oscar's General Counsel — paraphrase, exact wording tuned in
10C):

> Please redline the attached NDA (file path `nda_a.docx`, author
> `Client Ltd`) to make it mutual. The current draft is unilateral —
> convert it so both parties are simultaneously disclosing and receiving,
> with symmetric obligations throughout. Save the redlined output to
> `nda_a_redlined.docx`.

Success criteria (lawyer-shape):
- Every asymmetric reference to "Disclosing Party" / "Receiving Party"
  that reflects a duty is touched, consistently. Typical pattern: either
  replacing both with "each Party" / "the other Party", or retaining the
  role labels but making each party simultaneously play both roles.
- Markup is surgical — each change is a targeted span, not a full-clause
  rewrite. Open the redlined `.docx` in Word and the Review Pane should
  show many small edits, not a handful of giant deletions-plus-insertions.
- Clause numbering is preserved; no paragraph-level renumbering.
- 0–3 comments total — e.g. one explaining the mutualisation pattern if
  non-obvious.
- The structural check: opens in Word without repair dialog; `w:ins` and
  `w:del` elements parse cleanly; `adeu extract nda_a_redlined.docx` shows
  expected CriticMarkup spans.

**Transformation 2 — "Add a limitation of liability clause."**

Prompt:

> Please redline the attached NDA (file path `nda_b.docx`, author
> `Client Ltd`) to add a limitation of liability clause. The cap should
> be the greater of £100,000 or the fees paid under any related agreement.
> Exclude fraud, wilful misconduct, and breach of confidentiality from the
> cap. Save the redlined output to `nda_b_redlined.docx`.

Success criteria:
- A new clause is inserted in a sensible location (typically between the
  no-warranty clause and governing law, or grouped under Miscellaneous).
- Clause numbering flows (if clauses 1–12 exist and the new clause slots
  in as "10a" or renumbers to become clause 11, the output is consistent
  or the LLM has added a comment explaining the numbering choice).
- The cap language is professionally drafted, not templated — i.e. not
  "[LIABILITY CAP GOES HERE]" or an obvious boilerplate stub.
- The three carve-outs are present and read correctly.
- No edits to surrounding clauses except the minimum needed to anchor
  the insertion.
- 0–2 comments, likely none (the clause is inserted as new language, not
  a counter to existing text).

**Transformation 3 — "Convert litigation to arbitration for dispute
resolution."**

Prompt:

> Please redline the attached NDA (file path `nda_c.docx`, author
> `Client Ltd`) so that any disputes arising out of or in connection
> with the agreement are resolved by arbitration in London under the
> LCIA Rules, with the seat of arbitration in London and the language
> English. Governing law remains English law. Preserve the parties'
> ability to seek injunctive relief in court for breach of
> confidentiality. Save the redlined output to `nda_c_redlined.docx`.

Success criteria:
- The jurisdiction clause (10b) is rewritten — the span naming English
  courts is marked as deleted, new arbitration language inserted.
- The governing-law clause (10a) is untouched (English law is the
  instruction).
- An injunctive-relief carve-out is added — either as an amendment to
  the rewritten clause or as a new sub-clause.
- Surgical redline pattern — not the entire clause 10b rewritten, but
  the court-reference phrase and whatever adjacent language must
  consistently change.
- 1–2 comments at most — e.g. flagging the injunctive-relief carve-out
  as the non-obvious element of the change.

### 3.6 Verification approach

Two layers, applied to each of the three outputs.

**Layer 1 — Structural verification (mechanical).**

- `adeu read_docx(path)` (or SDK equivalent `extract_text_from_stream`)
  returns the annotated view; every edit in the applied list surfaces as
  CriticMarkup in the expected location.
- The output file is a valid `.docx` — `zipfile.is_zipfile(path)` passes;
  `python-docx.Document(path)` opens without exception.
- The output opens in Word (or LibreOffice as a proxy if Word is not
  available) without triggering a repair dialog. Cannot be automated in
  the sandbox; verified manually on the host if needed, otherwise
  treated as a post-deployment check.
- `w:ins` and `w:del` element counts match expectations (rough bounds —
  the first-pass transformations shouldn't produce more than a few
  dozen of each).

**Layer 2 — Lawyer-shape verification (semantic).**

Sandbox-Claude-Code reads the output's annotated view and applies these
criteria per transformation:

- **Surgical edits, not paragraph-level rewrites.** For each `w:ins` /
  `w:del` pair, the deleted span and the inserted span should differ in
  minimum-necessary ways. If a whole paragraph is marked as deleted and
  a whole paragraph marked as inserted, that is the failure mode. A
  good redline looks like "delete N words, insert M words, context
  around both untouched".
- **Completeness on coordinated changes.** For Transformation 1, every
  asymmetric reference that should have been touched is touched — no
  orphans. Sandbox-Claude-Code can enumerate occurrences via `grep`ping
  the clean view for the original patterns and checking they are all
  within `w:del` spans in the annotated view.
- **No scope creep.** Transformations only touch what they needed to
  touch. Transformation 2 should not have edited anything except the
  insertion anchor and adjacent numbering. Transformation 3 should not
  have touched governing law.
- **Comment discipline.** Count comments; confirm 0–3 range (§3.3) and
  each one, if present, is substantive (not a restatement of the
  tracked change).
- **Author attribution.** Every `w:ins` and `w:del` carries `w:author`
  equal to the supplied client name.

**Honest-judgement criterion.** Sandbox-Claude-Code writes a short
verdict per transformation in the sprint log — "lawyer-shape" / "close
to lawyer-shape, N issues" / "not lawyer-shape". The user (or a
human-designated reviewer) can veto sandbox-Claude's verdict on a final
inspection in Word. No automated scoring — the verdict is a judgement
call.

### 3.7 Sprint 10B scope — recommend a three-sprint split

**Recommendation: split into three sprints.**

- **Sprint 10B — Substrate.** Install `adeu==1.1.0`, confirm dep tree
  resolves, widen sandbox policy if (unexpectedly) needed, wrap Adeu's
  SDK as one `@tool` function (`apply_redline`) + `read_contract` in
  `src/adeu_tools/`, prove end-to-end on a toy `.docx` (single
  `ModifyText` edit, author attribution, output validates as .docx).
  No NDAs yet, no specialist yet. Equivalent to the Sprint 6/7 split of
  "Deep Agents runs" → "org-chart routes." ADR on SDK-vs-CLI-vs-MCP
  choice.
- **Sprint 10C — Wiring.** Draft the three NDAs and commit as
  `.docx` fixtures. Stand up `redline-specialist` with the §3.3 prompt
  under Head of Commercial. Extend HOC's routing. Prove end-to-end on
  one transformation (pick Transformation 2 — LoL — as the simplest
  structurally). Second ADR on the specialist's prompt structure.
- **Sprint 10D — Verification and iteration.** Run all three
  transformations. Apply the §3.6 verification. If outputs miss
  lawyer-shape on any of them, iterate on the specialist's prompt (or,
  if the pattern suggests MiniMax is the constraint, swap the model to
  `openai/gpt-5.4` via env-var and re-run). Budget two prompt
  iterations before declaring a miss a finding rather than a fixable
  problem. This is the sprint that decides whether the capability is
  real.

Why split rather than one sprint:

- **Prompt iteration needs a stable substrate.** If all three tasks land
  in one sprint, a prompt miss forces re-running substrate verification
  to rule out a substrate regression. Separation isolates.
- **Binary success criteria per sprint.** Each sprint has a single
  outcome: substrate runs / one transformation green / all three
  transformations lawyer-shape. This mirrors the discipline of Sprints
  1 → 2 → 3 → 6 → 7 → 9 already used in PROJECT.md.
- **Honest risk surface.** If Adeu's dep tree conflicts with Oscar's
  pinned manifest (§4), 10B finds out immediately and the fix is
  substrate-only. If the prompt generalises poorly from Claude to
  MiniMax, 10D is where that plays out and the fix is contained there.

Alternative (two-sprint split — 10B = substrate + first transformation,
10C = remaining two + verification) is workable but mixes substrate and
prompt risk in 10B, which is the thing the three-way split is designed
to avoid.

---

## Part 4 — Risks surfaced

Flagged honestly; 10B should treat each as a thing to verify, not assume.

**R1 — Adeu dep-tree conflict with Oscar's pinned manifest.** Adeu
requires `pydantic>=2.0.0` (we have 2.13.2 — fine),
`lxml>=5.0.0` (not installed), `python-docx>=1.1.0` (not installed),
`structlog>=24.0.0`, `jinja2>=3.1.6`, `keyring>=25.7.0`,
`fastmcp[apps]>=3.1.1`, `diff-match-patch`. Installing these on top of
our 59 pinned packages may surface a conflict — we've not tested this
yet. Mitigation: 10B installs into a scratch venv first, captures the
full dep resolution, then updates `requirements.txt` with Adeu pinned +
new transitives pinned. If a true conflict (circular or contradictory
version constraint) emerges, that is a substrate-level blocker and the
sprint's finding is: write an ADR on version-ceiling management, then
pick the compatible Adeu version.

**R2 — `fastmcp[apps]` is a hard (non-extra) dependency even for SDK
usage.** `pyproject.toml` lists `fastmcp[apps]>=3.1.1` directly in
`dependencies`, not under `optional-dependencies`. An SDK-only consumer
still installs FastMCP and its transitives. This inflates footprint
and pulls in `mcp`, `starlette`, `uvicorn` on the server side. Nothing
breaks — FastMCP modules are unused from SDK call sites — but the
sandbox network-policy scanner may see additional processes or probe
attempts at import time. Mitigation: check at 10B install time whether
any dormant Adeu submodule opens sockets on import; if so, either
restrict imports to `adeu.redline.engine` directly (bypassing
`adeu/__init__.py` re-exports) or widen policy narrowly.

**R3 — Prior-art prompting was built against Claude; we run MiniMax +
gpt-5.4.** The lawyer-shape rules in §2.2 were authored and iterated on
for Claude (likely Sonnet or Opus). Translating them to MiniMax-M2.7 is
not a code change, but may surface quality drift — e.g. MiniMax may be
more prone to whole-clause rewrites even with the rule present. Sprint
9 surprise 2 already showed MiniMax has reliability-tail issues on
forced structured output. Mitigation: 10D's first iteration runs on
MiniMax; if lawyer-shape fails consistently, swap to `openai/gpt-5.4`
via OpenRouter through the DI seam (one env-var change, ADR 011's
pattern). If neither meets the bar, that is a substantive finding
about model capability.

**R4 — Deep Agents `StateBackend` stores files as strings; Adeu wants
bytes.** The Deep Agents filesystem channel holds text (Sprint 6's
observation). A `.docx` is a zip of XML — pass it through as a string
and it breaks. Mitigation: the redline-specialist works on paths on
the real filesystem (e.g. `/sandbox/oscar-enterprise/tests/fixtures/ndas/...`
or `/tmp/oscar-redline/...`), not on the graph's files channel. The
tool takes an input path and writes to an output path. ADR for Sprint
10B to record this.

**R5 — Discriminated-union tool schemas through LangChain tool-binding.**
Adeu's `DocumentChange` is an annotated union of four Pydantic models
with a `type` discriminator. LangChain's tool-call JSON handling for
discriminated unions has historically been quirky (dropping the
discriminator when round-tripping). First-pass redlining only uses
`ModifyText`, so the MVP can bind `ModifyText` directly (single model,
no union) and add the other types when counterparty-response is built
in a later sprint. Mitigation: explicitly schema `ModifyText` in the
tool signature for Sprint 10B, do not pass `DocumentChange`.

**R6 — Latent `general-purpose` subagent pyramid (Sprint 6 surprise 3
→ Sprint 9 surprise 5).** Adding `redline-specialist` means GC, HOC,
redline-specialist each have a latent `general-purpose` subagent.
Prompt-level enforcement still applies. Not a new risk; a continued
one. No mitigation required beyond the standard prompt-level naming
discipline.

**R7 — Adeu API churn in a future version bump.** Claude-Plugin-MCP's
`adeu>=0.7.0` pin now references `DocumentEdit` and `adeu.anchor`,
neither of which exist in 1.1.0 — a concrete example of post-1.0
breaking changes. Mitigation: pin to `adeu==1.1.0` exactly. Budget
follow-up sprints for future bumps.

**R8 — Comment-discipline prompt is culturally English / common-law.**
The prior-art rules about over-commenting "signalling inexperience"
reflect English/Commonwealth solicitor norms. Oscar is pitched at
law-firm clients (PROJECT.md § What Oscar Is). Jurisdictional drift
in later sprints (US clients, civil-law clients) may want different
comment volumes. Not a Sprint 10 problem; flagged for later phases.

**R9 — "Open in Word without a repair dialog" cannot be automated in
the sandbox.** There's no Word (or LibreOffice) in the sandbox. The
structural proxy is `python-docx.Document(path)` loads cleanly + the
OOXML parses under `lxml`. A true "opens in Word" check requires a
manual step on the host. Mitigation: treat the programmatic check as
necessary-but-not-sufficient; document in the sprint log that
final visual verification is a human-host step.

**R10 — Test fixture `.docx` creation.** The three NDAs need to be
drafted and converted to `.docx`. Option (a): use
`python-docx` to generate them programmatically (boring but scriptable
and diffable in git). Option (b): author in Word on the host, commit
the binaries. (a) is more in keeping with the repo's "diffable source"
preference; (b) is closer to realistic client input. 10B or 10C
decides. Flagged here so the three-sprint split can schedule it
deliberately.

---

## Appendix — source references (what was read)

**Adeu (`/sandbox/reference-material/adeu/`):**

- `README.md`
- `pyproject.toml`
- `AI_CONTEXT.md`, `ARCHITECTURE.md`, `spec.md`
- `src/adeu/__init__.py` (public API)
- `src/adeu/models.py` (edit types)
- `src/adeu/ingest.py` (CriticMarkup extraction)
- `src/adeu/redline/engine.py` (RedlineEngine — the core)
- `src/adeu/mcp_components/tools/document.py`,
  `mcp_components/tools/sanitize.py`, `mcp_components/tools/validation.py`
- `src/adeu/server.py`
- `skills/adeu-redlining/SKILL.md`

**Claude-Plugin-MCP (`/sandbox/reference-material/claude-plugin-mcp/`):**

- `README.md`, `pyproject.toml`, `.mcp.json`,
  `.claude-plugin/plugin.json`, `scripts/start-mcp.sh`
- `skills/negotiate-contract/SKILL.md` (the main skill — 805 lines)
- `skills/yolo-negotiation/SKILL.md`
- `defaults/PERSONA.md`, `defaults/AUTHORITY.md`,
  `defaults/PLAYBOOK-template.md`
- `src/mcp_server/__main__.py`,
  `src/mcp_server/redline_tool.py`,
  `src/mcp_server/pipeline_tool.py`
- `src/pipeline/first_pass.py` (Adeu invocation pattern)
- `src/orchestration/negotiator.py` (top-level orchestration)

**Oscar's own framework source:**

- `/sandbox/.venv/lib/python3.13/site-packages/deepagents/middleware/subagents.py`
  (SubAgent + CompiledSubAgent fields; `response_format`; routing semantics)

PyPI index consulted: `pip index versions adeu` (28 versions; latest 1.1.0).

No fetches from external documentation URLs this sprint; all findings
read from source per CLAUDE.md's "code outranks docs" rule.
