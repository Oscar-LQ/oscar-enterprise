# Sprint 10Q — playbook layer feasibility (Phase 0, read-only)

Phase 0 research per Arturs's brief. The redline arc closed at 10P
production-acceptable on counterparty-response on the Acme NDA. Sprint
10Q lifts the redline track from per-round prompt-only operation to a
**playbook layer**: a per-client, per-document-type Word doc that drives
planner positions on first pass and yields to user direction on
subsequent passes, with divergence between direction and playbook flagged
visibly in the .docx and recorded in a structured audit trail.

This note covers six research areas (§1–§6). It does not propose code,
draft a Sprint 10Q brief, or modify the playbook concept Arturs has
specified.

---

## §1 — MCP playbook surface

**Finding: MCP has a playbook concept and it matches the shape Arturs
has specified almost exactly. Document the architecture, not just the
existence — Oscar can port directly.**

### Where the playbook lives in MCP

Three files / locations carry the MCP playbook:

1. **Shipped template** —
   `/sandbox/reference-material/claude-plugin-mcp/defaults/PLAYBOOK-template.md`
   (40-odd lines). Defines the per-clause structure: `### {Clause Name}`
   with bullets for `**Position:**`, `**Fallback:**`, `**Walk-away:**`,
   `**Notes:**`. Includes a "Catch-All Guidance" trailer naming the
   materiality test for clauses the playbook does not cover.

2. **Discovery + load chain** —
   `/sandbox/reference-material/claude-plugin-mcp/src/config/loader.py`
   (197 lines). The function relevant to playbooks:

   ```python
   # loader.py:99
   def _load_playbook(
       project_dir: str | None,
       explicit_path: str | None,
   ) -> str:
       """Load a playbook file from explicit path or project directory discovery.

       Playbooks are per-matter and do not fall back to global config. If no
       playbook is found, returns an empty string. When multiple PLAYBOOK-*.md
       files exist in the project directory, the first alphabetically is used.
       ...
       """
       if explicit_path is not None:
           if _has_path_traversal(explicit_path):
               return ""
           return _read_file_safe(explicit_path, "")

       if project_dir is not None:
           project_path = Path(project_dir)
           playbook_files = sorted(project_path.glob("PLAYBOOK-*.md"))
           if playbook_files:
               return _read_file_safe(str(playbook_files[0]), "")

       return ""
   ```

   Three-level discipline: explicit path → project-dir glob
   `PLAYBOOK-*.md` (alphabetical first wins) → empty string. **Crucially:
   playbooks do NOT fall back to global config** (the per-matter rule
   matches Arturs's per-document-type intent — one playbook per
   contract-type, not a global one). 1 MB hard limit
   (`_MAX_CONFIG_FILE_SIZE = 1_000_000`). Path-traversal protection.
   Whitespace-only files treated as empty.

3. **Pydantic model and consumption** —
   `/sandbox/reference-material/claude-plugin-mcp/src/config/models.py`:

   ```python
   # models.py:12
   class NegotiationConfig(BaseModel):
       """Loaded negotiation configuration.

       All string fields are markdown that Claude reads as prompt context.
       The engine never interprets this content -- it passes through to the
       LLM. The model also tracks whether custom configuration was found, which
       triggers the conversational setup flow when False.
       """
       persona: str
       authority: str
       playbook: str = ""
       has_custom_config: bool = False
   ```

   The docstring is the load-bearing architectural commitment: **the
   engine NEVER interprets the playbook**. The `negotiate()` orchestrator
   accepts `config: NegotiationConfig | None = None` only for audit
   trail (`negotiator.py:42-86`):

   > *"Optional NegotiationConfig for audit trail. Not used by the
   > pipeline -- by the time negotiate() is called, the LLM has already
   > read the config and produced decisions."*

### How MCP wires the playbook into the LLM context

MCP is a single-LLM pattern (Claude reads docs and produces decisions in
one call). The skill file
`skills/negotiate-contract/SKILL.md` instructs the LLM to load the
config in Step 1 of the workflow:

> *"Read the loaded persona, authority framework, and playbook (if any).
> These shape your judgment for the rest of the workflow."* (Step 1,
> SKILL.md:151–153)

Then in both the counterparty-response workflow (Step 4) and the
first-pass workflow (Step A):

> *"Combine the user's instructions with: the **persona** (who you are
> as a lawyer); the **authority framework** (what you can do
> autonomously vs. must flag); the **playbook** (clause-by-clause
> positions, if provided)."*

And the per-decision rule:

> *"If the playbook has a position on a clause type, follow it. General
> contextual judgment applies only to clause types the playbook does
> not cover."* (Step 5, SKILL.md:315–316)

The README (`README.md:40, 84–87`) names PERSONA / AUTHORITY / PLAYBOOK
as the **three configurable layers** of the negotiation stack, each
file-discovered, each markdown, each passed through to the LLM verbatim.

### The conversational setup flow

`src/config/defaults.py:129 SETUP_PROMPT` describes a four-question
intake (practice type / area / negotiation style / risk tolerance) that
generates tailored `PERSONA.md` and `AUTHORITY.md` content via
`write_global_config(persona, authority)`. Notably, the setup flow does
NOT generate a playbook — the playbook is treated as a per-matter
artefact the user produces themselves (matching Arturs's "playbooks are
client-driven, not LLM-generated" constraint).

### Recommendations

- **Port `src/config/loader.py` and `src/config/models.py` into
  `src/redline/lib/`** as the playbook discovery + loading layer.
  ~250 LoC combined (loader + models + defaults). All Python stdlib +
  Pydantic. No MCP-specific dependencies.

  Adaptations Oscar needs:
  - Per-VPS deployment makes the global-config tier (`~/.config/...`)
    redundant for playbooks (already excluded from MCP's
    `_load_playbook`). Keep MCP's per-matter rule as-is.
  - Glob pattern `PLAYBOOK-*.md` is good as-is — Oscar's per-document-type
    naming would be e.g. `PLAYBOOK-NDA.md`, `PLAYBOOK-MSA.md`,
    `PLAYBOOK-employment.md`. The "first alphabetically" tiebreak can
    be removed in favour of explicit-path-only when the document type is
    known at run time (Oscar's planner is invoked with a
    `document_type` argument; the loader is asked for the playbook of
    that type by name).

- **Adopt MCP's "engine never interprets, LLM reads as prompt
  context" rule verbatim.** Sprint 10Q's playbook is a string (the
  Word doc rendered as text) inserted into the planner's system prompt
  or user message. No structured parsing. No rule registry. The shape
  is "additional prompt text", not "additional code path".

- **Rename `NegotiationConfig` to `RedlineConfig` (or similar) and
  drop the persona/authority fields for now.** Oscar already has
  per-agent prompts that carry the persona/authority load. The 10Q port
  is the playbook-only slice. Adding persona/authority infrastructure
  is a separate decision Arturs hasn't asked for and would expand
  scope.

