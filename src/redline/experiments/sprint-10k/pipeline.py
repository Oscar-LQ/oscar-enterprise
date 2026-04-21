"""Sprint 10K — Claude-Plugin-MCP first-pass port, tested on MiniMax.

Ports Claude-Plugin-MCP's (CPM) first-pass redlining pattern faithfully
onto Oscar's Adeu substrate. The hypothesis under test: CPM's rich
prompt scaffolding (persona + authority framework + Step D1 surgical
discipline + worked examples + commenting restraint) produces
lawyer-shape output on MiniMax where simpler surgical-span prompts in
10F / 10G / 10I failed.

Architecture (single LLM call, per CPM's first-pass):

    SystemMessage: PERSONA + AUTHORITY + Step 6 + Step A-F + substrate
                   note + task instruction + data-contract schema
    HumanMessage:  full NDA clean text

    chat_model.invoke(...) → JSON {"edits": [{target, new, comment}]}
        → parse (fence-strip allowed)
        → map to adeu.ModifyText list
        → RedlineEngine.process_batch
        → save nda-output.docx
        → verify_output

Single attempt. No retries. No prompt iteration. Mechanical fixes
(imports, env vars, JSON fence-strip) allowed per plan approval.

See `/sandbox/.claude/plans/bright-noodling-liskov.md` for the full
plan, and `docs/research/sprint-10k-claude-plugin-mcp-port.md` for the
Phase 1 research note (written on main regardless of outcome).
"""
from __future__ import annotations

import io
import json
import logging
import os
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Structlog-silencing preamble — must run before any adeu import.
# Copied verbatim from Sprint 10E pattern (Sprint 10C's harness.py
# proved this out; Sprint 10J inherited it).
import structlog  # noqa: E402

logging.basicConfig(level=logging.WARNING)
for _name in (
    "adeu",
    "adeu.redline.engine",
    "adeu.redline.mapper",
    "adeu.redline.comments",
    "adeu.ingest",
    "adeu.markup",
    "adeu.utils.docx",
):
    logging.getLogger(_name).setLevel(logging.WARNING)
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(colors=False),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from lxml import etree  # noqa: E402

from adeu import ModifyText, RedlineEngine, extract_text_from_stream  # noqa: E402
from adeu.redline.engine import BatchValidationError  # noqa: E402

from shared.llm.chat_model import get_chat_model  # noqa: E402


# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
INPUT_DOCX = HERE / "nda-input.docx"
OUTPUT_DOCX = HERE / "nda-output.docx"
LLM_INPUT_TXT = HERE / "llm-input.txt"
LLM_OUTPUT_TXT = HERE / "llm-output.txt"
PARSED_EDITS_JSON = HERE / "parsed-edits.json"
ADEU_CALLS_JSONL = HERE / "adeu-calls.jsonl"
TRANSCRIPT = HERE / "transcript.txt"

AUTHOR = "Oscar"
ENV_PREFIX = "OSCAR_LLM_REDLINE_EXECUTOR"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": W_NS}


# ---------------------------------------------------------------------------
# CPM prompt blocks — verbatim extracts (source: /sandbox/reference-material/
# claude-plugin-mcp/{defaults,skills/negotiate-contract/SKILL.md})
# ---------------------------------------------------------------------------

# Source: defaults/PERSONA.md (lines 1–29, verbatim)
PROMPT_PERSONA = """# Persona: Commercial Solicitor

You are a commercial solicitor advising on transactional matters. Your practice
focuses on supply agreements, service contracts, licensing arrangements, and
general commercial terms.

## Negotiation Style

You are collaborative but firm. You seek commercially reasonable outcomes that
protect your client's interests without being unnecessarily adversarial. You
prefer to explain your reasoning when pushing back on a counterparty's position.

## Judgment Baseline

When evaluating a counterparty's proposed change:
- Consider whether it shifts risk or commercial balance materially
- Distinguish between genuine improvements and one-sided amendments
- Accept changes that are neutral or beneficial to your client
- Push back on changes that erode your client's position without justification
- Always preserve your client's ability to enforce key protections
- Invest negotiation effort proportionally to commercial impact -- do not spend the same energy on a notice period as on a liability cap
- Do not counter-propose a change just because you would have worded it differently -- accept when the substance is acceptable

## Communication

- Use clear, professional language in all comments
- Explain the commercial rationale behind counter-proposals
- Acknowledge reasonable counterparty positions before disagreeing
- Keep comments concise -- solicitors value brevity
"""

