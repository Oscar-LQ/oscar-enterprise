"""Sprint 10D — General Counsel → Head of Commercial → redline-specialist.

First end-to-end agent-driven redline in Oscar. Pipes a single transformation
("convert litigation to arbitration in the dispute resolution clause") through
the three-level org chart. The specialist applies Adeu operations to a
synthetic NDA and saves a .docx with native track changes for human review.

Structure:
    GC (GPT-5.4 via OpenRouter — orchestrator)
      → head-of-commercial (MiniMax-M2.7 — department head, routes)
        → redline-specialist (MiniMax-M2.7 — applies Adeu edits)
        → accept-reject-reasoner (existing Sprint 9 specialist; not exercised
          this sprint but still routable)

Scope — this sprint only:
    * One synthetic NDA input (see ``build_input.py``).
    * One transformation: litigation → arbitration on the dispute resolution
      clause in Clause 9.
    * One end-to-end invocation. No matrix, no iteration loops beyond a single
      retry if the first invocation produces no output.
    * Mechanical verification only (script runs, output .docx exists, valid
      zip, parseable ``word/document.xml``). Lawyer-shape quality is Arturs's
      job in Word after the sprint, not a Sprint 10D deliverable.

The specialist's tool surface is deliberately thin: ``modify_text`` and
``insert_text`` exposing Adeu's native operations (per Sprint 10C's
"expose Adeu's API, don't wrap it" stance and ADR 018's facilitator
boundary). ``add_comment`` as a STANDALONE primitive is not implemented —
see the sprint log entry for the full rationale; briefly, Adeu 1.1.0's
public SDK does not expose pure-comment-on-untouched-text, and
manufacturing one via a dummy edit would be a wrapper (ADR 018). Comment
capability is preserved by making ``comment`` a parameter on both
``modify_text`` and ``insert_text``.

Binary .docx bytes never touch the graph state (ADR 017). Paths flow via
closure-bound constants in the tool factory; the specialist reasons about
edits, not file locations.
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import sys
import zipfile
from pathlib import Path

# Silence Adeu's structlog INFO/DEBUG stream before any adeu import; matches
# the pattern Sprint 10C's harness.py proved out.
import structlog

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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from typing import Literal

from deepagents import create_deep_agent

from adeu import ModifyText, RedlineEngine
from adeu.redline.engine import BatchValidationError

from llm.chat_model import get_chat_model


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
INPUT_DOCX = HERE / "nda-input.docx"
OUTPUT_DOCX = HERE / "nda-output.docx"

AUTHOR = "Oscar"


# ---------------------------------------------------------------------------
# Tool factory — closure over input/output paths (ADR 017)
# ---------------------------------------------------------------------------


def _reset_output(input_path: Path, output_path: Path) -> None:
    """Copy input to output so subsequent edits accumulate on output."""
    shutil.copyfile(input_path, output_path)


def _apply_one_edit(output_path: Path, edit: ModifyText) -> str:
    """Read output, apply one edit, write back, return a summary string.

    Returns a summary like ``"applied: edits_applied=1 edits_skipped=0"``.
    On ``BatchValidationError`` returns a string starting with ``ERROR:``
    and the formatted error list so the agent can retry with better
    target_text.
    """
    with open(output_path, "rb") as f:
        current = f.read()
    engine = RedlineEngine(io.BytesIO(current), author=AUTHOR)
    try:
        result = engine.process_batch([edit])
    except BatchValidationError as exc:
        errors = getattr(exc, "errors", [str(exc)])
        detail = "\n".join(errors) if errors else str(exc)
        return (
            "ERROR: Adeu rejected the edit during validation. The target_text "
            "did not match exactly one span in the document. Fix the target "
            "and retry.\n" + detail
        )
    new_bytes = engine.save_to_stream().getvalue()
    with open(output_path, "wb") as f:
        f.write(new_bytes)
    summary = (
        f"applied: edits_applied={result.get('edits_applied', 0)} "
        f"edits_skipped={result.get('edits_skipped', 0)}"
    )
    if result.get("edits_skipped", 0) and not result.get("edits_applied", 0):
        summary += (
            " — WARNING: 0 edits applied. The engine skipped this edit; "
            "most common cause is empty target_text or overlap with a prior edit."
        )
    return summary


def make_redline_tools(input_path: Path, output_path: Path) -> list[BaseTool]:
    """Build the specialist's Adeu-wrapped tools bound to the given paths.

    Contract: when this factory runs, it copies ``input_path`` to
    ``output_path`` once. Every subsequent tool call reads and writes
    ``output_path`` — edits accumulate. Callers invoking the agent more
    than once against the same output path should rebuild this factory
    first (which reseeds ``output_path`` from ``input_path``).
    """
    _reset_output(input_path, output_path)

    @tool
    def modify_text(target_text: str, new_text: str, comment: str = "") -> str:
        """Replace ``target_text`` in the NDA with ``new_text`` via tracked change.

        Thin wrapper over ``adeu.ModifyText``. The ``target_text`` MUST match
        exactly ONE span in the document — if zero or more than one match,
        the edit is rejected with an ERROR you can read and retry. Target
        text is word-boundary-aware: submitting a full sentence where only
        one phrase differs is fine — Adeu's engine narrows the redline to
        the differing words automatically.

        The original text is preserved inside ``<w:delText>`` (Word shows it
        struck through); the replacement is inserted with ``<w:ins>`` (shown
        underlined). Both carry ``w:author="Oscar"``.

        To delete text without replacement, pass ``new_text=""`` — this
        produces a tracked deletion. Do NOT pass ``comment`` on deletions:
        Adeu silently drops comments on pure deletions (this is a known
        quirk). If you want to comment on a deletion, attach the comment to
        a retained anchor nearby via a separate modify_text call.
        """
        kwargs: dict[str, object] = {
            "target_text": target_text,
            "new_text": new_text,
        }
        if comment:
            if new_text == "":
                return (
                    "ERROR: You passed comment with new_text='' (pure deletion). "
                    "Adeu silently drops comments on pure deletions. Either drop "
                    "the comment, or attach it to a retained anchor via a "
                    "separate modify_text call with a substantive new_text."
                )
            kwargs["comment"] = comment
        edit = ModifyText(**kwargs)  # type: ignore[arg-type]
        return _apply_one_edit(output_path, edit)

    @tool
    def insert_text(anchor_text: str, new_text: str, comment: str = "") -> str:
        """Insert ``new_text`` immediately after ``anchor_text`` via tracked insertion.

        The anchor must exist in the document exactly once (case, whitespace,
        punctuation match exactly). The insertion produces a single ``<w:ins>``
        with no paired ``<w:del>`` — Word shows underlined inserted text only,
        original text stays intact around it.

        Pick anchors that end with punctuation (full stop, semicolon) — they
        read naturally and avoid truncating mid-word. Use the shortest anchor
        that is still unique in the document.

        To insert a new paragraph or clause, include a leading space or
        newline in ``new_text`` (e.g. ``" "`` at the start, or ``"\\n"``
        to break to a new paragraph). If you start ``new_text`` with
        ``"# "``, ``"## "``, etc., that paragraph becomes a heading.

        Internally this is a facilitator — Adeu's native idiom is to pass
        the anchor as ``target_text`` and ``anchor+new_text`` as
        ``new_text``; the engine detects the prefix match and synthesises an
        insertion (ADR 018). You see the simpler shape; the mechanics are
        identical.
        """
        kwargs: dict[str, object] = {
            "target_text": anchor_text,
            "new_text": anchor_text + new_text,
        }
        if comment:
            kwargs["comment"] = comment
        edit = ModifyText(**kwargs)  # type: ignore[arg-type]
        return _apply_one_edit(output_path, edit)

    return [modify_text, insert_text]


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------


def redline_specialist_prompt(output_path: Path) -> str:
    return f"""You are the redline specialist in an in-house legal function. You receive a Word NDA plus a transformation instruction from the Head of Commercial. You apply tracked-change edits to the NDA using two tools (``modify_text`` and ``insert_text``) and return the saved output path when done.