- **Note a forward connection**: MCP supports plain-text playbooks
  while Arturs has specified Word docs. The playbook's content shape is
  the same (markdown-style clause-by-clause); the file format differs.
  Either (a) lawyers maintain `.md` files (cleanest, but lawyers think
  in Word), or (b) Oscar reads `.docx` playbooks via Adeu's text
  extraction or python-docx (matches lawyer ergonomics). Recommend (b)
  with the loaded text injected as if it were markdown — the text
  shape from a structured Word doc with headings + bullets renders to
  the planner the same way MCP's markdown does. **Open question for
  Arturs:** does he want a `.docx` playbook (lawyer-natural, parsing
  needed) or a `.md` playbook (parser-free, lawyer learns Markdown)?

### Open questions for Arturs

- **Playbook file format** — `.md` (MCP-shape, parser-free) or `.docx`
  (lawyer-natural, ~30 LoC of python-docx text extraction, possibly
  losing inline formatting)?
- **Per-document-type discovery** — explicit-path-only (planner caller
  passes `playbook_path` argument) or glob-by-type (planner asks for
  `PLAYBOOK-NDA.md` and gets the file matching that name in the
  client-VPS playbook directory)?
- **Empty-playbook behaviour** — first-pass with no playbook should
  fall back to direction-only operation (similar to MCP's
  `playbook: str = ""` default), or block with an "uninitialised
  client" error?

---

## §2 — Deep Agents memory abstraction

**Finding: Deep Agents 0.5.3 has two relevant middleware primitives
(`MemoryMiddleware` and `SkillsMiddleware`) that load file-discovered
markdown into the system prompt. Their *shape* is closely aligned with
the playbook concept, but Oscar's pipeline since 10I deliberately runs
direct `chat_model.invoke()` outside the Deep Agents harness. Oscar
should NOT reach for `MemoryMiddleware` for this; it should adopt the
*pattern* (file-discovered markdown → system prompt) without the
framework dependency.**

### `MemoryMiddleware` — shape and constraints

`/sandbox/.venv/lib/python3.13/site-packages/deepagents/middleware/memory.py`,
~355 lines. Public class signature:

```python
# memory.py:159
class MemoryMiddleware(AgentMiddleware[MemoryState, ContextT, ResponseT]):
    """Middleware for loading agent memory from `AGENTS.md` files.

    Loads memory content from configured sources and injects into the system prompt.

    Supports multiple sources that are combined together.
    """
    def __init__(
        self,
        *,
        backend: BACKEND_TYPES,
        sources: list[str],
    ) -> None: ...

    def before_agent(self, state, runtime, config) -> MemoryStateUpdate | None: ...
    def modify_request(self, request) -> ModelRequest: ...
    def wrap_model_call(self, request, handler) -> ModelResponse: ...
```

Mechanics:
- `before_agent` reads `sources` (list of paths) via the backend, stores
  each file's content in `state.memory_contents: dict[path, str]`.
- `modify_request` formats the contents with a fixed `MEMORY_SYSTEM_PROMPT`
  template wrapping `<agent_memory>` + per-source path/content
  pairs, and appends the block to `request.system_message` via
  `append_to_system_message`.
- Sources are concatenated in order; multiple sources fully included.
- Backend is pluggable: `FilesystemBackend(root_dir="/")`,
  `StateBackend()` (ephemeral, in-memory only), composite, sandbox,
  langsmith. `StateBackend` has explicit "not across threads" persistence
  (see `state.py:39-48`).

The `MEMORY_SYSTEM_PROMPT` template (memory.py:97–156) is heavy with
**LLM-driven self-modification instructions**: *"updating memory must be
your FIRST, IMMEDIATE action — before responding to the user, before
calling other tools"*; *"As you learn from your interactions with the
user, you can save new knowledge by calling the `edit_file` tool."*
This template is not appropriate for Oscar's playbook layer:
- Arturs's constraint #1: *"playbooks are Word documents, client-driven,
  not LLM-generated"* — the LLM should not be modifying the playbook
  via tool calls.
- The template is conversational-scratchpad-shaped, not legal-positions-
  shaped.
- The instruction set bleeds into the planner's reasoning frame.

### `SkillsMiddleware` — shape and constraints

`/sandbox/.venv/lib/python3.13/site-packages/deepagents/middleware/skills.py`,
~835 lines. Implements the **Agent Skills specification**
(https://agentskills.io/specification): each skill is a directory
containing `SKILL.md` with YAML frontmatter (`name`, `description`,
optional `license` / `compatibility` / `metadata` / `allowed_tools`).
Progressive disclosure: the system prompt lists name + description for
each available skill, the LLM reads the full content via `read_file` on
demand.

This is closer to a "library of pluggable knowledge files" than to a
"persistent context" pattern. Not a clean fit for the playbook (which
is mandatory, not on-demand).

### Why Oscar should NOT use the Deep Agents middleware

Three reasons:

1. **Architectural mismatch with Oscar's current pipeline.** Sprint
   10I onwards (10I, 10J, 10K, 10L, 10M, 10N, 10O, 10P, 10P-prep)
   uses direct `chat_model.invoke()` calls without Deep Agents. The
   pipeline at `src/redline/experiments/sprint-10P/pipeline.py` is a
   plain Python orchestrator: planner call → JSON parse → executor call
   per counter-propose decision → dispatcher applies actions via Adeu +
   ported MCP helpers. There is no `AgentMiddleware` lifecycle to hook.
   Adopting `MemoryMiddleware` would require regressing to a Deep Agents
   harness — at minimum for the planner stage — to gain access to a
   feature (file → system prompt) that is structurally trivial.

2. **The middleware's prompt template encourages LLM self-update**,
   which violates Arturs's constraint #1.

3. **Per-VPS deployment makes the abstraction redundant.** The
   `BackendProtocol` exists to abstract over filesystem / cloud / agent
   state for cross-environment portability. Oscar runs on a single
   client VPS with a real filesystem — there is nothing to abstract.

### What Oscar SHOULD do

- **Build minimal own infrastructure (~50–100 LoC)** OR port MCP's
  `src/config/loader.py` (~200 LoC including helpers; covered in §1).
  Either way: stdlib `pathlib` + `Path.read_text()`, no framework.
- **Inject playbook text into the planner's system prompt at
  `prompt_builder.py` construction time.** Sprint 10P already has
  `load_planner_system_prompt()` reading
  `planner_prompt.txt`. Adding a `## Playbook` section after the
  behavioural rules — interpolated from the loaded playbook file at
  runtime — fits the existing shape and adds zero infrastructure.

### Recommendation

Oscar's playbook layer is a stdlib Python file-load + a
prompt-construction interpolation. Deep Agents' `MemoryMiddleware`
provides the same conceptual shape but at a higher infrastructure cost
and with prompt-template baggage that conflicts with the
human-authority constraint. **Recommend: port MCP's `loader.py`
shape; do not use `MemoryMiddleware`.** If Oscar later needs the
agent-state-backed memory pattern (e.g. for accumulated
matter-decision history; see §6), revisit the Deep Agents middleware
at that point — it remains available as a forward option.

### Open questions for Arturs

- None — the recommendation is clear given the existing pipeline shape.
  Confirmation rather than direction.

---

## §3 — Planner prompt structure for four inputs

**Finding: the existing 10P planner prompt has a clean three-input
shape (state-of-play + brief + original document). Adding the
playbook as a fourth input is structurally a system-prompt
interpolation, with first-pass / subsequent-pass mediation living in
the behavioural-rules section. Divergence detection is a new
LLM-reasoning task that emits an additional per-decision field;
session-mute is a brief-parsed boolean threading from run.py through
the dispatcher.**

### Where the playbook lives in the prompt

The current planner prompt
(`src/redline/experiments/sprint-10P/planner_prompt.txt`) has:

- **System prompt** — role; inputs list; behavioural rules (5);
  decision schema; decision selection guide; cross-reference framing;
  preserve-list discipline; cross-clause patterns; comment_text
  conventions.
- **User message** (built in `prompt_builder.py:51 build_planner_user_prompt`)
  — `PARTNER'S BRIEF:` + `STATE OF PLAY:` JSON + `ORIGINAL NDA:` clean
  text, in that order, separated by `---`.

For the playbook, two architecturally clean options:

1. **System prompt interpolation.** A new section is appended to
   `planner_prompt.txt` at load time with the loaded playbook content
   under `## CLIENT PLAYBOOK ({document_type})`. The standing positions
   live where the standing rules already live.

2. **User message section.** A new `CLIENT PLAYBOOK:` block is added to
   the user message, between `PARTNER'S BRIEF:` and `STATE OF PLAY:`.

**Recommend option 1 (system prompt).** The playbook is persistent
across rounds (matches the system-prompt layer); the brief is
per-round (matches the user-message layer). MCP's design (loaded once,
combined with persona + authority, pinned at the top of the
conversation) reflects the same separation. Cross-version porting
discipline (CLAUDE.md) reinforces this — adopt MCP's load-bearing
architectural choices when porting the pattern, not just the surface
syntax.