# Source: defaults/AUTHORITY.md (lines 1–53, verbatim)
PROMPT_AUTHORITY = """# Authority Framework

This defines what you can do autonomously, what needs flagging, and what
requires immediate escalation.

## Green Zone (Act Autonomously)

You may accept or make these changes without flagging:
- Typographical corrections and grammar fixes
- Minor formatting adjustments (spacing, numbering style)
- Standard boilerplate that matches market practice
- Defined term consistency corrections
- Cross-reference updates

## Amber Zone (Flag and Recommend)

Flag these to the user with your recommendation before acting:
- Payment terms and payment timing
- Liability caps and limitations
- Indemnity scope and carve-outs
- Warranty periods and warranty scope
- Termination provisions and notice periods
- Insurance requirements
- Intellectual property ownership or licensing terms
- Confidentiality scope and duration
- Force majeure provisions
- Assignment and subcontracting rights
- Any financial threshold or monetary amount
- Any change that shifts commercial risk between parties

## Red Zone (Escalate Immediately)

Never act on these -- escalate to the user immediately:
- Governing law or choice of law changes
- Jurisdiction or dispute resolution mechanism changes
- Regulatory compliance obligations
- Sanctions or export control provisions
- Data protection and privacy terms beyond standard
- Any clause you do not fully understand
- Any change that could expose the client to unlimited liability

## Catch-All for Unlisted Clause Types

For clause types not listed above: assess based on impact, not label.
- If the change shifts risk or financial exposure -> treat as amber
- If the change is neutral or administrative -> treat as green
The clause category does not determine the zone -- the commercial impact does.

## General Principle

When in doubt, treat it as amber. It is always better to flag something
unnecessarily than to miss something material. Your authority widens as
the user builds trust in your judgment.
"""

# Source: SKILL.md lines 330–420, verbatim
PROMPT_STEP_6 = """### Step 6: Commenting Rules -- Read This Carefully

Most tracked changes have NO comment. The markup speaks for itself.

**DO NOT comment when:**
- The change is self-explanatory from the markup (most are -- "30 days" to "45
  days" needs no explanation)
- The change is a standard buyer/seller position any commercial lawyer would
  recognise
- The change is mechanical (cross-references, defined terms, formatting)
- You are making a first-pass redline with no counterparty comments to reply to

**ONLY comment when:**
- Your position is reserved and you need instructions from your client before
  finalising
- Something is unclear in the original drafting and you need the counterparty to
  clarify
- The change is unusual or non-standard and the reasoning isn't obvious from the
  markup
- You are flagging a material risk that the recipient might not spot from the
  tracked change alone
- You are replying to an existing comment from the counterparty
- You need to create a NEW standalone comment (not a reply). Apply a tighter bar:
  the counterparty genuinely cannot infer the reasoning from the tracked change
  alone AND the point is material enough to warrant written explanation. If only
  one of these conditions is met, do not comment.

If you are unsure whether a comment is needed, do not add one.

**RIGHT/WRONG commenting examples:**

WRONG -- restating the tracked change in prose:
  The tracked change shows "30 days" deleted and "45 days" inserted.
  Comment: "We have amended the payment period from 30 days to 45 days to align
    with our standard terms."
  Why wrong: The markup already shows exactly this. The comment adds nothing.

WRONG -- narrating what is visible in the markup:
  The tracked change shows a liability cap inserted.
  Comment: "We have added a liability cap of GBP 500,000."
  Why wrong: The counterparty can read. Telling them what the markup says
    signals inexperience.

RIGHT -- explaining commercial rationale not visible in markup:
  The tracked change shows a liability cap inserted.
  Comment: "This exposes the client to uncapped liability on a fixed-fee
    contract -- the cap reflects the total contract value."
  Why right: The reasoning behind the cap is not visible in the markup itself.

RIGHT -- flagging a material risk the counterparty might not spot:
  The tracked change shows an indemnity clause amended.
  Comment: "The original wording created a reverse indemnity against your own
    negligence -- we've narrowed to direct losses only."
  Why right: The tracked change shows the text change but not the legal
    consequence.

**Two-bar comment volume system** (15-clause contract as baseline):
- First-pass redlines: 0-3 comments
- Counterparty responses: 3-5 comments
- Over-commenting signals inexperience to the counterparty; a solicitor's
  restraint is itself a professional signal.

**Comment reasoning by type:**
When you do comment, match the reasoning to the clause category:
- Financial clauses (payment, liability, indemnity): explain the commercial
  rationale -- what this costs, what exposure it creates
- Structural/procedural clauses (termination mechanics, notice, assignment):
  reference market practice -- "This is unusual for contracts of this type"
- Genuine legal issues (regulatory, enforceability, jurisdiction): use legal
  reasoning -- but only when it genuinely is a legal issue, not a commercial one

When helpful, suggest a path forward: "We would accept this if [condition]."
This is especially valuable in later rounds to signal flexibility and accelerate
agreement.

A first-pass redline of a 15-clause contract should typically have 0-3
comments, not 11. Over-commenting is unprofessional and signals inexperience.

**Accepted changes:** Always add a brief comment -- "Accepted" or similar. No
silent accepts. The counterparty needs to see you reviewed it deliberately.

Never use formulaic headers like "BUYER'S POSITION:", "RATIONALE:", or any
structured template. Comments read like a solicitor wrote them -- concise,
professional, no formatting.

**Counterparty response vs first-pass:** The commenting rules above apply to
both workflows, but the expected volume differs. In counterparty response,
you have a counterparty's positions to respond to -- commenting on countered
clauses where the reasoning isn't obvious from the markup is appropriate and
expected. In first-pass redlining, you have no counterparty -- the 0-3 comment
guideline applies strictly.
"""