Operating discipline — READ THIS FIRST.
Your ONLY way to change the document is by calling ``modify_text`` or ``insert_text``. You do NOT have any other tools. You do NOT hand-edit OOXML. You do NOT produce the final .docx yourself; the tools write the file for you. When you are finished applying edits, reply with ONE sentence naming the output path exactly as given below — do not add prose beyond that sentence.

The output file is: ``{output_path}``. After your last tool call, reply exactly with: "Redline saved to {output_path}."

The transformation task for this invocation:
Convert the dispute resolution clause in this NDA from litigation (submission to the exclusive jurisdiction of the courts of England and Wales) to binding arbitration. Keep the governing-law sentence (laws of England and Wales) intact — only the dispute-resolution sentence changes.

Shape of the arbitration clause you must produce. A complete arbitration clause names FIVE things. Draft them into the replacement text explicitly; do not leave any out, and do not default to generic language:
  1. The seat of arbitration — London, England.
  2. The arbitral rules — the LCIA Rules in force at the commencement of arbitration.
  3. The number of arbitrators — one (sole arbitrator).
  4. The language of arbitration — English.
  5. That the arbitration is final and binding.

How to decompose the edit.
The clause to change is one sentence only: "The parties submit to the exclusive jurisdiction of the courts of England and Wales for the resolution of all disputes arising out of or in connection with this Agreement." Replace the WHOLE of that sentence with a new arbitration sentence covering the five elements above. Do not touch the governing-law sentence that precedes it ("This Agreement ... shall be governed by and construed in accordance with the laws of England and Wales."). Do not touch any other clause in the document.

