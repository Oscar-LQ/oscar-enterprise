"""Sprint 10F — Identification test: same NDA transformation as 10D/10E, but
the specialist has to find the spans itself.

Sprint 10E proved MiniMax can EXECUTE a surgical-span decomposition when the
prompt supplies the exact target_text / new_text / anchor_text values. 10F
removes the decomposition. The specialist is given the general rule (surgical
spans) and the target shape (LCIA arbitration with five named elements), but
NOT the specific phrases in the existing document. The open question: can
MiniMax read §9, decide which phrases need to change, and apply narrow edits
without being told the spans?

Three changes vs. Sprint 10E (all local to this file):

    1. ``redline_specialist_prompt`` rewritten. Removes the "DECOMPOSITION FOR
       THIS TRANSFORMATION" block that handed the specialist CALL 1 / CALL 2
       with exact target_text / new_text / anchor_text values. Removes the
       10E-specific RIGHT example. Replaces with a "HOW TO APPROACH THIS
       TRANSFORMATION" section that tells the specialist to read §9, decide
       which phrases need to change, and apply narrow edits. Keeps (a) the
       output-discipline preamble, (b) the NO-RETRY RULE, (c) the
       SURGICAL-SPAN RULE, (d) SHAPE OF THE ARBITRATION LANGUAGE (five
       required elements), and (e) the WRONG example quoting Sprint 10D's
       wholesale-swap failure — these are execution guardrails unchanged
       by the identification test. The decomposition crutch is what 10F
       removes; the execution guardrails stay.

       Per Arturs's plan approval: the shape guidance is "one wide call is
       the wrong shape AND many tiny fragments is also the wrong shape — you
       are making a small handful of narrow edits". No count range is given
       — that was judged to be softer scaffolding but still scaffolding.

    2. THE TASK paragraph softened. 10E said "from litigation (exclusive
       jurisdiction of the courts of England and Wales) to binding LCIA
       arbitration" — the parenthetical pre-identified the forum phrase.
       10F says "from litigation to binding LCIA arbitration" — no
       pre-identification of the specific forum phrase.

    3. ``verify_output`` retains 10E's four warnings (span widths,
       empty-delText nested delete, duplicate w:ins, litigation phrase
       preservation). Added: a clean-view arbitration-shape spot-check in
       ``main`` that reports whether each of the five required elements
       (seat London, LCIA, sole arbitrator, English, final-and-binding)
       appears in the post-edit clean-view §9 text. This is the
       "span selection quality" assessment the 10F plan called for.

Scope (per brief): Sprint 10F tests IDENTIFICATION of surgical spans when
given only the rule and the high-level target. It does NOT test identification
on a wider variety of transformations — that is 10G+ territory. A successful
10F is evidence MiniMax can produce a narrow decomposition for THIS
transformation; a failed 10F triggers the Sprint 10G model swap to GPT-5.4.

Input: identical to Sprint 10D/10E's ``nda-input.docx`` (same clause
structure; ``build_input.py`` regenerates it). Output: ``nda-output.docx`` in
this directory; transcript with verbatim tool calls in ``transcript.txt``;
per-call JSON in ``tool-calls.jsonl``.
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import sys
import zipfile
from collections import Counter
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

from adeu import ModifyText, RedlineEngine, extract_text_from_stream
from adeu.redline.engine import BatchValidationError

from llm.chat_model import get_chat_model


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
INPUT_DOCX = HERE / "nda-input.docx"
OUTPUT_DOCX = HERE / "nda-output.docx"
TRANSCRIPT = HERE / "transcript.txt"
TOOL_CALL_LOG = HERE / "tool-calls.jsonl"

AUTHOR = "Oscar"

# Module-level capture of specialist tool calls. Deep Agents' `task` tool
# hides subagent messages behind the final string — we can't extract the
# specialist's modify_text/insert_text args from the GC-level message trace
# (confirmed empirically in Sprint 10E). The tool functions themselves are
# the only reliable capture point. Carry-forward infrastructure from 10E.
_TOOL_CALL_CAPTURE: list[dict] = []


# ---------------------------------------------------------------------------
# Tool factory — closure over input/output paths (ADR 017)
# ---------------------------------------------------------------------------


def _reset_output(input_path: Path, output_path: Path) -> None:
    """Copy input to output so subsequent edits accumulate on output."""
    shutil.copyfile(input_path, output_path)


def _apply_one_edit(output_path: Path, edit: ModifyText) -> str:
    """Read output, apply one edit, write back, return a summary string.

    Returns a summary like ``"applied: edits_applied=1 edits_skipped=0 — ..."``.
    The leading ``applied: edits_applied=N edits_skipped=M`` prefix is stable
    (the prompt's stop-condition matches on it). On ``BatchValidationError``
    returns a string starting with ``ERROR:`` and the formatted error list so
    the agent can retry with better target_text.

    The anti-retry brake sentence on successful applications is the 10E
    addition that kept MiniMax from nesting edits on its own insertions. It
    still applies for 10F — the failure mode it prevents (self-retargeting)
    is independent of whether the specialist identifies the spans itself.
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
    summary += (
        " — this region is now TRACKED; do NOT call modify_text or "
        "insert_text on overlapping text again. Move to the next planned "
        "call or stop."
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

    def _record(name: str, args: dict) -> None:
        _TOOL_CALL_CAPTURE.append({"name": name, "args": args})
        import json as _json
        with open(TOOL_CALL_LOG, "a") as _f:
            _f.write(_json.dumps({"name": name, "args": args}) + "\n")

    @tool
    def modify_text(target_text: str, new_text: str, comment: str = "") -> str:
        """Replace ``target_text`` in the NDA with ``new_text`` via tracked change.

        Thin wrapper over ``adeu.ModifyText``. The ``target_text`` MUST match
        exactly ONE span in the document — if zero or more than one match,
        the edit is rejected with an ERROR you can read and retry. Target
        text should be the smallest phrase that contains the words you are
        changing plus just enough anchor context for unique match (5-15
        words); do NOT pass a whole sentence when only part of it differs.

        The original text is preserved inside ``<w:delText>`` (Word shows it
        struck through); the replacement is inserted with ``<w:ins>`` (shown
        underlined). Both carry ``w:author="Oscar"``.

        To delete text without replacement, pass ``new_text=""`` — this
        produces a tracked deletion. Do NOT pass ``comment`` on deletions:
        Adeu silently drops comments on pure deletions (this is a known
        quirk). If you want to comment on a deletion, attach the comment to
        a retained anchor nearby via a separate modify_text call.
        """
        _record(
            "modify_text",
            {"target_text": target_text, "new_text": new_text, "comment": comment},
        )
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
        _record(
            "insert_text",
            {"anchor_text": anchor_text, "new_text": new_text, "comment": comment},
        )
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
    """Sprint 10F — identification-mode system prompt.

    Differences from Sprint 10E:
      * DECOMPOSITION FOR THIS TRANSFORMATION block removed. The specialist
        is not handed CALL 1 / CALL 2 values; it must decide from the clause
        text.
      * THE TASK paragraph softened — 10E named "exclusive jurisdiction of
        the courts of England and Wales" in the task framing, which
        pre-identified the forum phrase. 10F says only "from litigation to
        binding LCIA arbitration".
      * Shape guidance added (approved wording): "one wide tool call is the
        wrong shape ... many tiny fragment calls is also the wrong shape ...
        a small handful of narrow edits". No count range given.
      * OPERATING DISCIPLINE section added — the iteration-2 fix after
        iteration 1 surfaced the same hallucinate-missing-file failure
        Sprint 10D iteration 1 hit. With 10E's decomposition crutch
        removed, MiniMax defaulted to "the file does not exist" rather
        than attempting the task. This section forbids that claim and
        explains how to operate tool-only (reason from NDA-drafting
        knowledge, try target_text, let the ERROR return guide adjustment).

    Unchanged from 10E (execution guardrails, not identification scaffolding):
      * OUTPUT DISCIPLINE preamble (Sprint 9 MiniMax tool-call discipline).
      * NO-RETRY RULE (prevents 10D nested-delete failure).
      * SURGICAL-SPAN RULE (5-15 words, only the phrase that differs).
      * SHAPE OF THE ARBITRATION LANGUAGE (five required elements).
      * RULES FOR TARGET / ANCHOR TEXT (exact match, unique span, no
        CriticMarkup, no markdown).
      * WRONG example quoting Sprint 10D's wholesale-swap failure — shape
        warning, not identification crutch (it shows the wrong answer, not
        the right one).
      * Error handling (read the ERROR, adjust once, retry; then stop).
      * Final-reply template.
    """
    return f"""You are the redline specialist in an in-house legal function. You receive a Word NDA plus a transformation instruction from the Head of Commercial. You apply tracked-change edits to the NDA using two tools (``modify_text`` and ``insert_text``) and return the saved output path when done.

OUTPUT DISCIPLINE — READ THIS FIRST.
Your ONLY way to change the document is by calling ``modify_text`` or ``insert_text``. You do NOT hand-edit OOXML. You do NOT produce the final .docx yourself. When you are finished, reply with ONE sentence naming the output path exactly as given below — no extra prose.
The output file is: ``{output_path}``. After your last tool call, reply exactly with: "Redline saved to {output_path}."

OPERATING DISCIPLINE — HOW YOU WORK ON THE FILE.
You have NO filesystem read access. You cannot open the .docx, list directories, or verify that a file exists. Your ONLY way to touch the document is through ``modify_text`` and ``insert_text`` — the tools know where the document is and apply edits to it on your behalf. You MUST NOT claim that a file is missing, invalid, unreadable, or that a directory does not exist — you have no way to know, and such claims are fabrications.

If your ``target_text`` does not match the document, ``modify_text`` returns an ERROR with diagnostic detail — that ERROR is your feedback channel, not a filesystem check. Proceed by reasoning about what a commercial English-law NDA §9 "Governing Law and Dispute Resolution" clause typically contains when it names litigation (a forum-submission sentence), pick target_text phrases based on that reasoning, and let the tool's ERROR / success return guide any adjustment. When in doubt, start with what you believe is the narrowest high-probability phrase and try it; adjust only if the tool reports zero or multiple matches.

NO-RETRY RULE.
After each tool call, READ the return value. If it begins with ``applied: edits_applied=1 edits_skipped=0``, that edit is DONE. Do NOT call modify_text or insert_text on the same or overlapping text again. Do NOT "improve" or "re-verify" a successful edit. Re-targeting a region you already edited will nest a new redline inside your previous one, clear the original text from the audit trail, and produce a broken redline. Move on to the next planned call or stop.

THE TASK.
Convert the dispute-resolution provision in Clause 9 from litigation to binding LCIA arbitration. The governing-law sentence that precedes it (laws of England and Wales) stays INTACT.

SHAPE OF THE ARBITRATION LANGUAGE. The final arbitration provision must name all five of: (1) seat London, (2) LCIA Rules, (3) one sole arbitrator, (4) English language, (5) final and binding on the parties.

SURGICAL-SPAN RULE — CORE DISCIPLINE.
Your ``target_text`` is a locator for the smallest slice of the document that actually changes. Target 5-15 words, only the phrase that differs, plus just enough anchor context for a unique match. Never use a whole sentence or paragraph as target_text when only part of it differs. Never rewrite what you are not changing.

HOW TO APPROACH THIS TRANSFORMATION.
Read Clause 9 (Governing Law and Dispute Resolution) in the NDA. The governing-law sentence stays intact. The dispute-resolution sentence names litigation today; it must become arbitration carrying the five elements listed above. Decide — by reading the clause — which phrases in the existing language need to be replaced, and which new language needs to be added. Apply those decisions as narrow tracked-change edits: ``modify_text`` for replacements, ``insert_text`` for additions.

One wide tool call is the wrong shape — you are not doing a wholesale sentence swap. Many tiny fragment calls is also the wrong shape — you are not copy-editing word by word. You are making a small handful of narrow edits that together transform the clause.

RULES FOR TARGET / ANCHOR TEXT (apply to both tools).
  * MUST match the document exactly — case, punctuation, whitespace.
  * MUST match exactly one span. Zero or multiple matches return ERROR; read it, adjust the target once, retry.
  * Do NOT include CriticMarkup markers ({{--...--}}, {{++...++}}) in either field.
  * Do NOT use markdown bold (**) or italic (_) in new_text.
  * Do NOT pass ``comment`` on a pure deletion (new_text=""); Adeu drops it.

WRONG — one wide rewrite (what Sprint 10D did — DO NOT DO THIS):
  modify_text(
    target_text="The parties submit to the exclusive jurisdiction of the courts of England and Wales for the resolution of all disputes arising out of or in connection with this Agreement.",
    new_text="Any dispute arising out of or in connection with this Agreement shall be finally resolved by binding arbitration under the LCIA Rules, seated in London, ... a sole arbitrator ... final and binding on the parties."
  )
  # Result: 40+ word w:del, 40+ word w:ins. A human reviewing in Word cannot see which words actually change.

If a call returns ERROR, read the message, adjust ONCE, retry. If it errors again, STOP and report the error in your final reply instead of the saved-to line. Do not keep guessing.

When your edits together produce a complete arbitration provision with all five required elements, reply exactly: "Redline saved to {output_path}."
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
    """Build GC (with nested HOC + specialists) bound to the given paths."""
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
# Trace helpers (borrowed from Sprint 9/10D/10E)
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


def get_recorded_tool_calls() -> list[dict]:
    """Return the specialist tool calls captured by the tool implementations.

    Source of truth for the sprint-log entry's "verbatim tool calls"
    section. See 10E for why this capture lives in the tool functions
    rather than in the GC-level message trace.
    """
    return list(_TOOL_CALL_CAPTURE)


# ---------------------------------------------------------------------------
# Mechanical output verification (10F = 10E's four warnings unchanged)
# ---------------------------------------------------------------------------

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": W_NS}


def _element_text(el) -> str:
    """Concatenate all w:t + w:delText descendant text of a w:ins or w:del."""
    texts = el.xpath(".//w:t/text() | .//w:delText/text()", namespaces=_NS)
    return "".join(texts)


def _element_word_count(el) -> int:
    text = _element_text(el).strip()
    return len(text.split()) if text else 0


def verify_output(output_path: Path) -> tuple[bool, list[str]]:
    """Three mechanical checks + four Sprint 10E lawyer-shape warnings.

    The ``ok`` return reflects only the three mechanical checks from 10D
    (file exists, valid zip, parseable document.xml). The four warnings are
    diagnostic: they append to ``notes`` with a ``WARN:`` prefix and never
    flip ``ok`` to False. Sprint 10F's pass/fail criterion is what the
    warnings say, not a boolean gate.

    Warnings operationalise the lawyer-shape criteria:
      (1) span widths — any w:ins/w:del over 20 words is SUSPICIOUS, over
          50 is ALMOST CERTAINLY OVER-BROAD.
      (2) empty w:delText inside a nested w:del — the 10D nested-delete
          signature that lost the litigation text from the audit trail.
      (3) duplicate w:ins content (>10 words, ≥2 copies) — the 10D
          duplicate-insertion signature.
      (4) litigation phrase present somewhere in a w:delText — the
          transformation-specific audit-trail spot-check.
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

    from lxml import etree

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

    # (1) Span widths — per-element word counts.
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
    all_del_text = "".join(
        root.xpath(".//w:delText/text()", namespaces=_NS)
    )
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
# Arbitration-shape spot-check (Sprint 10F — span selection quality)
# ---------------------------------------------------------------------------

# Each check is a tuple (label, predicate) — predicate takes the clean-view
# §9 excerpt and returns True if the element is present. Predicates are
# intentionally loose (case-insensitive substring / alternatives) because
# MiniMax may draft with minor wording variation; we're testing whether the
# five substantive elements are present, not matching a specific sentence.

def check_arbitration_shape(clause_text: str) -> list[str]:
    """Report whether each of the five required arbitration elements is
    present in the clean-view §9 text.

    Returns a list of notes, one per element, prefixed FOUND / MISSING.
    This is the "span selection quality" assessment the 10F plan called for:
    narrow-but-wrong edits produce a valid-looking .docx that doesn't carry
    the required arbitration content.
    """
    t = clause_text.lower()

    def has_any(*alts: str) -> bool:
        return any(alt in t for alt in alts)

    checks = [
        ("seat: London", has_any("london")),
        ("rules: LCIA", has_any("lcia")),
        ("sole arbitrator (one)", has_any("sole arbitrator", "one arbitrator", "single arbitrator")),
        ("language: English", has_any("language shall be english", "language english", "in the english language", "english language", "language of the arbitration shall be english")),
        ("final and binding", has_any("final and binding", "finally and bindingly")),
    ]
    notes: list[str] = []
    for label, ok in checks:
        notes.append(f"{'FOUND' if ok else 'MISSING'}: {label}")
    return notes


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

    _TOOL_CALL_CAPTURE.clear()
    if TOOL_CALL_LOG.exists():
        TOOL_CALL_LOG.unlink()

    gc_agent = build_agents(INPUT_DOCX, OUTPUT_DOCX)

    print("=" * 72)
    print("INVOCATION")
    print(f"PROMPT:\n{INVOCATION_PROMPT}")
    print("=" * 72)

    result = gc_agent.invoke({"messages": [HumanMessage(INVOCATION_PROMPT)]})

    print("\n--- GC MESSAGE TRACE ---")
    trace_lines = []
    for i, msg in enumerate(result["messages"], 1):
        line = f"  {i:2}. {_summary(msg)}"
        print(line)
        trace_lines.append(line)

    print("\n--- GC task() subagent_types ---")
    subagent_names = _gc_task_subagent_names(result["messages"])
    for n in subagent_names:
        print(f"  {n}")

    final = _final_text(result["messages"])
    print("\n--- FINAL RESPONSE (GC → user) ---")
    print(final)

    specialist_calls = get_recorded_tool_calls()
    print("\n--- SPECIALIST TOOL CALLS (VERBATIM) ---")
    print(f"  (count: {len(specialist_calls)})")
    if not specialist_calls:
        print("  (none — specialist made no modify_text/insert_text calls)")
    else:
        for i, call in enumerate(specialist_calls, 1):
            print(f"  CALL {i}: {call['name']}(")
            for k, v in call["args"].items():
                print(f"    {k}={v!r},")
            print("  )")

    print("\n--- MECHANICAL VERIFICATION ---")
    ok, notes = verify_output(OUTPUT_DOCX)
    for n in notes:
        print(f"  {n}")

    print("\n--- CLEAN-VIEW READ-BACK (simulated Accept-All) ---")
    clean_view_excerpt = ""
    try:
        with open(OUTPUT_DOCX, "rb") as f:
            clean_view = extract_text_from_stream(
                io.BytesIO(f.read()), clean_view=True
            )
        marker = "9. Governing Law"
        idx = clean_view.find(marker)
        if idx >= 0:
            clean_view_excerpt = clean_view[idx : idx + 1200]
        else:
            idx = clean_view.find("England and Wales")
            clean_view_excerpt = (
                clean_view[max(0, idx - 200) : idx + 1000]
                if idx >= 0
                else clean_view[:1500]
            )
        for line in clean_view_excerpt.splitlines():
            print(f"  {line}")
    except Exception as exc:
        print(f"  <clean-view extraction failed: {exc}>")

    print("\n--- ARBITRATION-SHAPE SPOT-CHECK (Sprint 10F — clean-view §9) ---")
    shape_notes = check_arbitration_shape(clean_view_excerpt)
    for n in shape_notes:
        print(f"  {n}")

    with open(TRANSCRIPT, "w") as f:
        f.write("=" * 72 + "\n")
        f.write("Sprint 10F — transcript\n")
        f.write("=" * 72 + "\n\n")
        f.write(f"INVOCATION:\n{INVOCATION_PROMPT}\n\n")
        f.write("--- GC MESSAGE TRACE ---\n")
        for line in trace_lines:
            f.write(line + "\n")
        f.write("\n--- GC task() subagent_types ---\n")
        for n in subagent_names:
            f.write(f"  {n}\n")
        f.write("\n--- FINAL RESPONSE (GC → user) ---\n")
        f.write(final + "\n")
        f.write(f"\n--- SPECIALIST TOOL CALLS (VERBATIM) — count={len(specialist_calls)} ---\n")
        if not specialist_calls:
            f.write("  (none)\n")
        else:
            for i, call in enumerate(specialist_calls, 1):
                f.write(f"  CALL {i}: {call['name']}(\n")
                for k, v in call["args"].items():
                    f.write(f"    {k}={v!r},\n")
                f.write("  )\n")
        f.write("\n--- MECHANICAL VERIFICATION ---\n")
        for n in notes:
            f.write(f"  {n}\n")
        f.write("\n--- CLEAN-VIEW §9 EXCERPT ---\n")
        for line in clean_view_excerpt.splitlines():
            f.write(f"  {line}\n")
        f.write("\n--- ARBITRATION-SHAPE SPOT-CHECK ---\n")
        for n in shape_notes:
            f.write(f"  {n}\n")
    print(f"\ntranscript written to {TRANSCRIPT}")

    print()
    if not ok:
        raise AssertionError(
            "Sprint 10F verification failed — see notes above. Output file "
            "either missing, not a valid zip, or word/document.xml did not "
            "parse."
        )
    print("sprint-10f: end-to-end redline run completed (mechanical checks).")
    print(
        f"\nOutput for human review: {OUTPUT_DOCX}\n"
        f"Identification self-assessment is the combination of (a) span-width "
        f"WARN lines above, (b) tool-call count, and (c) the arbitration-shape "
        f"spot-check. Any WARN, an all-one-call shape, or missing arbitration "
        f"elements means 10F failed at the identification bar (even though "
        f"mechanical checks passed)."
    )


if __name__ == "__main__":
    main()