# Source: SKILL.md lines 606–713, verbatim (Steps A–F; Step G styler and
# Step H report excluded as scope-excluded per plan).
PROMPT_FIRST_PASS_WORKFLOW = """### First-Pass Redlining Workflow

Use this workflow when the document is clean (no existing tracked changes). The
user wants you to review the contract and create initial redlines.

### Step A: Read the User's Instructions

The user provides negotiation instructions -- these may be brief ("push back on
payment terms, liability, and warranties") or detailed (a full playbook with
clause-by-clause positions). Combine the user's instructions with:
- The **persona** (who you are as a lawyer)
- The **authority framework** (what you can do autonomously vs. must flag)
- The **playbook** (clause-by-clause positions, if provided)

### Step B: Analyse the Contract

Read the full contract clause by clause using the clean text from ingestion. For
each clause, consider: does it need changes based on the user's instructions,
persona, and authority framework? Most clauses will be fine as-is -- do not
change things for the sake of change.

### Step C: Authority Check

Before building your edit list, classify each proposed change against the
authority framework:

- **Green zone** -- act autonomously, no need to flag
- **Amber zone** -- flag to the user with your recommendation and reasoning,
  ask for confirmation before including in the edit list
- **Red zone** -- escalate immediately, do not include

If any proposed changes fall in amber or red, present them to the user and wait
for guidance before proceeding.

### Step D: Build the Edit List

For each clause needing changes, create an edit dict with:
- `target_text`: the exact text from the document to find and replace
- `new_text`: the replacement text (or `""` for a pure deletion)
- `comment`: `None` for most edits. Only add a comment in the rare cases
  described in Step 6 -- see the commenting rules

### Step D1: Edit Precision Rules

When building your edit list, follow these rules to produce precise,
word-level redlines:

**Target the minimum changed span.** If you need to change one word in a
sentence, set target_text to a phrase containing just that word plus enough
surrounding context for unique matching (usually 5-15 words). Do not set
target_text to the entire paragraph or sentence.

**Do not rewrite what you are not changing.** If you need to add a proviso
to the end of a clause, include the last few words as target_text and append
your addition in new_text. Do not delete and rewrite the whole clause.

**Do not include formatting markers.** Never include ** or _ in new_text.
Formatting is preserved automatically from the original document.

**Keep target_text as short as uniquely matchable.** The engine needs to find
your target_text in the document. Include enough context to avoid ambiguity,
but no more. A phrase of 5-15 words is usually right.

WRONG -- rewriting a whole sentence to change one word:
  target_text: "The Receiving Party shall keep all Confidential Information
    strictly confidential and shall not disclose it to any third party"
  new_text: "The Receiving Party agrees to maintain the confidentiality of
    all Confidential Information and shall not disclose such information to
    any third party without prior written consent"

RIGHT -- targeting just the phrase that needs the addition:
  target_text: "shall not disclose it to any third party"
  new_text: "shall not disclose it to any third party without the prior
    written consent of the Disclosing Party"

WRONG -- replacing a defined term by rewriting the whole definition:
  target_text: "Confidential Information means any information disclosed by
    either party to the other party"
  new_text: "Confidential Information means any information disclosed by the
    Disclosing Party to the Receiving Party"

RIGHT -- targeting just the phrase that differs:
  target_text: "disclosed by either party to the other party"
  new_text: "disclosed by the Disclosing Party to the Receiving Party"

### Step E: Commenting Rules

The same commenting rules from Step 6 apply here. Most edits have `comment:
None` -- that is normal and expected.

For first-pass redlines: almost every edit should have `comment: None`. You have
no counterparty comments to reply to, and the markup speaks for itself. A
15-clause contract should typically produce 0-3 comments total. If you find
yourself commenting on more than that, you are over-commenting. When you do add
one of these rare comments, match the reasoning type to the clause category --
commercial rationale for financial clauses, market practice for structural
clauses.

### Step F: Call `redline_document`

Call the `redline_document` MCP tool with:
- `input_path`: the original clean .docx
- `output_path`: where to save the redlined result
- `edits`: the list of edit dicts from Step D
- `author_name`: the client's name for Track Changes attribution

The tool returns a JSON result with the number of edits applied, any skipped
edits, and any validation warnings.
"""