### First-pass vs subsequent-pass mediation

Arturs's design move:
- **First pass** — playbook IS the source of positions
- **Subsequent passes** — playbook becomes principles; user direction
  beats playbook on conflict

Detection rule: state-of-play empty (no tracked changes inbound) implies
first pass; state-of-play populated implies subsequent pass. This is
already determined upstream of the planner (the doc analyser produces
the state-of-play from the input `.docx`); the planner sees the
state-of-play and can branch on `len(state.changes) == 0`.

The behavioural-rules section needs a new rule (proposed wording — for
Arturs to refine):

> *"6. Playbook is positions on first pass; principles on subsequent
> passes. When the state-of-play is empty, the client playbook is
> your source of positions — apply each clause's `**Position:**`
> unless the partner's brief overrides explicitly. When the
> state-of-play has tracked changes, the partner's brief is the
> operational layer; the playbook becomes principles for borderline
> calls and for clauses the brief does not address. Direction beats
> playbook on conflict."*

### Divergence detection — a reasoning task, not a parser task

When the planner's decision (driven by direction) departs from what the
playbook position is for the relevant clause type, the planner must
recognise the divergence and surface it. This is exactly the
"compare-and-flag" reasoning shape that MCP's per-decision evaluation
already handles for the materiality test — adding a divergence
sub-step is structurally similar.

Schema extension (added to the decision shape in
`planner_prompt.txt`):

```
{
  "change_id": "...",
  "action": "...",
  ...existing fields...,

  "divergence_from_playbook": null | {
    "playbook_position": "<verbatim quote from the relevant playbook clause's Position/Fallback>",
    "decision_taken": "<one-line summary of what the planner decided>",
    "divergence_reason": "<why direction or context overrode the playbook>",
    "playbook_clause_heading": "<### heading the position came from>"
  }
}
```

The planner emits a non-null `divergence_from_playbook` whenever its
chosen action does not match what the playbook would have said. When
the playbook is silent on a clause type, the field stays null (the
catch-all guidance applies; no divergence to flag).

### Comment text on divergence

When `divergence_from_playbook` is non-null, the planner emits a
canonical divergence comment text — separate from the regular
`comment_text` so the dispatcher can render it independently.

Schema extension:

```
{
  ...,
  "divergence_comment_text": "<one-sentence text suitable for an Oscar Counsel comment in the .docx, naming the playbook position and the reason for departure>"
}
```

Recommended canonical wording (proposed for the prompt — for Arturs to
refine):

> *"This decision departs from playbook position [{playbook_clause_heading}] at the user's direction: {divergence_reason}."*

The dispatcher renders this as an Oscar Counsel comment attached to the
relevant paragraph alongside (or instead of) the regular `comment_text`.
Always populated when divergence is non-null; suppressed at render time
when session-mute is on (see §4).

### Session-mute mechanics

Arturs's design: user can say in their direction *"stop flagging
divergences for this session"*; planner respects for the rest of the
session; audit trail still records divergences regardless.

Architectural placement of mute state:

- **Not in the planner output** — the planner always populates
  `divergence_from_playbook` and `divergence_comment_text` regardless of
  mute (audit trail does not care about mute).
- **Not in the system prompt** — mute is per-round, not standing.
- **In a thin pre-processor at run.py** — parse the user's brief at
  start of round for mute keywords / phrases, lift to a
  `SessionConfig(suppress_divergence_flags: bool)` dataclass, pass
  alongside the planner output to the dispatcher.

The dispatcher reads `session.suppress_divergence_flags`:
- if True: skip rendering the divergence visible flag; still write to
  audit trail
- if False (default): render the visible flag as an Oscar Counsel
  comment; still write to audit trail

Mute parsing is keyword-based, not LLM-based — Arturs's intent is
deterministic and audit-trail-friendly. Phrases to recognise (proposed):
"stop flagging divergences", "don't flag divergences", "suppress
divergence flags this session", "mute divergence flags". A small
keyword-match function in `run.py` is sufficient.

The planner does NOT need to know about mute. Cleaner separation of
concerns.

### Implications for prompt size and reasoning load

Adding the playbook as system-prompt content increases token count by
the playbook's length (typically 1k–5k tokens for a clause-by-clause
playbook of 10–20 clauses). At 10P scale (planner produces 18
decisions in 128.7s on gpt-5.5 non-Pro), this is well within budget.
Cross-clause reasoning on top of playbook + brief + state-of-play is
the cognitive lift — the unresolved 10O/10P-prep question of
"GPT-5.5 non-Pro cross-document propagation ceiling" extends here.
Sprint 10Q should anticipate that the playbook layer may surface that
ceiling more sharply (more cross-clause patterns to detect when
playbook is in the picture).

### Open questions for Arturs

- **Playbook position in prompt** — system prompt (recommended) or user
  message?
- **Divergence schema** — proposed shape acceptable, or different
  structure preferred?
- **Divergence comment wording** — canonical template acceptable, or a
  different shape (e.g., link to playbook clause heading inline)?
- **Mute keywords** — keyword-based parser acceptable, or should mute
  be a structured argument to run.py (e.g., a CLI flag) rather than
  parsed from the brief?
- **Divergence on first pass** — when playbook IS the source of
  positions, does any deviation from playbook still count as
  divergence? Or is divergence only meaningful on subsequent passes
  where direction can override?

---