Pick your target_text to match exactly one span. The litigation sentence appears once, starting "The parties submit to the exclusive jurisdiction" and ending "in connection with this Agreement." Use the whole sentence as ``target_text`` — that is the correct scope. Adeu's engine will narrow the displayed redline to the actually-differing words using its trim_common_context feature, so you do not need to minimise the span manually.

Rules for target_text (applies to both tools).
  * It MUST match the document exactly — case, punctuation, and whitespace.
  * It MUST match exactly one span. Zero matches or two-or-more matches fail with an ERROR you can read; if so, shorten or lengthen until unique.
  * Do NOT include any CriticMarkup markers ({{--...--}}, {{++...++}}, etc.) in target_text or new_text. Those are Adeu's output; passing them as input confuses the match.
  * Do NOT use markdown bold (**) or italic (_) in new_text unless you intend bold or italic output in Word.
  * Do NOT pass ``comment`` on a deletion (new_text=""); Adeu silently drops it. You should not need comments at all for this transformation, but if you add one, put it on the substantive modification, not on any deletion.

Destructive-rewrite guardrail. Do NOT delete an entire clause heading or adjacent untouched sentences to replace them. Only the litigation sentence changes; everything else stays exactly as drafted. If you find yourself about to call ``modify_text`` with a ``target_text`` that spans more than one sentence or crosses a clause boundary, stop and reconsider — you are almost certainly over-broadening the scope.

Tool-call discipline.
Make one tool call for this transformation: a single ``modify_text`` call with the litigation sentence as ``target_text`` and the arbitration sentence as ``new_text``. Read the tool's return value. If it starts with ``ERROR:``, read the error carefully, correct the target_text, and retry — do not retry the same target if the error was an unmatched or ambiguous match. If ``edits_applied`` is 1, you are done.

After the tool returns ``applied: edits_applied=1 edits_skipped=0``, reply with exactly: "Redline saved to {output_path}."
"""


class AcceptRejectDecision(BaseModel):
    """Decision on a single proposed contract markup (Sprint 9).

    Copied inline from ``src/experiments/sprint-09-accept-reject-specialist/
    gc_commercial_acceptreject.py`` because that module lives in a
    hyphenated directory path that isn't importable by name. The schema
    and prompt are stable per ADR 015 (playbook rule hardcoded).
    """

    decision: Literal["accept", "reject", "counter"] = Field(
        description="One of accept, reject, counter."
    )
    reason: str = Field(description="One sentence explaining the decision.")
    counter_language: str = Field(
        default="",
        description=(
            "Proposed alternative wording. REQUIRED (non-empty) when "
            "decision == 'counter'. Empty string otherwise."
        ),
    )


ACCEPT_REJECT_SYSTEM_PROMPT = """You are an accept/reject reasoner. Given a single proposed contract markup and the playbook rule that governs it, decide one of three outcomes: accept, reject, or counter.