# Substrate-forced adaptation — the one block that departs from CPM verbatim.
# Replaces CPM's Step F reference to `redline_document` MCP tool with a
# statement that the caller applies the edit list via Adeu.
PROMPT_SUBSTRATE_NOTE = """## Substrate note for this environment

In this environment you do not have access to the `redline_document` MCP tool.
Instead, return your edit list as a single JSON object (schema below).
The caller will apply each edit via Adeu's `RedlineEngine`, which generates
native OOXML tracked changes with the same `w:ins`/`w:del` structure that
`redline_document` produces. The semantics of `target_text` / `new_text` /
`comment` are identical to the shape described in Step D and Step D1 above.
"""

# User's "negotiation instructions" per Step A.
PROMPT_TASK_INSTRUCTION = """## User instructions

Change Clause 9 ("Governing Law and Dispute Resolution") from court litigation
to binding LCIA arbitration. The final arbitration provision must name all
five of: (1) seat London, (2) LCIA Rules, (3) a sole arbitrator, (4) English
language, (5) final and binding on the parties. Keep the governing-law sentence
(the first sentence of Clause 9, ending "...laws of England and Wales.") intact.
Change only the dispute-resolution sentence.

## Red-Zone authorisation

This is a dispute-resolution mechanism change, which falls in the Authority
Framework's Red Zone. The user (the client's general counsel) has pre-authorised
this specific change. Do not escalate; proceed with the surgical edits per
Step D and Step D1.
"""

PROMPT_DATA_CONTRACT = """## Output format

Return a single JSON object, nothing else. No markdown fences. No prose before
or after. Schema:

```
{
  "edits": [
    {
      "target_text": "<exact text from the document to find>",
      "new_text": "<replacement text>",
      "comment": "<optional rationale, or null>"
    }
  ]
}
```

Each edit dict follows Step D / Step D1. For first-pass work on a single
clause, 0–3 comments total is the expected volume; most edits should have
`"comment": null`.
"""