## §4 — Divergence flagging mechanism

**Finding: three layers (visible flag, audit trail, mute) compose
cleanly on top of 10P's existing dispatcher and parsed-plan.json
artefacts. The audit trail file is a new sibling artefact;
the visible flag is an Oscar Counsel comment routed via Stage C of the
existing comment-attaching pipeline; the mute toggle threads from
run.py through the dispatcher.**

### Layer 1: Visible flag in .docx output

**Mechanism**: an Oscar Counsel comment attached to the paragraph
where the divergence occurs. Same code path as the regular
`comment_text` / `accept_with_comment` flow — uses the
`add_comments_inplace` ported infrastructure that 10P validated
(`src/redline/lib/add_comments_inplace.py`). The dispatcher already
attaches comments per-decision in Stage C; adding a divergence
comment is one more comment per affected decision when mute is off.

Two possible attachment shapes:
- (a) **Single combined comment** — divergence text prepended to the
  regular `comment_text` (e.g., *"[Departs from playbook on
  Affiliates] Counter-proposed Affiliates only — extending to
  contractors expands the disclosure perimeter beyond what Acme can
  monitor under §6."*).
- (b) **Two separate comments** on the same paragraph — one for the
  regular comment, one for the divergence flag.

**Recommend (a) single combined comment.** Two comments on the same
paragraph clutters the Word review pane; the divergence prefix in
square brackets is enough signal to a partner reading the redline.
Word's comment count remains 1:1 with paragraphs; audit trail still
records both.

**Author**: "Oscar Counsel" (the redline-author-config name, same as
all other Oscar comments in 10P). Divergence flags do NOT get a
separate author — they ARE Oscar Counsel observations.

**Suppression**: when `session.suppress_divergence_flags = True`, the
dispatcher emits the comment WITHOUT the divergence prefix — i.e.,
falls back to the regular `comment_text` only. The divergence is still
recorded in the audit trail (Layer 2).

### Layer 2: Structured audit trail

**Mechanism**: a new JSON file `divergence-audit.json` in the
sprint-output directory alongside `parsed-plan.json` and
`parsed-edits.json`. Always written, regardless of mute.

Schema (one entry per divergence — decisions with
`divergence_from_playbook == null` are NOT recorded; only divergences
go in the audit file):

```json
[
  {
    "change_id": "Chg:7",
    "action": "counter_propose",
    "playbook_clause_heading": "### Affiliates",
    "playbook_position": "Affiliates only — extend to contractors only with separate confidentiality agreement",
    "decision_taken": "counter_propose to broaden to Affiliates + qualified contractors",
    "divergence_reason": "partner brief specifies a one-time accommodation for this counterparty's vendor model",
    "session_mute_active": false,
    "rendered_visible_flag": true,
    "timestamp_iso": "2026-04-26T..."
  }
]
```

`session_mute_active` and `rendered_visible_flag` are recorded so the
audit trail itself is inspectable for whether the visible flag was
rendered at all — useful when the partner reviews retrospectively or
for compliance audit.

**Append-only discipline** (per PROJECT.md Audit principle): the file
is recreated per round (not modified across rounds); per-matter
accumulation is achieved by accumulating the per-round files in a
matter-level archive (an open question for §6 / future sprints, not
10Q).

### Layer 3: Session mute toggle

**Mechanism**: a thin keyword-match parser at the front of run.py
inspects the partner's brief for mute keywords; if matched, sets
`SessionConfig(suppress_divergence_flags=True)`; passes through to the
dispatcher.

Proposed keyword list (regex case-insensitive — finalising the list is
an Arturs decision):

- `stop flagging (the )?divergences?` (with optional "the")
- `don'?t flag (the )?divergences?`
- `(suppress|mute) divergence flags?`

The keyword match happens BEFORE the planner is invoked. The planner
never sees the mute state; its output is deterministic given the
inputs. The dispatcher reads the mute state and conditionally renders.

**Why not a CLI flag instead?** Arturs's intent is that the user
expresses mute in natural-language direction (the same channel as the
brief), not a separate CLI / metadata layer. The keyword parser
preserves that user surface.

**Why not LLM-parsed?** Determinism and audit. A keyword match is
inspectable and reproducible; a model-parsed mute introduces another
LLM judgement layer that could drift. Audit-trail principles favour the
deterministic path.

### Where each piece lives in the code

Mapping to 10P's structure:

| Concern | File | New / extension |
|---------|------|-----------------|
| Mute keyword parser | `run.py` | New ~20 LoC function |
| `SessionConfig` dataclass | `run.py` (or new `session.py`) | New |
| Planner divergence schema | `planner_prompt.txt` | Schema extension only |
| Audit trail writer | `pipeline.py` (or new `divergence_audit.py`) | New ~50 LoC |
| Visible flag rendering | `pipeline.py` (Stage C comment attachment) | Adapt comment_text construction |
| Comment author | `author_config.py` | No change — already "Oscar Counsel" |

Net new code: ~150–200 LoC for the divergence layer mechanics, on top
of the playbook loader (§1) and the prompt extensions (§3).

### Open questions for Arturs

- **Combined vs separate comments** — recommended (a) single combined
  comment with prefix; confirm or specify (b) two-comment pattern.
- **Audit trail granularity** — divergences-only (recommended) or
  every decision with a `divergence: null | object` field (richer but
  larger artefact)?
- **Audit trail location** — same dir as parsed-plan.json
  (recommended) or separate per-matter archive directory?
- **Mute keyword list** — three patterns above acceptable, or extend?
- **Cross-round mute persistence** — mute resets per round
  (recommended — each round is its own session) or persists across
  rounds within a matter?

---

## §5 — Test artefact: compute-capacity MSA

**Finding: no public template exists in a form Oscar can adopt
verbatim. The cleanest path is to start from a hyperscaler's published
customer-side terms (which Oscar already has analytical access to as a
publicly-published document), mark it provider-favourable, and let the
G42-style customer-side MSA playbook do the work of pushing it back —
the playbook does the customer-side heavy lifting, the test artefact
provides the raw provider clay. Customer-side MSA playbook coverage is
a 10–13 position cluster.**

### Survey of public templates

Five candidates considered. Key honest caveats:

1. **AWS Customer Agreement** (`aws.amazon.com/agreement`)
   - Length: ~5–7 pages of core terms; product-specific terms attached
     as referenced annexes (significantly more if all annexes counted)
   - Structure: high-level sections — service availability, fees,
     suspension/termination, indemnification, limitation of liability,
     governing law (US-state-specific defaults). Click-through.
   - Adaptable to customer-side: substantially, but it is written as a
     public clickwrap for one-side acceptance — not a negotiated MSA.
     Customer-side adaptation requires adding clauses (custom audit
     rights, data residency commitments, performance SLAs, regulatory
     cooperation) that providers do not include in clickwrap.
   - Licensing: published terms — analytical use (testing, redlining)
     is generally fine; redistributing the test fixture publicly in
     Oscar's repo is a separate consideration.
   - **Verdict**: too thin as a standalone MSA test fixture. Useful as
     reference for hyperscaler boilerplate.