Output discipline — READ THIS FIRST.
Your ONLY output channel is a single tool call to the `AcceptRejectDecision` tool with the structured arguments shown below. Do not write prose. Do not write a chat reply. Do not wrap the JSON in markdown code fences (```). Do not explain your reasoning outside the `reason` field of the tool call. Emit exactly one tool call and nothing else.

Rule GL-001 (Governing Law). The client's position is that governing law must be England and Wales. Apply this in exact order to every inbound markup:
  1. If the counterparty has accepted England and Wales, or left it unchanged, decide: accept.
  2. If the counterparty proposes Scotland, Northern Ireland, or Ireland as the governing law, decide: counter. The client still wants England and Wales. When deciding counter, you MUST populate `counter_language` with a complete, self-contained English sentence that restates England and Wales as the governing law, with a brief justification drafted for this markup.
  3. If the counterparty proposes any other jurisdiction (for example Delaware, New York, Singapore, Germany), decide: reject.

Rules for the Decision tool call:
- `decision` is exactly one of accept, reject, counter.
- `reason` is one sentence.
- `counter_language`: on counter decisions MUST be a non-empty English sentence the client would send back to the counterparty, drafted specifically for this markup (do not copy boilerplate). On accept and reject decisions, leave it as an empty string.

No hedging. No requests for more information. No other rules apply in this sprint."""


def _build_accept_reject_spec() -> dict:
    """SubAgent spec for the accept/reject specialist (Sprint 9 sibling)."""
    return {
        "name": "accept-reject-reasoner",
        "description": (
            "Decides accept / reject / counter on a single proposed contract "
            "markup against a playbook rule. Call this when you have one "
            "markup and the governing rule and need a decision. Returns a "
            "structured AcceptRejectDecision JSON."
        ),
        "system_prompt": ACCEPT_REJECT_SYSTEM_PROMPT,
        "tools": [],
        "model": get_chat_model(
            env_prefix="OSCAR_LLM_ACCEPT_REJECT_REASONER"
        ),
        "response_format": AcceptRejectDecision,
    }


HEAD_OF_COMMERCIAL_SYSTEM_PROMPT = """You are the Head of Commercial in an in-house legal function. You are responsible for commercial contract work — NDAs, MSAs, SaaS agreements, procurement contracts, amendments, and similar.

Output discipline — READ THIS FIRST.
You have NO direct filesystem access, NO ability to verify file existence, and NO tools of your own beyond the `task` tool. You MUST NOT claim that a file is missing, invalid, unreadable, or does not exist — you have no way to know. File validation is the specialist's job (and, underneath, Adeu's job). Your job is to route the inbound request to the correct specialist and relay the specialist's response.

Staffed specialists under you (subagent names to use with the `task` tool):
  - redline-specialist: applies DOCUMENT-LEVEL transformations to a .docx NDA using tracked changes — e.g., "convert the dispute resolution clause from litigation to arbitration", "make this mutual", "add a limitation of liability". Use this whenever the inbound task asks to transform, redline, amend, or rewrite a clause or clauses in a .docx file (with or without a file path).
  - accept-reject-reasoner: decides accept / reject / counter on a SINGLE proposed contract markup against a playbook rule. Returns a structured JSON decision. Use this ONLY when the inbound task is a decision on one markup that a counterparty has already proposed (including "accepted unchanged", "proposed change to X", "struck through") AND a playbook rule applies.

Routing rules (follow strictly):
  1. If the inbound task asks to transform / redline / amend / rewrite / convert / change / modify a clause in a .docx NDA (with or without a specified file path), you MUST delegate to `redline-specialist` via the `task` tool. Do not try to decide whether the file exists, is valid, or is reachable — the specialist handles that. Pass the transformation instruction verbatim in the `description` field; if the user named a file path, include it verbatim in the description too.
  2. If the inbound task describes a single counterparty position on a clause AND a playbook rule that governs it (and does NOT ask for a document-level transformation), delegate to `accept-reject-reasoner` via the `task` tool. "Accepted unchanged" and "no change" still count as a counterparty position — delegate anyway.
  3. If neither (1) nor (2) applies, respond plainly (one or two sentences) describing what you would do. Do not attempt to perform the work yourself.

After delegating, relay the specialist's response verbatim (or lightly paraphrased) back to the General Counsel in plain English:
  * `redline-specialist` replies with a short sentence naming the output .docx path. Include that path verbatim in your response to GC.
  * `accept-reject-reasoner` replies with a structured JSON decision (`decision`, `reason`, `counter_language`). State the decision, include the reason, and include `counter_language` verbatim when decision is "counter".

Do not invent information. Do not claim that a tool failed unless the specialist's response explicitly says it did."""


GC_SYSTEM_PROMPT = """You are the General Counsel of an in-house legal function. Your job is to classify inbound work and delegate to the right department head via the `task` tool.

Currently staffed department heads (subagent names you can call via `task`):
  - head-of-commercial: commercial contract work — NDAs, MSAs, SaaS agreements, procurement contracts, amendments, and any accept/reject/counter decisions on specific contract markups, including document-level transformations of .docx contracts.

Other departments (company secretarial, data protection, employment, property, litigation, and anything else) are NOT yet staffed. For those requests, respond exactly: "this department is not yet staffed". Do not delegate when no department head is staffed for the request.

When delegating to a staffed head, synthesise their response into a final reply to the user. Include any file paths the head surfaces — the user needs those to open the output. When not delegating, reply directly."""


# ---------------------------------------------------------------------------
# Agent construction — matches Sprint 9 pattern (ADR 014)
# ---------------------------------------------------------------------------


def _build_redline_specialist(
    input_path: Path, output_path: Path
) -> dict:
    """Build the redline-specialist SubAgent spec bound to the given paths."""
    tools = make_redline_tools(input_path, output_path)
    return {
        "name": "redline-specialist",
        "description": (
            "Applies document-level redlining transformations to a .docx NDA "
            "using tracked changes. Call this when the inbound task names or "
            "describes a .docx file and asks for a transformation, redline, "
            "amendment, or rewrite of a clause or clauses. Returns a short "
            "sentence naming the output .docx path when done."
        ),
        "system_prompt": redline_specialist_prompt(output_path),
        "tools": tools,
        "model": get_chat_model(env_prefix="OSCAR_LLM_REDLINE_SPECIALIST"),
    }


def _build_head_of_commercial(input_path: Path, output_path: Path) -> dict:
    """Build Head of Commercial as its own compiled Deep Agent (ADR 014)."""
    redline_spec = _build_redline_specialist(input_path, output_path)
    accept_reject_spec = _build_accept_reject_spec()
    hoc_graph = create_deep_agent(
        model=get_chat_model(env_prefix="OSCAR_LLM_HEAD_OF_COMMERCIAL"),
        tools=[],
        system_prompt=HEAD_OF_COMMERCIAL_SYSTEM_PROMPT,
        subagents=[redline_spec, accept_reject_spec],
    )
    return {
        "name": "head-of-commercial",
        "description": (
            "Head of Commercial. Delegate commercial contract work — NDAs, "
            "MSAs, SaaS agreements, procurement contracts, amendments, and "
            "any accept/reject/counter decisions on specific contract "
            "markups, including document-level redline transformations."
        ),
        "runnable": hoc_graph,
    }


def build_agents(
    input_path: Path = INPUT_DOCX, output_path: Path = OUTPUT_DOCX
):
    """Build GC (with nested HOC + specialists) bound to the given paths.

    Unlike Sprint 9 (which exposed a separate HOC probe for JSON
    extraction), Sprint 10D's specialist returns a plain-text path — no
    structured response to peel. One graph is enough.
    """
    hoc_under_gc = _build_head_of_commercial(input_path, output_path)
    gc_agent = create_deep_agent(
        model=get_chat_model(env_prefix="OSCAR_LLM_GENERAL_COUNSEL"),
        tools=[],
        system_prompt=GC_SYSTEM_PROMPT,
        subagents=[hoc_under_gc],
    )
    return gc_agent


# ---------------------------------------------------------------------------
# Invocation prompt
# ---------------------------------------------------------------------------

INVOCATION_PROMPT = (
    f"Please convert the dispute resolution clause in the attached NDA from "
    f"litigation to arbitration. Keep the governing-law sentence (England "
    f"and Wales) intact; change only the jurisdiction/dispute-resolution "
    f"sentence. The NDA is at {INPUT_DOCX.resolve()}."
)


# ---------------------------------------------------------------------------
# Trace helpers (borrowed from Sprint 9)
# ---------------------------------------------------------------------------


def _text_of(msg) -> str:
    text = getattr(msg, "content", "")
    if isinstance(text, list):
        parts: list[str] = []
        for block in text:
            if isinstance(block, dict):
                parts.append(str(block.get("text", block)))
            else:
                parts.append(str(block))
        text = " ".join(parts)
    return str(text)


def _final_text(messages) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            return _text_of(msg)
    return "<no final AI message found>"


def _summary(msg) -> str:
    kind = type(msg).__name__
    text = _text_of(msg).replace("\n", " ").strip()
    if isinstance(msg, ToolMessage):
        return f"[{kind} name={msg.name!r}] {text[:260]}"
    if isinstance(msg, AIMessage) and msg.tool_calls:
        calls = ", ".join(
            f"{c['name']}({list(c.get('args', {}).keys())})"
            for c in msg.tool_calls
        )
        return f"[{kind} tool_calls={calls}] {text[:220]}"
    return f"[{kind}] {text[:300]}"


def _gc_task_subagent_names(messages) -> list[str]:
    names: list[str] = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for call in msg.tool_calls:
                if call["name"] == "task":
                    names.append(call.get("args", {}).get("subagent_type", ""))
    return names


# ---------------------------------------------------------------------------
# Mechanical output verification
# ---------------------------------------------------------------------------


def verify_output(output_path: Path) -> tuple[bool, list[str]]:
    """Three mechanical checks per the brief.

    Returns ``(ok, notes)``. ``ok`` is True iff all three pass.
    """
    notes: list[str] = []

    # 1. File exists
    if not output_path.exists():
        return False, [f"output file does not exist: {output_path}"]
    notes.append(f"exists: {output_path} ({output_path.stat().st_size} bytes)")

    # 2. Valid zip
    try:
        with zipfile.ZipFile(output_path) as zf:
            names = zf.namelist()
            if "word/document.xml" not in names:
                return False, notes + ["word/document.xml not in zip"]
            doc_xml = zf.read("word/document.xml")
    except zipfile.BadZipFile:
        return False, notes + ["not a valid zip file"]
    notes.append(f"valid zip with {len(names)} parts")

    # 3. document.xml parses as XML
    from lxml import etree

    try:
        root = etree.fromstring(doc_xml)
    except etree.XMLSyntaxError as exc:
        return False, notes + [f"XML parse failed: {exc}"]
    notes.append(
        f"parsed OK (root tag: {etree.QName(root.tag).localname})"
    )

    # Extra diagnostics (non-gating): count w:ins / w:del
    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    NS = {"w": W_NS}
    ins = root.findall(".//w:ins", NS)
    dl = root.findall(".//w:del", NS)
    notes.append(f"tracked changes: w:ins={len(ins)}, w:del={len(dl)}")

    return True, notes


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _echo_env() -> None:
    for name in [
        "OSCAR_LLM_GENERAL_COUNSEL_PROVIDER",
        "OSCAR_LLM_GENERAL_COUNSEL_MODEL",
        "OSCAR_LLM_HEAD_OF_COMMERCIAL_PROVIDER",
        "OSCAR_LLM_HEAD_OF_COMMERCIAL_MODEL",
        "OSCAR_LLM_REDLINE_SPECIALIST_PROVIDER",
        "OSCAR_LLM_REDLINE_SPECIALIST_MODEL",
    ]:
        print(f"{name:45s} = {os.environ.get(name)!r}")


def main() -> None:
    _echo_env()
    print()

    if not INPUT_DOCX.exists():
        from build_input import build_document

        build_document()
        print(f"generated {INPUT_DOCX}")

    gc_agent = build_agents(INPUT_DOCX, OUTPUT_DOCX)

    print("=" * 72)
    print("INVOCATION")
    print(f"PROMPT:\n{INVOCATION_PROMPT}")
    print("=" * 72)

    result = gc_agent.invoke({"messages": [HumanMessage(INVOCATION_PROMPT)]})

    print("\n--- GC MESSAGE TRACE ---")
    for i, msg in enumerate(result["messages"], 1):
        print(f"  {i:2}. {_summary(msg)}")

    print("\n--- GC task() subagent_types ---")
    for n in _gc_task_subagent_names(result["messages"]):
        print(f"  {n}")

    final = _final_text(result["messages"])
    print("\n--- FINAL RESPONSE (GC → user) ---")
    print(final)

    print("\n--- MECHANICAL VERIFICATION ---")
    ok, notes = verify_output(OUTPUT_DOCX)
    for n in notes:
        print(f"  {n}")

    print()
    if not ok:
        raise AssertionError(
            "Sprint 10D verification failed — see notes above. Output file "
            "either missing, not a valid zip, or word/document.xml did not "
            "parse."
        )
    print("sprint-10d: end-to-end redline run succeeded (mechanical checks).")
    print(
        f"\nOutput for human review: {OUTPUT_DOCX}\n"
        f"Open in Word, review the track changes against the NDA's "
        f"litigation clause (Clause 9). Sprint 10E iterates based on findings."
    )


if __name__ == "__main__":
    main()