def build_system_prompt() -> str:
    """Assemble the CPM-port system prompt.

    Order: persona → authority → step 6 (referenced by step E) → first-pass
    workflow (steps A–F) → substrate note → task instruction → data contract.
    """
    return "\n\n---\n\n".join(
        [
            PROMPT_PERSONA.rstrip(),
            PROMPT_AUTHORITY.rstrip(),
            PROMPT_STEP_6.rstrip(),
            PROMPT_FIRST_PASS_WORKFLOW.rstrip(),
            PROMPT_SUBSTRATE_NOTE.rstrip(),
            PROMPT_TASK_INSTRUCTION.rstrip(),
            PROMPT_DATA_CONTRACT.rstrip(),
        ]
    ) + "\n"


# ---------------------------------------------------------------------------
# NDA clean-text rendering
# ---------------------------------------------------------------------------


def build_human_message() -> str:
    """Render the full NDA as plain text for the HumanMessage.

    Mirrors CPM's Step B ("Read the full contract clause by clause using the
    clean text from ingestion"). The LLM needs the whole document in context
    so its Authority-Check classification runs on real clause adjacency, not
    on §9 in isolation.
    """
    from build_input import CLAUSES, PREAMBLE, SIGNATURES, TITLE

    parts: list[str] = [TITLE, "", PREAMBLE, ""]
    for heading, body in CLAUSES:
        parts.append(heading)
        parts.append("")
        parts.append(body)
        parts.append("")
    for line in SIGNATURES:
        parts.append(line)
    return "\n".join(parts).rstrip() + "\n"


# ---------------------------------------------------------------------------
# JSON parsing — fence-strip (mechanical robustness; one deterministic cleanup)
# ---------------------------------------------------------------------------


def parse_edits(raw: str) -> list[dict[str, Any]]:
    """Parse MiniMax's reply into an edit list.

    Accepts plain JSON or JSON wrapped in a single ```json fence. One
    deterministic fence-strip only (per plan — not iteration).

    Returns the list of edit dicts. Raises ``ValueError`` on malformed
    output.
    """
    text = raw.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[: -3].rstrip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed JSON: {exc}") from exc
    if not isinstance(data, dict) or "edits" not in data:
        raise ValueError(
            f"expected top-level object with 'edits' key, got: {type(data).__name__}"
        )
    edits = data["edits"]
    if not isinstance(edits, list):
        raise ValueError(f"'edits' must be a list, got: {type(edits).__name__}")
    for i, e in enumerate(edits):
        if not isinstance(e, dict):
            raise ValueError(f"edit[{i}] must be a dict, got: {type(e).__name__}")
        if "target_text" not in e or "new_text" not in e:
            raise ValueError(f"edit[{i}] missing target_text or new_text")
    return edits


# ---------------------------------------------------------------------------
# Map to Adeu ModifyText
# ---------------------------------------------------------------------------


def map_to_adeu(edit_dicts: list[dict[str, Any]]) -> list[ModifyText]:
    """Construct Adeu `ModifyText` instances from parsed edit dicts.

    Version-forced translation: CPM (Adeu 0.7.x target) used `DocumentEdit`;
    Adeu 1.1.0 renamed the class to `ModifyText` in v0.9.0's unified
    `DocumentChange` API. Field names (`target_text`, `new_text`, `comment`)
    are identical.
    """
    result: list[ModifyText] = []
    for e in edit_dicts:
        kwargs: dict[str, Any] = {
            "target_text": e["target_text"],
            "new_text": e["new_text"] if e["new_text"] is not None else "",
        }
        comment = e.get("comment")
        if comment:
            kwargs["comment"] = comment
        result.append(ModifyText(**kwargs))
    return result


# ---------------------------------------------------------------------------
# Apply edits via Adeu
# ---------------------------------------------------------------------------


@dataclass
class ApplyResult:
    applied: int
    skipped: int
    validation_errors: list[str] = field(default_factory=list)
    raised: Exception | None = None