2. **Microsoft Customer Agreement / Azure Online Services Terms**
   - Length: substantially longer (~40+ pages with product-specific
     terms; the "Microsoft Customer Agreement" itself is shorter — ~10
     pages). Both publicly available.
   - Structure: enterprise-focused; defined-term-heavy; multiple
     referenced policies. The Customer Agreement is closer to MSA-shape
     than AWS Customer Agreement.
   - Adaptable: better than AWS; written for negotiated enterprise
     deals.
   - Licensing: same caveat as AWS.
   - **Verdict**: candidate for the test-artefact base. Closest to
     enterprise MSA shape among the public hyperscaler agreements.

3. **Google Cloud Master Agreement**
   - Length: shorter than Microsoft's (~15 pages depending on which
     version is referenced).
   - Structure: similar to AWS — provider-side, click-through.
   - Adaptable: similar to AWS.
   - **Verdict**: similar to AWS. Microsoft's Customer Agreement is
     richer.

4. **Oracle Cloud Services Agreement / IBM Cloud Service Agreement**
   - Length: comparable to Google.
   - Structure: similar shape; provider-side; click-through with
     enterprise-negotiable annexes.
   - **Verdict**: same as Google. No clear advantage over Microsoft.

5. **OpenAI Enterprise Agreement / OpenAI Business Terms**
   - Length: business terms ~5–8 pages; full Enterprise Agreement
     not generally published.
   - Structure: focuses on AI-specific terms (model access, rate
     limits, IP-of-outputs, no-training-on-customer-data
     commitments, prompt-injection liability disclaimers). Other
     standard MSA elements (general indemnity, term, notice
     mechanics) are present but lighter.
   - Adaptable: VERY relevant for AI-compute-flavoured MSA test —
     the AI-specific clauses are exactly what a G42 / CloudCo
     contract would centre on.
   - **Verdict**: useful as a SOURCE OF AI-SPECIFIC CLAUSES to
     graft into the Microsoft-shaped base — not a standalone
     test artefact.

6. **SEC EDGAR filings of compute-capacity arrangements**
   - Many large compute deals are disclosed in 10-K / 8-K filings
     (CoreWeave, Nebius, Microsoft-OpenAI Stargate references).
     Filings may include redacted MSA exhibits.
   - Length: when filed, full MSAs (40–80+ pages, redacted).
   - Adaptable: actual negotiated agreements between named parties —
     closer to where Oscar's test should land than provider-published
     clickwrap.
   - Licensing: SEC filings are public; analytical use is
     unambiguously OK. Redistribution carries the named-party
     attribution caveat.
   - **Verdict**: would be the cleanest source if a specific compute
     MSA filing can be identified. **Cannot identify a specific
     filing without web search; flag for Arturs to check or for a
     Phase 0.5 with web access.**

7. **LawInsider / DocSeq / CommonAccord public template repos**
   - Crowdsourced templates, mixed quality. Search terms to investigate
     in Phase 0.5: "cloud services master agreement", "compute capacity
     agreement", "AI infrastructure services agreement",
     "infrastructure-as-a-service master agreement".
   - **Verdict**: useful supplement; not a primary source.

### Recommendation (updated 2026-04-26 per Arturs's pushback — see addendum below)

**SEC EDGAR addendum follows.** A focused EDGAR search surfaced four
named, real, recent compute-capacity MSAs filed as exhibits — the
"alternative if web access available" path is real and
preferable to the Microsoft + OpenAI synthetic hybrid. See addendum.

**Original (synthetic-hybrid) fallback** stays available if EDGAR
candidates fail document-shape review: Microsoft Customer Agreement
(or equivalent hyperscaler enterprise agreement) as the structural
base + OpenAI Enterprise Business Terms grafted in as the AI-specific
clause cluster. Arturs edits the result into a single
CloudCo-attributed `.docx` of ~40–60 pages.

### Addendum: SEC EDGAR candidates (post-Phase-0, 2026-04-26)

**Finding: SEC EDGAR has multiple high-quality compute-capacity MSA
candidates filed as exhibits in 2025–2026. Four named candidates
identified; document-shape review of any one of them was
constrained by SEC.gov returning HTTP 403 to programmatic fetches in
this environment (consistent with SEC anti-scrape defaults that
require a User-Agent identifier with contact email per their
[fair-access policy](https://www.sec.gov/os/accessing-edgar-data)).
Arturs (or a future session with browser access) can fetch directly
and confirm document-shape readiness; the named candidates and their
URLs are documented below.**

#### Candidate inventory

**Candidate 1 — CoreWeave–Customer Master Services Agreement (Bare-Metal Environment).**
- **Filing**: SEC EX-10.24, filed in CoreWeave's S-1 registration
  statement (CIK 1769628, filing index 000119312525052207).
- **URL**: `https://www.sec.gov/Archives/edgar/data/1769628/000119312525052207/d899798dex1024.htm`
- **Customer**: redacted in filing as "Customer"; widely reported in
  the financial press as OpenAI but SEC-filed version is anonymised.
- **Provider side**: CoreWeave — direct AI-compute hyperscaler.
- **Side that filed**: provider (CoreWeave is the registrant).
- **Shape**: dedicated MSA for a bare-metal-environment GPU cloud
  arrangement — closest possible match to the G42-style "AI compute
  capacity reservation" frame Arturs has specified for Sprint 10Q.

**Candidate 2 — CoreWeave–Customer Master Services Agreement.**
- **Filing**: SEC EX-10.23, filed in CoreWeave's S-1 (same registrant,
  filing index 000119312525044231).
- **URL**: `https://www.sec.gov/Archives/edgar/data/1769628/000119312525044231/d899798dex1023.htm`
- **Customer**: redacted as "Customer".
- **Provider side**: CoreWeave.
- **Shape**: general MSA (vs the bare-metal-specific Candidate 1).
  The pair (EX-10.23 + EX-10.24) gives both a general and a
  capacity-specialised MSA from the same provider, suggesting
  CoreWeave operates a layered framework — useful structural
  reference for what playbook positions need to address.

**Candidate 3 — CoreWeave–OpenAI Master Services Agreement (earlier S-1 filing).**
- **Filing**: filed as exhibit in CoreWeave SEC filing (CIK 1769628,
  filing index 000114036125036118, exhibit 10-31).
- **URL**: `https://www.sec.gov/Archives/edgar/data/1769628/000114036125036118/ny20053122x6_ex10-31.htm`
- **Customer**: OpenAI (named, not redacted to "Customer" in this
  particular filing).
- **Provider side**: CoreWeave.
- **Shape**: explicit named-party version of the CoreWeave–OpenAI
  arrangement at S-1 filing date — earlier counterpart of Candidate 4
  below.
- **Mirror**: Justia at
  `https://contracts.justia.com/companies/coreweave-inc-103508/contract/1318200/`
  (also returned 403 in this fetch).

**Candidate 4 — CoreWeave–OpenAI Master Services Agreement (2025-09-25 8-K).** ★ **Sprint 10Q test fixture — Arturs's selection 2026-04-26.**
- **Filing**: Exhibit 10.1 to CoreWeave Form 8-K dated 2025-09-25.
- **URL**: `https://www.sec.gov/Archives/edgar/data/1769628/000119312525216497/d17274dex101.htm`
- **Customer**: **OpenAI OpCo, LLC** (named; signed by Sam Altman as
  CEO — verified by Arturs via direct fetch). Earlier draft of the
  research note misidentified this exhibit as a CoreWeave–Meta MSA
  based on press coverage of the September 2025 Meta deal in the same
  filing window; the EX-10.1 itself is the OpenAI MSA. Corrected
  2026-04-26.
- **Provider side**: CoreWeave.
- **Shape**: most recent drafting practice (mid-2025); customer-side
  perspective from a sophisticated AI buyer; both parties had top-tier
  counsel; negotiated balance reflects real positions; closer analogue
  to G42's actual deal flow than the (separate) Meta MSA would be —
  G42 is a customer; Meta is a hyperscaler.
- **Specific clause noted**: §7(a) export-controls representation
  directly relevant to G42's US-UAE-China triangulation context.
- **Verdict**: all 13 position categories from the customer-side MSA
  playbook map onto real clauses in this MSA. Sprint 10Q test fixture.

#### Cerebras–G42 master agreement — referenced but not directly accessible

Cerebras's S-1 (refiled April 2026 after CFIUS review concluded
October 2025) references a master agreement with G42 governing
revenue concentration of 87% in H1 2024, ~$300M July 2023 commitment +
~$1.43B May 2024 expansion + option to acquire Cerebras shares at
discount tied to spending between $500M and $5B by end of 2025
(per EE Times reporting on the filing). Whether the master agreement
itself is filed as an exhibit (vs being summarised in the body of the
S-1 with confidential treatment for the agreement document itself) is
unclear from search results; direct EDGAR access required.

- **Cerebras S-1 (April 2026)**: `https://www.sec.gov/Archives/edgar/data/2021728/000162828026025762/cerebras-sx1april2026.htm`
- **Original Cerebras S-1 (September 2024)**: `https://www.sec.gov/Archives/edgar/data/2021728/000162828024041596/cerebras-sx1.htm`

This is the closest public document touching the actual G42-side
sovereign-AI compute deal Arturs's brief named as Sprint 10Q's
production context. **Direct EDGAR fetch is the next step here** —
search-result summaries do not establish whether the exhibit is filed
in clean form or whether confidential-treatment redaction has
preserved enough operational substance for a meaningful Oscar test.

#### Applied Digital hyperscaler lease exhibits — secondary candidates

Applied Digital's 8-K filings disclose multi-billion-dollar AI
data-centre lease arrangements with un-named hyperscaler
counterparties:
- 2025-10-22 Polaris Forge 2: ~$5B, 200 MW, 15-year term (8-K filed
  CIK 1144879)
- 2026-04-23 Delta Forge 1: ~$7.5B, 300 MW, 15-year term

These are lease-style not MSA-style — different document shape from
the CoreWeave compute MSAs. The lease form would be a useful
secondary fixture if Sprint 10Q (or a future sprint) tests against
data-centre infrastructure rather than compute services. Not
recommended as Sprint 10Q's primary fixture given the brief specifies
compute capacity rather than colocation.

- **2025-10-22 8-K**: `https://ir.applieddigital.com/sec-filings/all-sec-filings/content/0001144879-25-000076/0001144879-25-000076.pdf`
- **2026-04 8-K**: `https://ir.applieddigital.com/sec-filings/all-sec-filings/content/0001144879-26-000036/0001144879-26-000036.pdf`

#### Redaction level — open question

SEC compute-MSA exhibits typically employ confidential-treatment
redaction for pricing, capacity numerics, technical specifications,
and identity of the customer counterparty. Press summaries of the
CoreWeave-NVIDIA MSA confirm "[redacted]" markers in operative
clauses governing capacity allocation. **What remains visible in the
typical post-redaction filing** (per general SEC compliance practice;
not directly confirmed for these four exhibits in this session):

- All clause headings and structural skeleton
- Most boilerplate (governing law, dispute resolution, notice,
  assignment, force majeure)
- Term, termination, suspension provisions
- Indemnity scope (caps and supercaps may be redacted; structure
  visible)
- Warranty and disclaimer language
- Intellectual property allocation framework
- Service-level commitment shape (numerics typically redacted; SLA
  structure visible)
- Audit-rights structure
- Confidentiality framework

**For a redline test, structural skeleton + visible boilerplate is
sufficient.** Sprint 10Q's playbook tests the planner's
position-on-clause-shape reasoning, not its number-comparison
reasoning. A redacted-but-structurally-complete CoreWeave–Customer
MSA should give the planner enough surface area to exercise the 13
position categories in the customer-side MSA playbook.

#### Licensing for SEC-filed exhibits

SEC filings are public-domain documents. Analytical use, redlining,
and inclusion in test fixtures are unambiguously permissible. **No
fictionalisation pass is required for internal testing** — the earlier
draft's "global rename to CloudCo / Sovereign AI Holdings"
recommendation is superseded for Sprint 10Q. If/when external-facing
material references the test (video demo, pitch deck, public-facing
case study), fictionalisation or anonymisation becomes a separate
decision at that point.

#### Decision (Arturs, 2026-04-26)

**Sprint 10Q test fixture: CoreWeave–OpenAI MSA, Exhibit 10.1 to the
2025-09-25 CoreWeave 8-K.** Reasons (per Arturs):

- Most recent drafting practice (mid-2025); reflects current market
  on AI compute infrastructure deals
- Customer-side perspective (OpenAI as buyer); matches the test
  framing for Sprint 10Q's customer-side MSA playbook
- All 13 playbook position categories from §5 map onto real clauses
  in this MSA (verified by Arturs via direct fetch)
- Both parties had top-tier counsel; negotiated balance reflects real
  positions
- Closer analogue to G42's actual deal flow than the Meta MSA would
  be — G42 is a customer; Meta is a hyperscaler
- Public domain (SEC filing); usable for internal testing as-is, no
  fictionalisation
- §7(a) export-controls representation directly relevant to G42's
  US-UAE-China triangulation context

**Cerebras–G42 standalone-exhibit existence remains an open follow-up**
but is not Sprint 10Q's blocker. If a future sprint wants the
highest-fidelity G42 production analogue, the Cerebras April 2026 S-1
and September 2024 S-1 filings are the place to look.

#### Action items before Sprint 10Q drafts

These actions belong on a Sprint 10Q feature branch (or an interim
fixture-prep branch); they are NOT main-branch research-note work.