def apply_edits(
    edits: list[ModifyText],
    input_path: Path,
    output_path: Path,
) -> ApplyResult:
    """Apply the edits to input_path and write to output_path.

    Uses `RedlineEngine.process_batch` directly — no `@tool` wrappers, no
    surgical orchestration layer, no retries. Single-shot application,
    matching CPM's shape without the compensation fallbacks (intentionally
    scope-excluded per plan).

    On `BatchValidationError`, returns an `ApplyResult` with the errors
    captured (no raise). The caller reports Outcome C with diagnosis.
    """
    with open(input_path, "rb") as f:
        stream = io.BytesIO(f.read())
    engine = RedlineEngine(stream, author=AUTHOR)
    try:
        result = engine.process_batch(edits)
    except BatchValidationError as exc:
        errs = getattr(exc, "errors", [str(exc)])
        return ApplyResult(applied=0, skipped=0, validation_errors=list(errs), raised=exc)
    except Exception as exc:  # other adeu failures — report, do not retry
        return ApplyResult(applied=0, skipped=0, validation_errors=[str(exc)], raised=exc)
    output_stream = engine.save_to_stream()
    with open(output_path, "wb") as f:
        f.write(output_stream.read())
    return ApplyResult(
        applied=int(result.get("edits_applied", 0)),
        skipped=int(result.get("edits_skipped", 0)),
    )


# ---------------------------------------------------------------------------
# verify_output — copy from Sprint 10E (same four lawyer-shape warnings)
# ---------------------------------------------------------------------------


def _element_text(el) -> str:
    """Concatenate all w:t + w:delText descendant text of a w:ins or w:del."""
    texts = el.xpath(".//w:t/text() | .//w:delText/text()", namespaces=_NS)
    return "".join(texts)


def _element_word_count(el) -> int:
    text = _element_text(el).strip()
    return len(text.split()) if text else 0


def verify_output(output_path: Path) -> tuple[bool, list[str]]:
    """Three mechanical checks + four Sprint 10E lawyer-shape warnings.

    Copied verbatim from Sprint 10E's `run.py:590–717` so the seven-sprint
    comparison uses the same diagnostic. `ok` reflects mechanical checks
    only; WARN items are diagnostic and do not flip `ok` to False.
    """
    notes: list[str] = []

    if not output_path.exists():
        return False, [f"output file does not exist: {output_path}"]
    notes.append(f"exists: {output_path} ({output_path.stat().st_size} bytes)")

    try:
        with zipfile.ZipFile(output_path) as zf:
            names = zf.namelist()
            if "word/document.xml" not in names:
                return False, notes + ["word/document.xml not in zip"]
            doc_xml = zf.read("word/document.xml")
    except zipfile.BadZipFile:
        return False, notes + ["not a valid zip file"]
    notes.append(f"valid zip with {len(names)} parts")

    try:
        root = etree.fromstring(doc_xml)
    except etree.XMLSyntaxError as exc:
        return False, notes + [f"XML parse failed: {exc}"]
    notes.append(f"parsed OK (root tag: {etree.QName(root.tag).localname})")

    ins_elements = root.findall(".//w:ins", _NS)
    del_elements = root.findall(".//w:del", _NS)
    notes.append(
        f"tracked changes: w:ins={len(ins_elements)}, w:del={len(del_elements)}"
    )

    # (1) Span widths.
    for el in ins_elements + del_elements:
        tag = etree.QName(el.tag).localname
        wid = el.get(f"{{{W_NS}}}id", "?")
        wc = _element_word_count(el)
        if wc > 50:
            notes.append(
                f"WARN: w:{tag}[id={wid}] span={wc} words — >50, "
                f"almost certainly over-broad (lawyer-shape fail)"
            )
        elif wc > 20:
            notes.append(
                f"WARN: w:{tag}[id={wid}] span={wc} words — >20, "
                f"suspicious (review against criteria)"
            )

    # (2) Empty-delText nested-delete signature.
    for d in del_elements:
        empty_dts = [
            dt
            for dt in d.findall(".//w:delText", _NS)
            if (dt.text is None or dt.text == "")
        ]
        has_ancestor_del = False
        parent = d.getparent()
        while parent is not None:
            if etree.QName(parent.tag).localname == "del":
                has_ancestor_del = True
                break
            parent = parent.getparent()
        if empty_dts and has_ancestor_del:
            wid = d.get(f"{{{W_NS}}}id", "?")
            notes.append(
                f"WARN: w:del[id={wid}] is a nested w:del with empty "
                f"w:delText — original text not preserved in audit trail "
                f"(matches Sprint 10D nested-delete failure)"
            )

    # (3) Duplicate w:ins content (>10 words, ≥2 copies).
    counter: Counter[str] = Counter()
    for i_el in ins_elements:
        content = _element_text(i_el).strip()
        if len(content.split()) > 10:
            counter[content] += 1
    for content, count in counter.items():
        if count >= 2:
            wc = len(content.split())
            notes.append(
                f"WARN: {count} w:ins elements share identical {wc}-word "
                f"content — duplicate insertion (matches Sprint 10D "
                f"duplicate-ins failure). Content starts: "
                f"{content[:80]!r}"
            )

    # (4) Litigation-text preservation spot-check.
    all_del_text = "".join(root.xpath(".//w:delText/text()", namespaces=_NS))
    needle = "exclusive jurisdiction of the courts of England and Wales"
    if needle in all_del_text:
        notes.append(
            f"SPOT-CHECK OK: litigation phrase {needle!r} is preserved "
            f"in w:delText (original text is in the audit trail)."
        )
    else:
        notes.append(
            f"WARN: litigation phrase {needle!r} NOT found in any "
            f"w:delText — the original text may not be preserved in the "
            f"audit trail (matches Sprint 10D broken-audit-trail failure)."
        )

    return True, notes


# ---------------------------------------------------------------------------
# Artefact writers
# ---------------------------------------------------------------------------


def _write_text(path: Path, body: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)


def _write_json(path: Path, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _write_jsonl(path: Path, items: list[Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def _echo_env() -> None:
    for suffix in ("PROVIDER", "MODEL", "API_KEY"):
        name = f"{ENV_PREFIX}_{suffix}"
        val = os.environ.get(name)
        if suffix == "API_KEY" and val:
            shown = f"<set, {len(val)} chars>"
        else:
            shown = repr(val)
        print(f"{name:45s} = {shown}")


@dataclass
class RunArtefacts:
    system_prompt: str
    human_message: str
    raw_response: str
    parsed_edits: list[dict[str, Any]]
    adeu_edits: list[ModifyText]
    apply_result: ApplyResult
    verify_ok: bool
    verify_notes: list[str]
    clean_view_excerpt: str


def run_pipeline() -> RunArtefacts:
    """Execute the single-attempt pipeline and return all artefacts.

    Raises `ValueError` only on malformed JSON (Outcome C).
    `BatchValidationError` is captured into `apply_result.validation_errors`
    (Outcome C with diagnosis).
    """
    # 1. Build prompts.
    system_prompt = build_system_prompt()
    human_message = build_human_message()

    # 2. Persist the prompts (reproducibility).
    _write_text(
        LLM_INPUT_TXT,
        "=" * 72 + "\nSYSTEM MESSAGE\n" + "=" * 72 + "\n"
        + system_prompt
        + "\n" + "=" * 72 + "\nHUMAN MESSAGE\n" + "=" * 72 + "\n"
        + human_message,
    )

    # 3. Invoke MiniMax.
    chat_model = get_chat_model(env_prefix=ENV_PREFIX)
    response = chat_model.invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=human_message)]
    )
    raw = response.content if isinstance(response.content, str) else str(response.content)
    _write_text(LLM_OUTPUT_TXT, raw)

    # 4. Parse. Single fence-strip cleanup allowed per plan.
    parsed = parse_edits(raw)
    _write_json(PARSED_EDITS_JSON, parsed)

    # 5. Map to Adeu.
    adeu_edits = map_to_adeu(parsed)

    # 6. Log Adeu calls verbatim (pre-apply).
    _write_jsonl(
        ADEU_CALLS_JSONL,
        [
            {
                "target_text": e.target_text,
                "new_text": e.new_text,
                "comment": e.comment,
            }
            for e in adeu_edits
        ],
    )

    # 7. Ensure input exists (regenerate if missing).
    if not INPUT_DOCX.exists():
        from build_input import build_document

        build_document()

    # 8. Apply.
    apply_result = apply_edits(adeu_edits, INPUT_DOCX, OUTPUT_DOCX)

    # 9. Verify. If apply failed mid-pipeline, output may not exist.
    if OUTPUT_DOCX.exists():
        verify_ok, verify_notes = verify_output(OUTPUT_DOCX)
    else:
        verify_ok, verify_notes = False, [
            f"output did not apply: validation errors captured in apply_result"
        ]

    # 10. Clean-view §9 excerpt (Accept-All simulated).
    clean_view_excerpt = ""
    if OUTPUT_DOCX.exists():
        try:
            with open(OUTPUT_DOCX, "rb") as f:
                clean_view = extract_text_from_stream(
                    io.BytesIO(f.read()), clean_view=True
                )
            idx = clean_view.find("9. Governing Law")
            if idx >= 0:
                clean_view_excerpt = clean_view[idx : idx + 1200]
            else:
                idx = clean_view.find("England and Wales")
                if idx >= 0:
                    clean_view_excerpt = clean_view[max(0, idx - 200) : idx + 1000]
                else:
                    clean_view_excerpt = clean_view[:1500]
        except Exception as exc:
            clean_view_excerpt = f"<clean-view extraction failed: {exc}>"

    return RunArtefacts(
        system_prompt=system_prompt,
        human_message=human_message,
        raw_response=raw,
        parsed_edits=parsed,
        adeu_edits=adeu_edits,
        apply_result=apply_result,
        verify_ok=verify_ok,
        verify_notes=verify_notes,
        clean_view_excerpt=clean_view_excerpt,
    )