1. **Fetch the full text of EX-10.1** at
   `https://www.sec.gov/Archives/edgar/data/1769628/000119312525216497/d17274dex101.htm`.
   SEC's anti-scrape gate requires a User-Agent containing a contact
   email per
   [SEC fair-access policy](https://www.sec.gov/os/accessing-edgar-data);
   set the header accordingly when fetching programmatically.

2. **Convert HTML to .docx** for Sprint 10Q's pipeline. Two viable
   paths: (a) `python-docx` constructs the .docx from parsed HTML
   structure; (b) `pandoc` handles HTML-to-docx directly. Verify the
   converted .docx renders in Word correctly (paragraph structure,
   headings, signature-block tables).

3. **Save at** `src/redline/experiments/sprint-10Q/msa-input.docx` on
   the feature branch (or interim fixture-prep branch). Keep the SEC
   source URL and accession number in a small README at that path for
   provenance.

4. ✅ **Update §5 of the research note on main** — this commit lands
   the correction (Meta → OpenAI) and documents the
   no-fictionalisation decision for internal use.

### Customer-side MSA playbook coverage

Sprint 10Q tests against a customer-side MSA playbook. Position
categories the playbook would cover (NOT drafting the playbook itself —
listing categories Arturs would write into PLAYBOOK-MSA.md):

1. **Data residency and sovereignty**
   - jurisdictions where data may rest / be processed
   - sovereign-cloud carve-outs (UAE-PDPL specifics for G42 example)
   - sub-processor jurisdictions and notification rights

2. **Model and weight ownership**
   - foreground IP (models trained / fine-tuned during the engagement)
   - background IP (provider's pre-existing models, customer's
     pre-existing data)
   - derivative-works ownership
   - especially load-bearing for AI-compute contexts

3. **SLA tiers**
   - uptime targets (per service tier)
   - latency commitments
   - capacity reservations and burst behaviour
   - fair-use clauses limiting "unlimited" promises

4. **Audit rights**
   - frequency cap (annual? on-cause?)
   - scope (financial, security, regulatory cooperation)
   - third-party auditor access
   - confidentiality obligations on auditor

5. **Indemnity caps**
   - mutual or asymmetric (customer typically prefers mutual)
   - exclusions (fraud, wilful misconduct, IP infringement)
   - super-cap for IP infringement
   - cap as multiple of fees vs. fixed monetary cap

6. **IP ownership**
   - foreground / background / derivative split
   - licence-back clauses (provider's right to use customer feedback)
   - publicity rights (provider's right to name customer publicly)

7. **Export-control carve-outs**
   - US-UAE-China triangulation specifically relevant to G42 / CloudCo
   - sanctions compliance representations
   - dual-use technology classification disclosures

8. **Termination triggers**
   - material breach (cure period, definition of "material")
   - change of control (provider side — does customer get exit on
     provider acquisition?)
   - insolvency
   - regulatory disqualification

9. **Data return and destruction on exit**
   - format (provider-native vs. open standards)
   - timeframe (e.g., 90 days)
   - certification of destruction
   - customer's right to retain backups for compliance windows

10. **Bias and Responsible AI**
    - customer's visibility into provider's RAI practices
    - audit cooperation on bias / discrimination claims
    - regulatory cooperation on AI-specific regulations
      (EU AI Act, similar)

11. **Regulatory cooperation**
    - GDPR / CCPA / UAE PDPL DPA requirements
    - sector-specific (financial services, healthcare)
    - law-enforcement-request notification (subject to legal
      restrictions on notification)

12. **Pricing and fee escalation**
    - annual escalator caps
    - renewal pricing transparency
    - benchmark / MFN clauses
    - currency and FX handling

13. **Dispute resolution**
    - arbitration vs. court (likely arbitration for
      international compute deals)
    - seat (London / Singapore / Dubai / DIFC)
    - governing law
    - injunctive-relief carve-outs (necessary to enforce
      confidentiality and IP)

13 position categories is a reasonable scope for a first MSA playbook.
At ~50 lines per category in `**Position:** / **Fallback:** /
**Walk-away:** / **Notes:**` shape, the playbook would be ~700 lines
(~5–8k tokens) — well within prompt budget.

### Open questions for Arturs

- **Test artefact source** — Microsoft + OpenAI hybrid (recommended,
  no web access required), or SEC EDGAR sourced (richer test, requires
  web search to identify a filing)?
- **Customer name on test fixture** — keep the G42 / CloudCo
  hyperscaler framing throughout, or fictionalise to (e.g.,)
  "Sovereign AI Holdings Ltd" / "Hyperscale Cloud Co" to avoid any
  G42 IP / publicity concern?
- **Playbook position scope for the first MSA test** — all 13
  categories or a subset (e.g., 5 highest-impact: data residency, IP,
  SLA, indemnity, termination)?
- **Playbook authorship for the test** — does Arturs author the test
  PLAYBOOK-MSA.md himself (cleanest, real lawyer judgement), or does
  Oscar / Claude draft a candidate playbook for Arturs to refine
  (faster, with the standing constraint that the AI does not
  unilaterally produce playbook content for production)?

---

## §6 — Memory roadmap conceptual architecture

**Finding: the longer arc has three components — playbook
(intentional, lawyer-authored), Slack-refinements layer (lawyer-
intended, lower-friction), and accumulated decision memory (emergent,
matter-archive-shaped). The three reconcile on a clear precedence rule:
direction beats playbook (Arturs's rule); playbook beats memory;
memory beats nothing. Sprint 10Q delivers playbook only; documenting
the conceptual architecture for the other two informs design choices
now without committing to implementation.**

### Slack-to-playbook integration

Two architectural shapes considered:

**Option A: Slack writes to an addendum file** that the planner reads
alongside the canonical playbook. E.g., Slack message *"add: when
counter-proposing affiliates, default to including foreign
subsidiaries"* writes a line to `PLAYBOOK-NDA-addendum.md`. The
planner's prompt reads both files, concatenated.

- Pro: low friction; fully automated
- Pro: master playbook is never modified by AI
- Con: addendum drift — over time, addenda accumulate and the master
  playbook becomes incomplete relative to the operational reality
- Con: same Arturs constraint #1 issue as `MemoryMiddleware` —
  effectively the LLM (via the Slack bot) writes to the playbook
  surface

**Option B: Slack queues proposed updates for human approval.** Slack
message → bot drafts a structured playbook-update proposal → posts
back to Slack for human approval → on approval, the master playbook
is edited; on rejection, the proposal is discarded. Same shape as a
GitHub PR review.

- Pro: preserves human authority — the lawyer is in the loop on every
  master-playbook edit (matches Arturs's constraint #1)
- Pro: master playbook stays canonical
- Pro: rejection is a learning signal for the bot (over time, fewer
  bad proposals)
- Con: more friction than option A (two-step: propose → approve)

**Recommend option B.** Arturs's constraint #1 is load-bearing — the
playbook is the lawyer's intentional artefact, not a bot-modified
surface. The Slack bot lowers the friction of updating the playbook
(no need to find the file in the VPS, edit, save) without removing
the lawyer's authority.

Operational shape (sketch — not a Sprint 10Q deliverable):

- Slack bot listens for messages tagged `/playbook-update` (or
  similar) in a per-client Slack channel
- Bot drafts a structured proposal: `{playbook_file: "PLAYBOOK-NDA.md",
  section: "Affiliates", change_type: "amend", before: "...", after: "..."}`
- Proposal posted back to Slack thread for review
- On 👍 from authorised user (whitelist of partner / senior counsel
  Slack IDs), bot edits the playbook file on the client VPS
- Audit trail records every proposal (accepted or rejected)

The Slack bot is a separate service running on the per-client VPS
(same isolation discipline as Oscar). It writes to the same playbook
files Oscar reads.

### Accumulated past-matter context

Per Arturs's three-question framing:

- **Per-matter audit trails accumulate into a knowledge base.** Each
  matter produces parsed-plan.json + parsed-edits.json + (Sprint 10Q+)
  divergence-audit.json. These are persistent per-matter files.
  Aggregating them across matters per client gives a queryable
  decision archive.

- **RAG over past matters as the retrieval mechanism.** Each decision
  in the archive is embedded over (clause-context + decision-action +
  reasoning + counterparty-text). At planner time, for each decision
  being made, the top-K past similar decisions can be retrieved and
  surfaced as part of the planner's user message. *"You have
  previously: accepted Affiliates broadening for Counterparty X
  citing Y; counter-proposed Affiliates narrowing for Counterparty Z
  citing W."*

- **Targeted persistence of "decisions worth banking".** At end of
  matter (post-completion review), the lawyer flags decisions that
  worked particularly well or particularly poorly. These flagged
  decisions feed the Slack-to-playbook queue (option B above) as
  candidate playbook updates — closing the learning loop.

The retrieval shape is per-clause-type, not per-document — embeddings
are over decision-text + reasoning + clause-context. Cross-client
retrieval is forbidden (per-client isolation discipline); each
client's Oscar only sees that client's prior matters.

### Distinction between playbook (intentional) and memory (emergent)

- **Playbook**: what the lawyer wrote down. Authoritative within
  scope. Read at planner-prompt-construction time and pinned in the
  system prompt.

- **Memory**: what Oscar accumulated. Suggestive, not authoritative.
  Used for borderline calls and clauses the playbook is silent on.

Reconciliation rule (proposed for Arturs to confirm):

> **Direction > Playbook > Memory > Default.**
>
> 1. **Direction** (per-round brief from the lawyer) wins on conflict.
>    Arturs's rule.
> 2. **Playbook** (intentional, persistent, lawyer-authored) wins over
>    memory.
> 3. **Memory** (emergent past-decision archive) informs borderline
>    calls and silences in the playbook. Never overrides direction or
>    playbook.
> 4. **Default** (planner's general legal-judgement reasoning,
>    PERSONA-shaped) applies when all three above are silent.

Operationally:
- Playbook → system prompt section (Sprint 10Q)
- Memory → user message section *"RECENT SIMILAR DECISIONS"* with
  N retrieved entries (post-10Q)
- Direction → user message section *"PARTNER'S BRIEF"* (existing)

Conflict-detection patterns the planner needs to handle:
- Direction vs playbook → divergence flag (Sprint 10Q)
- Direction vs memory → no flag (direction always wins; memory is
  suggestive)
- Playbook vs memory → no flag (playbook always wins; memory is
  suggestive)
- Memory vs default → no flag (memory is informative; not a
  decision driver)

### Sprint 10Q's role in the longer arc

Sprint 10Q lands the playbook layer. The infrastructure choices
made in 10Q (file-discovered markdown loaded at planner-prompt-
construction time, divergence flagging via Oscar Counsel comments +
audit JSON) generalise to the memory and Slack layers without
re-architecture:

- **Slack layer** writes to the same playbook files 10Q reads. No
  Oscar-side changes needed beyond authoring the Slack bot.
- **Memory layer** adds a new user-message section without changing
  the system-prompt shape; reuses 10Q's divergence audit-trail
  pattern for memory-conflict logging if any.

**Important architectural test for 10Q**: the playbook layer should be
designed so that adding the memory layer later does NOT require
re-shaping the planner prompt. If 10Q's prompt is tightly coupled to
the four-input shape (playbook + brief + state-of-play + original
doc), a fifth input (memory) breaks it. Recommend: 10Q's prompt
section structure is "context layers" (a top-level grouping that
playbook joins now and memory could join later), not four-named-fields.

### Open questions for Arturs

- **Direction > Playbook > Memory > Default** precedence — confirmed?
  Or different ordering on edge cases?
- **Slack bot path** — option B (queue + approve, recommended) or
  option A (direct addendum)?
- **Memory cross-matter scope** — per-client only (recommended for
  isolation) or per-counterparty across clients (more powerful
  retrieval, breaks isolation)?
- **Memory schema and retrieval mechanism** — embeddings (BGE / OpenAI)
  + vector store (FAISS / pgvector) is the obvious shape; deferred to
  a memory sprint, but does Arturs want a specific direction
  flagged now?
- **End-of-matter "bank decisions" surface** — Slack message? Email?
  Dedicated dashboard? Deferred to memory sprint, but design hook
  needed in 10Q's audit-trail shape if banking surface should read from
  divergence-audit.json directly.

---

## Summary

| § | Question | Recommendation | Open for Arturs |
|---|----------|----------------|-----------------|
| 1 | Does MCP have a playbook concept? | **Yes**, full architecture present (`PLAYBOOK-template.md` + `loader.py:99 _load_playbook` + `NegotiationConfig.playbook`); port the loader pattern (~250 LoC) | File format (`.md` vs `.docx`), discovery mode, empty-playbook behaviour |
| 2 | Should Oscar use Deep Agents `MemoryMiddleware`? | **No** — adopt the pattern (file → system prompt) without the framework; pipeline isn't a Deep Agent and middleware's prompt template encourages LLM self-update which violates constraint #1 | Confirm |
| 3 | How does the planner prompt change for four inputs? | Playbook → system prompt section; first-pass / subsequent-pass mediated by state-of-play emptiness; new behavioural rule 6; new per-decision `divergence_from_playbook` + `divergence_comment_text` fields; mute parsed at run.py | Playbook position in prompt; divergence schema; canonical wording; mute keyword list; first-pass divergence semantics |
| 4 | Divergence flagging mechanism? | Layer 1 (visible) — single combined Oscar Counsel comment with `[Departs from playbook on …]` prefix; Layer 2 (audit) — `divergence-audit.json`, divergences-only, always written; Layer 3 (mute) — keyword parser at run.py threading SessionConfig to dispatcher | Combined vs separate comments; audit granularity; audit location; cross-round mute persistence |
| 5 | Test artefact source? | **Decided 2026-04-26 (Arturs)**: CoreWeave–OpenAI MSA, EX-10.1 to 2025-09-25 8-K. Customer = OpenAI OpCo, LLC (named, signed Sam Altman). All 13 playbook position categories map onto real clauses; §7(a) export-controls relevant to G42 context. No fictionalisation for internal use. Earlier draft mislabelled this exhibit as Meta — corrected. | Cerebras–G42 standalone-exhibit existence (deferred follow-up; not 10Q blocker); playbook scope; playbook authorship |
| 6 | Memory roadmap? | **Direction > Playbook > Memory > Default** precedence; Slack option B (queue + approve); per-client RAG over past-matter audit; "context layers" prompt structure to absorb memory later without re-architecture | Precedence ordering; Slack path; cross-matter scope; retrieval mechanism; end-of-matter banking surface |

Phase 0 closes here. The open questions in each section feed the
Sprint 10Q brief — a separate exercise per Arturs's directive.