def write_transcript(artefacts: RunArtefacts) -> None:
    """Write human-legible transcript summarising the run."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"Sprint 10K — transcript — {datetime.now(timezone.utc).isoformat()}")
    lines.append("=" * 72)
    lines.append("")
    lines.append("ENV:")
    for suffix in ("PROVIDER", "MODEL"):
        name = f"{ENV_PREFIX}_{suffix}"
        lines.append(f"  {name} = {os.environ.get(name)!r}")
    lines.append("")
    lines.append("ARTEFACTS:")
    lines.append(f"  llm-input.txt      ({LLM_INPUT_TXT.stat().st_size} bytes)")
    lines.append(f"  llm-output.txt     ({LLM_OUTPUT_TXT.stat().st_size} bytes)")
    lines.append(f"  parsed-edits.json  ({PARSED_EDITS_JSON.stat().st_size} bytes)")
    lines.append(f"  adeu-calls.jsonl   ({ADEU_CALLS_JSONL.stat().st_size} bytes)")
    if OUTPUT_DOCX.exists():
        lines.append(f"  nda-output.docx    ({OUTPUT_DOCX.stat().st_size} bytes)")
    else:
        lines.append(f"  nda-output.docx    (NOT WRITTEN — apply failed)")
    lines.append("")
    lines.append(f"PARSED EDITS: {len(artefacts.parsed_edits)}")
    for i, e in enumerate(artefacts.parsed_edits, 1):
        lines.append(f"  EDIT {i}:")
        for k, v in e.items():
            lines.append(f"    {k}={v!r}")
    lines.append("")
    lines.append("--- ADEU CALLS (VERBATIM) ---")
    for i, e in enumerate(artefacts.adeu_edits, 1):
        lines.append(f"  CALL {i}: ModifyText(")
        lines.append(f"    target_text={e.target_text!r},")
        lines.append(f"    new_text={e.new_text!r},")
        if e.comment:
            lines.append(f"    comment={e.comment!r},")
        lines.append("  )")
    lines.append("")
    lines.append("--- APPLY RESULT ---")
    lines.append(f"  edits_applied: {artefacts.apply_result.applied}")
    lines.append(f"  edits_skipped: {artefacts.apply_result.skipped}")
    if artefacts.apply_result.validation_errors:
        lines.append("  validation_errors:")
        for err in artefacts.apply_result.validation_errors:
            lines.append(f"    - {err}")
    lines.append("")
    lines.append("--- MECHANICAL VERIFICATION ---")
    for n in artefacts.verify_notes:
        lines.append(f"  {n}")
    lines.append("")
    lines.append("--- CLEAN-VIEW §9 READ-BACK (simulated Accept-All) ---")
    for line in artefacts.clean_view_excerpt.splitlines():
        lines.append(f"  {line}")
    lines.append("")
    _write_text(TRANSCRIPT, "\n".join(lines) + "\n")
