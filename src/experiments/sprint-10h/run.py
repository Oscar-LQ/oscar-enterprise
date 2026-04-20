"""Sprint 10H — Planner / Executor Split (Shape A).

Two-LLM split under Head of Commercial: a frontier planner (GPT-5.4 via
OpenRouter) decomposes the requested transformation into a narrow edit
plan; a specialist executor (MiniMax-M2.7) applies each plan entry one
tool call at a time. The architectural thesis behind the split is in
SPRINT_LOG.md Sprint 10G and the 10H brief — summarised:

    * 10E proved MiniMax executes a pre-decided decomposition faithfully.
    * 10F proved MiniMax identifies the clause but does not decompose.
    * 10G falsified the "plan-first prompt fixes it" hypothesis.
    * Cost rules out a single-agent frontier specialist.
    * Shape A — frontier planner + specialist executor — is the target.

10H is the mechanical validation that Shape A produces lawyer-shape output
on the same NDA and the same transformation as 10D/10E/10F/10G
(litigation → binding LCIA arbitration).

The plan data contract (Arturs-approved, ADR 020): a fenced ```json block
containing an array of edit dicts, preceded by "I will make N edits." on
its own line. Per-edit fields: ``tool`` (discriminator — exactly
``modify_text`` or ``insert_text``), ``target_text`` (modify_text) or
``anchor_text`` (insert_text), ``new_text``, ``reason``. The executor
parses the fenced block, fails fast on any malformed entry (no "whole
message is JSON" fallback — tolerance erodes the split), and dispatches
on ``tool`` before validating required fields so an ``insert_text``
entry's ``anchor_text`` does not trip a spurious "missing target_text"
error.

Observability — three capture points:
    1. Planner's plan: BaseCallbackHandler on the planner's model.
       GPT-5.4 is clean-text (Sprint 4); no reasoning_split workaround.
    2. HOC's relay to the executor: BaseCallbackHandler on HOC's model
       filtering ``task`` tool calls with ``subagent_type="redline-executor"``.
       This separates "HOC corrupted the plan" from "planner planned badly"
       and "executor failed to execute" as distinct failure modes — without
       it, an Outcome-B-shape end state is ambiguous (10D Surprise 3).
    3. Executor's tool calls: ``_TOOL_CALL_CAPTURE`` + ``tool-calls.jsonl``
       inside the tool implementations (10E pattern; only reliable vantage).

Two runs:
    * Primary — GC → HOC → planner → HOC → executor → HOC → GC.
      Artefacts: ``nda-output.docx``, ``plan.txt``,
      ``hoc-invocations.jsonl``, ``tool-calls.jsonl``, ``transcript.txt``.
    * Control — executor alone, handed 10E's exact hand-decided spans in
      the 10H plan contract. Confirms the executor's pure-execution
      discipline has not regressed in the new architecture. Artefacts:
      ``control-nda-output.docx``, ``control-tool-calls.jsonl``,
      ``control-transcript.txt``.

Outcome classification (A / B / C) is reported in the sprint log entry
separately from the mechanical-criteria-plus-assessments summary per
Arturs's Clarification 3.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Literal

# Silence Adeu's structlog INFO/DEBUG stream before any adeu import.
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

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import LLMResult
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from deepagents import create_deep_agent

from adeu import ModifyText, RedlineEngine, extract_text_from_stream
from adeu.redline.engine import BatchValidationError

from llm.chat_model import get_chat_model


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
INPUT_DOCX = HERE / "nda-input.docx"

# Primary run (Shape A end-to-end).
OUTPUT_DOCX = HERE / "nda-output.docx"
TRANSCRIPT = HERE / "transcript.txt"
TOOL_CALL_LOG = HERE / "tool-calls.jsonl"
PLAN_LOG = HERE / "plan.txt"
HOC_INVOCATION_LOG = HERE / "hoc-invocations.jsonl"

# Control run (executor alone, 10E's spans).
CONTROL_OUTPUT_DOCX = HERE / "control-nda-output.docx"
CONTROL_TRANSCRIPT = HERE / "control-transcript.txt"
CONTROL_TOOL_CALL_LOG = HERE / "control-tool-calls.jsonl"

AUTHOR = "Oscar"


# ---------------------------------------------------------------------------
# Capture buffers — module-level, reset at each run's main()
# ---------------------------------------------------------------------------

_TOOL_CALL_CAPTURE: list[dict] = []
_PLAN_CAPTURE: list[str] = []
_HOC_INVOCATION_CAPTURE: list[dict] = []


class _PlanCapture(BaseCallbackHandler):
    """Attach to the planner's model only. Records every non-empty
    ``AIMessage.content`` emitted. GPT-5.4 returns plan text as content
    (no reasoning_split workaround needed per Sprint 4)."""

    def on_llm_end(  # type: ignore[override]
        self,
        response: LLMResult,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **_: Any,
    ) -> None:
        for gen_list in response.generations:
            for gen in gen_list:
                msg = getattr(gen, "message", None)
                if not isinstance(msg, AIMessage):
                    continue
                content = msg.content
                if isinstance(content, list):
                    pieces: list[str] = []
                    for block in content:
                        if isinstance(block, dict):
                            pieces.append(str(block.get("text", "")))
                        else:
                            pieces.append(str(block))
                    content = "".join(pieces)
                text = str(content).strip()
                if not text:
                    continue
                _PLAN_CAPTURE.append(text)
                with open(PLAN_LOG, "a") as f:
                    f.write("--- planner AIMessage ---\n")
                    f.write(text + "\n\n")


class _HocInvocationCapture(BaseCallbackHandler):
    """Attach to HOC's model only. On every AIMessage, walks tool_calls
    and records any ``task`` calls targeting ``redline-executor``.

    Purpose: separate three failure modes when end-state is wrong —
    (a) planner planned badly, (b) HOC corrupted the plan on relay,
    (c) executor failed to execute a faithfully-relayed plan. Without
    this capture, HOC's paraphrasing tendency (10D Surprise 3) leaves
    (b) indistinguishable from (c). Arturs's Addition 1.
    """

    def on_llm_end(  # type: ignore[override]
        self,
        response: LLMResult,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **_: Any,
    ) -> None:
        for gen_list in response.generations:
            for gen in gen_list:
                msg = getattr(gen, "message", None)
                if not isinstance(msg, AIMessage):
                    continue
                for call in (msg.tool_calls or []):
                    if call.get("name") != "task":
                        continue
                    args = call.get("args", {}) or {}
                    if args.get("subagent_type") != "redline-executor":
                        continue
                    description = args.get("description", "")
                    entry = {
                        "subagent_type": args.get("subagent_type"),
                        "description": description,
                    }
                    _HOC_INVOCATION_CAPTURE.append(entry)
                    with open(HOC_INVOCATION_LOG, "a") as f:
                        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Tool factory — unchanged from 10E (ADR 017 file-path closure; ADR 018
# facilitator-wrapper boundary)
# ---------------------------------------------------------------------------


def _reset_output(input_path: Path, output_path: Path) -> None:
    shutil.copyfile(input_path, output_path)


def _apply_one_edit(output_path: Path, edit: ModifyText) -> str:
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


def make_redline_tools(
    input_path: Path, output_path: Path, tool_call_log: Path
) -> list[BaseTool]:
    """Build the executor's Adeu-wrapped tools bound to the given paths.

    Copies ``input_path`` to ``output_path`` at factory time; each tool
    call reads and writes ``output_path`` — edits accumulate. Call the
    factory once per run (reseeds ``output_path`` from ``input_path``).

    ``tool_call_log`` is the jsonl path to which every call appends (the
    primary run uses ``TOOL_CALL_LOG``; the control run uses
    ``CONTROL_TOOL_CALL_LOG``).
    """
    _reset_output(input_path, output_path)

    def _record(name: str, args: dict) -> None:
        _TOOL_CALL_CAPTURE.append({"name": name, "args": args})
        with open(tool_call_log, "a") as f:
            f.write(json.dumps({"name": name, "args": args}) + "\n")

    @tool
    def modify_text(target_text: str, new_text: str, comment: str = "") -> str:
        """Replace ``target_text`` in the NDA with ``new_text`` via tracked change.

        Thin wrapper over ``adeu.ModifyText``. The ``target_text`` MUST
        match exactly ONE span in the document. Target 5-15 words —
        the smallest phrase that contains the words that are changing,
        plus just enough anchor context for a unique match. Do NOT pass
        a whole sentence when only part of it differs.

        The original text is preserved inside ``<w:delText>``; the
        replacement is inserted with ``<w:ins>``. Both carry
        ``w:author="Oscar"``. Pass ``new_text=""`` for a pure deletion.
        Do NOT pass ``comment`` on a pure deletion — Adeu silently drops
        it.
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

        The anchor must exist in the document exactly once (case,
        whitespace, punctuation match exactly). The insertion produces a
        single ``<w:ins>`` with no paired ``<w:del>``. Pick anchors that
        end with punctuation (full stop, semicolon). To insert a new
        paragraph or clause, include a leading space or newline in
        ``new_text``.

        Internally this is a facilitator — Adeu's native idiom is to pass
        the anchor as ``target_text`` and ``anchor+new_text`` as
        ``new_text``; the engine detects the prefix match and synthesises
        an insertion (ADR 018).
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
# System prompts — planner, executor, HOC, GC
# ---------------------------------------------------------------------------


REDLINE_PLANNER_PROMPT = """You are the redline planner in an in-house legal function. You receive a requested transformation (plain English) plus the clause text the transformation operates on (verbatim). You decompose the transformation into a narrow, surgical edit plan that a downstream executor will apply mechanically, one tool call per plan entry.

OPERATING DISCIPLINE.
You have no filesystem access. You do not open files, read documents, or verify anything on disk. The Head of Commercial passes the clause text in your task description — that is what you plan against. You MUST NOT claim that a file is missing, invalid, unreadable, or unreachable — you have no way to know such things, and you do not need to: the executor works from the file on disk, you work from the clause text in your input. Any filesystem tools visible to you are not part of your role; do not call them.

YOUR ONLY OUTPUT.
Your reply is the plan. Nothing else. No prose narration before or after. No tool calls. Format below.

THE TASK SHAPE.
The transformation may ask you to replace language (mapping to `modify_text`), add new language (mapping to `insert_text`), or both. Each of your plan entries is one atomic edit that the executor will issue as one tool call.

SURGICAL-SPAN RULE — CORE DISCIPLINE.
Each edit's locator (`target_text` for `modify_text`, `anchor_text` for `insert_text`) targets 5-15 words — the smallest slice of the clause that actually changes (for modify) or the smallest punctuation-bounded anchor (for insert). Never use a whole sentence as a locator when only part of it differs. Never rewrite what you are not changing. The executor is a dumb pipe; your plan's spans are exactly the spans the OOXML redline will show.

DECOMPOSITION DISCIPLINE.
One wide `modify_text` replacing an entire sentence is the wrong shape — it produces a whole-sentence `w:del` + whole-sentence `w:ins` with no visual indication of which words actually change. Many tiny word-level edits is also the wrong shape — a human reviewer cannot follow a one-word-at-a-time rewrite. A small handful of narrow, compositional edits (typically 2 to 4) is the target: one or two `modify_text` calls swapping the locally-changing phrases, plus possibly one `insert_text` call adding any new sentence the old clause does not contain.

RULES FOR TARGET / ANCHOR TEXT.
  * MUST match the supplied clause text exactly — case, punctuation, whitespace. The executor's tool will fail on unmatched spans and you cannot adjust after the fact.
  * MUST be uniquely locatable within the clause. If a phrase appears more than once, extend the locator until it is unique.
  * Do NOT include CriticMarkup markers, markdown bold/italic, or any other formatting syntax in either field.
  * Do NOT leave placeholders ("TBD", "…", "[phrase]"). Every field is the exact value the executor will pass to the tool.

OUTPUT FORMAT — EXACT.
Your reply contains exactly one fenced ```json block with a JSON array of edit objects. Immediately before the fenced block, write one line: "I will make N edits." where N is the array length. No other prose, before or after, including no closing remark.

Each edit object has EXACTLY four fields, all strings:
  * `tool`: "modify_text" or "insert_text".
  * For `modify_text` entries: `target_text` (the locator) and `new_text` (the replacement). MUST NOT include `anchor_text`.
  * For `insert_text` entries: `anchor_text` (the locator) and `new_text` (the text to insert immediately after the anchor). MUST NOT include `target_text`.
  * `reason`: one sentence explaining what this edit accomplishes.

The reason field is for audit; the executor ignores it. Write it clearly enough that a lawyer reading the plan alone can follow the transformation.

WORKED EXAMPLE — DIFFERENT TRANSFORMATION.
Suppose the transformation was: "narrow the defined term Confidential Information to exclude publicly available material" and the clause was:

  'In this Agreement, "Confidential Information" means any information, whether written, oral, electronic, or in any other form, disclosed by one Party to the other Party in connection with the Purpose.'

A surgical plan for that transformation:

I will make 1 edit.

```json
[
  {
    "tool": "modify_text",
    "target_text": "any information, whether written, oral, electronic, or in any other form, disclosed by one Party to the other Party",
    "new_text": "any non-public information, whether written, oral, electronic, or in any other form, disclosed by one Party to the other Party",
    "reason": "Narrow the defined term to exclude publicly available material by inserting 'non-public' before 'information'."
  }
]
```

Note that the example plans for a different transformation from the one you are about to receive, and in a different clause. Do not copy its wording or its shape — decompose the actual transformation you receive on its own terms.

STOP CONDITION.
When your plan is complete, emit "I will make N edits." followed by the fenced ```json block, and stop. Do not write an explanation, do not suggest next steps, do not critique your own plan. The plan is your output."""


def redline_executor_prompt(output_path: Path) -> str:
    """System prompt for the redline executor (Sprint 10H).

    Half the length of 10E's redline-specialist prompt — decomposition
    guidance is gone because the executor does not decompose. Discipline
    focuses on faithful execution of a plan handed in the initial
    HumanMessage.
    """
    return f"""You are the redline executor in an in-house legal function. You receive a JSON plan of narrow edits (from a planner upstream) plus the file path of the NDA those edits apply to. You execute each plan entry in order via `modify_text` or `insert_text`, one tool call per entry, and return the saved output path when done.

OPERATING DISCIPLINE.
You have no filesystem read access. You do not open the .docx, list directories, or verify that a file exists. Your ONLY way to change the document is through `modify_text` and `insert_text` — the tools know where the document is. You MUST NOT claim that a file is missing, invalid, unreadable, or unreachable — you have no way to know such things, and they are not your concern. Any filesystem tools visible to you are not part of your role; do not call them.

You do NOT plan, identify, or redraft. The plan is handed to you. Your job is to apply it faithfully.

INPUT FORMAT.
Your first message contains a fenced ```json block with an array of edit objects. Immediately before that block may appear the line "I will make N edits." (from the planner); you may ignore it — the array length is what binds.

Each edit object has exactly four fields:
  * `tool`: "modify_text" or "insert_text".
  * `target_text` (for modify_text) OR `anchor_text` (for insert_text): the locator. Pass this verbatim to the tool.
  * `new_text`: the replacement text (modify_text) or the text to insert after the anchor (insert_text). Pass this verbatim to the tool.
  * `reason`: a plain-English explanation. You ignore this at runtime.

MALFORMED-PLAN HANDLING — FAIL FAST.
If any of the following is true, reply exactly with `ERROR: plan malformed — {{reason}}` and stop — make no tool call:
  * The message does not contain a fenced ```json block.
  * The fenced block does not parse as JSON.
  * The parsed JSON is not a non-empty array.
  * Any entry lacks `tool`, `new_text`, or `reason`.
  * Any entry with `tool == "modify_text"` lacks `target_text`, or has `anchor_text` present.
  * Any entry with `tool == "insert_text"` lacks `anchor_text`, or has `target_text` present.
  * Any entry's `tool` is not one of "modify_text" or "insert_text".

Do NOT try to recover a malformed plan. Do NOT guess at missing fields. Do NOT paraphrase or "improve" the plan. The plan is a contract; malformed plans are errors, not opportunities.

HOW TO EXECUTE A WELL-FORMED PLAN.
For each entry in the array, in order:
  1. If `tool == "modify_text"`: call `modify_text(target_text=<entry.target_text>, new_text=<entry.new_text>)`. Pass both args byte-identical to the plan. Do not edit, reword, abbreviate, or "improve" the strings.
  2. If `tool == "insert_text"`: call `insert_text(anchor_text=<entry.anchor_text>, new_text=<entry.new_text>)`. Pass both args byte-identical to the plan.
  3. Read the tool's return value. If it starts with `applied: edits_applied=1`, that edit is done — move to the next entry. If it starts with `ERROR:`, STOP the execution and report the error (see final-reply template below).

NO-RETRY RULE.
Successful edits are done. Do NOT call `modify_text` or `insert_text` on the same span or an overlapping span again. Do NOT "re-verify" a successful edit with a repeat call. Re-targeting a region you already edited will nest a new redline inside your previous one, clear the original text from the audit trail, and produce a broken redline.

DO NOT DEVELOP OPINIONS.
You do not critique the plan. You do not suggest a better plan. You do not add an edit the plan did not specify. You do not skip an edit the plan did specify. You do not re-order edits. You do not combine edits. You do not split edits. The plan is the contract.

FINAL-REPLY TEMPLATE.
  * On success (every entry returned `applied: edits_applied=1`): reply exactly `Redline saved to {output_path}.` — no other prose, no summary, no narration.
  * On plan-malformed: reply exactly `ERROR: plan malformed — <one-line reason>` — no tool call, no other prose.
  * On tool ERROR: reply exactly `ERROR executing plan: <tool return text>` — one line quoting the tool's ERROR message, no other prose.
"""


class AcceptRejectDecision(BaseModel):
    """Decision on a single proposed contract markup (Sprint 9)."""

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


HEAD_OF_COMMERCIAL_SYSTEM_PROMPT = """You are the Head of Commercial in an in-house legal function. You are responsible for commercial contract work — NDAs, MSAs, SaaS agreements, procurement contracts, amendments, and similar.

Output discipline — READ THIS FIRST.
You have NO direct filesystem access, NO ability to verify file existence, and NO tools of your own beyond the `task` tool. You MUST NOT claim that a file is missing, invalid, unreadable, or does not exist — you have no way to know. File validation is the executor's job (and, underneath, Adeu's job). Your job is to route the inbound request to the right specialist(s) and relay their response.

Staffed specialists under you (subagent names to use with the `task` tool):
  - redline-planner: decomposes a requested redline transformation into a narrow JSON edit plan. Takes a transformation instruction plus the clause text and returns a plan (text). Does not touch the document.
  - redline-executor: applies a JSON edit plan to a .docx NDA via tracked changes. Takes the plan (verbatim, from the planner) plus the file path and returns a saved-output-path sentence.
  - accept-reject-reasoner: decides accept / reject / counter on a SINGLE proposed contract markup against a playbook rule. Returns a structured JSON decision.

Routing rules (follow strictly):

  1. If the inbound task asks to transform / redline / amend / rewrite / convert / change / modify a clause in a .docx NDA, you MUST run the redline sequence:
       (a) Call `task(subagent_type="redline-planner", description=<transformation instruction and clause text verbatim>)`. The planner returns a JSON plan in its reply.
       (b) Call `task(subagent_type="redline-executor", description=<plan verbatim, plus the .docx file path>)`. The executor returns "Redline saved to <path>." on success.
       (c) Relay the executor's reply back to the General Counsel.

     When you call (a), include BOTH the transformation instruction AND the verbatim clause text that the user supplied in the original task. The planner needs the clause text to plan over.

     When you call (b), the `description` you hand to `redline-executor` MUST contain the planner's plan VERBATIM — do not summarise, paraphrase, re-format, or critique. The plan is a contract between the planner and the executor; your job is to pass it through unchanged, accompanied by the file path the executor needs for its final reply. A practical shape:

       Execute the following redline plan on <nda_path>.

       <planner's full reply, verbatim including "I will make N edits." and the fenced ```json block>

     Do not decide whether the plan is good. Do not re-order. Do not extract just the JSON and drop the rest. Pass the planner's reply through whole.

  2. If the inbound task describes a single counterparty position on a clause AND a playbook rule that governs it (and does NOT ask for a document-level transformation), delegate to `accept-reject-reasoner` via the `task` tool. "Accepted unchanged" and "no change" still count as a counterparty position — delegate anyway.

  3. If neither (1) nor (2) applies, respond plainly (one or two sentences) describing what you would do. Do not attempt to perform the work yourself.

After the executor returns (rule 1) or the accept-reject-reasoner returns (rule 2), relay verbatim (or lightly paraphrased) to the General Counsel:
  * `redline-executor` replies with a short sentence naming the output .docx path. Include that path verbatim in your response to GC.
  * `accept-reject-reasoner` replies with a structured JSON decision (`decision`, `reason`, `counter_language`). State the decision, include the reason, and include `counter_language` verbatim when decision is "counter".

Do not invent information. Do not claim that a tool failed unless the specialist's response explicitly says it did."""


GC_SYSTEM_PROMPT = """You are the General Counsel of an in-house legal function. Your job is to classify inbound work and delegate to the right department head via the `task` tool.

Currently staffed department heads (subagent names you can call via `task`):
  - head-of-commercial: commercial contract work — NDAs, MSAs, SaaS agreements, procurement contracts, amendments, and any accept/reject/counter decisions on specific contract markups, including document-level transformations of .docx contracts.

Other departments (company secretarial, data protection, employment, property, litigation, and anything else) are NOT yet staffed. For those requests, respond exactly: "this department is not yet staffed". Do not delegate when no department head is staffed for the request.

When delegating to a staffed head, synthesise their response into a final reply to the user. Include any file paths the head surfaces — the user needs those to open the output. When not delegating, reply directly."""


# ---------------------------------------------------------------------------
# Agent construction — ADR 014 (three-level delegation via CompiledSubAgent)
# ---------------------------------------------------------------------------


def _build_redline_planner_spec() -> dict:
    """SubAgent spec for the planner. Model: GPT-5.4 via OpenRouter."""
    planner_model = get_chat_model(env_prefix="OSCAR_LLM_REDLINE_PLANNER")
    planner_model.callbacks = [_PlanCapture()]
    return {
        "name": "redline-planner",
        "description": (
            "Decomposes a requested redline transformation (plus the clause "
            "text it operates on) into a narrow JSON edit plan suitable for "
            "a downstream executor. Does not touch the document. Returns a "
            "plan as text — the reply contains a fenced ```json block."
        ),
        "system_prompt": REDLINE_PLANNER_PROMPT,
        "tools": [],
        "model": planner_model,
    }


def _build_redline_executor_spec(
    input_path: Path, output_path: Path, tool_call_log: Path
) -> dict:
    """SubAgent spec for the executor. Model: MiniMax-M2.7."""
    tools = make_redline_tools(input_path, output_path, tool_call_log)
    return {
        "name": "redline-executor",
        "description": (
            "Applies a JSON edit plan to a .docx NDA via tracked changes. "
            "Takes the plan (verbatim, from the planner) plus the file path "
            "and returns a short sentence naming the output .docx path when "
            "done."
        ),
        "system_prompt": redline_executor_prompt(output_path),
        "tools": tools,
        "model": get_chat_model(env_prefix="OSCAR_LLM_REDLINE_EXECUTOR"),
    }


def _build_accept_reject_spec() -> dict:
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
        "model": get_chat_model(env_prefix="OSCAR_LLM_ACCEPT_REJECT_REASONER"),
        "response_format": AcceptRejectDecision,
    }


def _build_head_of_commercial(input_path: Path, output_path: Path) -> dict:
    planner_spec = _build_redline_planner_spec()
    executor_spec = _build_redline_executor_spec(
        input_path, output_path, TOOL_CALL_LOG
    )
    accept_reject_spec = _build_accept_reject_spec()

    hoc_model = get_chat_model(env_prefix="OSCAR_LLM_HEAD_OF_COMMERCIAL")
    hoc_model.callbacks = [_HocInvocationCapture()]

    hoc_graph = create_deep_agent(
        model=hoc_model,
        tools=[],
        system_prompt=HEAD_OF_COMMERCIAL_SYSTEM_PROMPT,
        subagents=[planner_spec, executor_spec, accept_reject_spec],
    )
    return {
        "name": "head-of-commercial",
        "description": (
            "Head of Commercial. Delegates commercial contract work — NDAs, "
            "MSAs, SaaS agreements, procurement contracts, amendments, and "
            "any accept/reject/counter decisions on specific contract "
            "markups, including document-level redline transformations via "
            "a planner + executor split."
        ),
        "runnable": hoc_graph,
    }


def build_agents(
    input_path: Path = INPUT_DOCX, output_path: Path = OUTPUT_DOCX
):
    hoc_under_gc = _build_head_of_commercial(input_path, output_path)
    gc_agent = create_deep_agent(
        model=get_chat_model(env_prefix="OSCAR_LLM_GENERAL_COUNSEL"),
        tools=[],
        system_prompt=GC_SYSTEM_PROMPT,
        subagents=[hoc_under_gc],
    )
    return gc_agent


# ---------------------------------------------------------------------------
# Invocation prompts
# ---------------------------------------------------------------------------

# Primary run — user includes §9 clause text inline so the planner has
# something concrete to plan over without needing a file-read tool.

from build_input import CLAUSE_9_TEXT  # noqa: E402

INVOCATION_PROMPT = (
    f"Please convert the dispute resolution clause in the attached NDA from "
    f"litigation to binding LCIA arbitration. Keep the governing-law "
    f"sentence (England and Wales) intact; change only the "
    f"jurisdiction/dispute-resolution sentence. The arbitration provision "
    f"must name all five of: (1) seat London, (2) LCIA Rules, (3) one sole "
    f"arbitrator, (4) English language, (5) final and binding on the "
    f"parties.\n"
    f"\n"
    f"The NDA is at {INPUT_DOCX.resolve()}.\n"
    f"\n"
    f'Clause 9 ("Governing Law and Dispute Resolution") reads verbatim:\n'
    f"\n"
    f"{CLAUSE_9_TEXT}"
)

# Control run — an executor-direct invocation carrying 10E's hand-decided
# spans in the 10H plan contract. The two edits are byte-identical to the
# values Sprint 10E wrote into the specialist's system prompt's
# DECOMPOSITION block.

_CONTROL_PLAN = [
    {
        "tool": "modify_text",
        "target_text": "the exclusive jurisdiction of the courts of England and Wales",
        "new_text": "binding arbitration under the LCIA Rules",
        "reason": "Replace the forum-submission phrase with LCIA arbitration.",
    },
    {
        "tool": "insert_text",
        "anchor_text": "arising out of or in connection with this Agreement.",
        "new_text": " The seat of arbitration shall be London, England; the language English; the tribunal shall consist of a sole arbitrator; and the award shall be final and binding on the parties.",
        "reason": "Append the seat/language/arbitrator/finality sentence after the closing full stop.",
    },
]


def _control_invocation_message() -> HumanMessage:
    plan_json = json.dumps(_CONTROL_PLAN, indent=2)
    body = (
        f"Execute the following redline plan on "
        f"{CONTROL_OUTPUT_DOCX.resolve()}.\n"
        f"\n"
        f"I will make {len(_CONTROL_PLAN)} edits.\n"
        f"\n"
        f"```json\n{plan_json}\n```"
    )
    return HumanMessage(body)


# ---------------------------------------------------------------------------
# Trace helpers — unchanged from 10E
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
    return list(_TOOL_CALL_CAPTURE)


# ---------------------------------------------------------------------------
# Mechanical output verification — same four criteria as 10E (the four that
# operationalise lawyer-shape) plus the 10D file-existence / zip / XML gates
# as hard failures.
# ---------------------------------------------------------------------------

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": W_NS}


def _element_text(el) -> str:
    texts = el.xpath(".//w:t/text() | .//w:delText/text()", namespaces=_NS)
    return "".join(texts)


def _element_word_count(el) -> int:
    text = _element_text(el).strip()
    return len(text.split()) if text else 0


def verify_output(output_path: Path) -> tuple[bool, list[str]]:
    """Hard gates (file / zip / XML) + the four lawyer-shape checks.

    ``ok`` returns False only on the three hard gates. The four lawyer-shape
    checks append WARN notes but do not flip ``ok`` — interpretation feeds
    the sprint-log entry.
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

    # (1) Span widths
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
        else:
            notes.append(f"OK: w:{tag}[id={wid}] span={wc} words")

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

    # (3) Duplicate w:ins content.
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
                f"duplicate-ins failure). Content starts: {content[:80]!r}"
            )

    # (4) Litigation-text preservation spot-check.
    all_del_text = "".join(
        root.xpath(".//w:delText/text()", namespaces=_NS)
    )
    needle = "exclusive jurisdiction of the courts of England and Wales"
    if needle in all_del_text:
        notes.append(
            f"SPOT-CHECK OK: litigation phrase {needle!r} is preserved "
            f"in w:delText."
        )
    else:
        notes.append(
            f"WARN: litigation phrase {needle!r} NOT found in any "
            f"w:delText."
        )

    # Transformation-specific content spot-check (five arbitration elements).
    def _clean_view_excerpt() -> str:
        try:
            with open(output_path, "rb") as fh:
                return extract_text_from_stream(
                    io.BytesIO(fh.read()), clean_view=True
                )
        except Exception:
            return ""

    cv = _clean_view_excerpt()
    five = [
        ("seat London", "London" in cv),
        ("rules LCIA", "LCIA" in cv),
        ("sole arbitrator (one)", ("sole arbitrator" in cv) or ("one arbitrator" in cv)),
        ("language English", "English language" in cv or "in English" in cv or "the English language" in cv),
        ("final and binding", "final and binding" in cv),
    ]
    for label, found in five:
        notes.append(f"{'FOUND' if found else 'MISSING'}: {label}")

    return True, notes


# ---------------------------------------------------------------------------
# Run helpers
# ---------------------------------------------------------------------------


def _echo_env() -> None:
    for name in [
        "OSCAR_LLM_GENERAL_COUNSEL_PROVIDER",
        "OSCAR_LLM_GENERAL_COUNSEL_MODEL",
        "OSCAR_LLM_HEAD_OF_COMMERCIAL_PROVIDER",
        "OSCAR_LLM_HEAD_OF_COMMERCIAL_MODEL",
        "OSCAR_LLM_REDLINE_PLANNER_PROVIDER",
        "OSCAR_LLM_REDLINE_PLANNER_MODEL",
        "OSCAR_LLM_REDLINE_EXECUTOR_PROVIDER",
        "OSCAR_LLM_REDLINE_EXECUTOR_MODEL",
        "OSCAR_LLM_ACCEPT_REJECT_REASONER_PROVIDER",
        "OSCAR_LLM_ACCEPT_REJECT_REASONER_MODEL",
    ]:
        print(f"{name:50s} = {os.environ.get(name)!r}")


def _reset_capture_and_logs() -> None:
    _TOOL_CALL_CAPTURE.clear()
    _PLAN_CAPTURE.clear()
    _HOC_INVOCATION_CAPTURE.clear()
    for p in (TOOL_CALL_LOG, PLAN_LOG, HOC_INVOCATION_LOG, CONTROL_TOOL_CALL_LOG):
        if p.exists():
            p.unlink()


def _print_tool_calls(label: str, calls: list[dict]) -> None:
    print(f"\n--- {label} (verbatim) ---")
    if not calls:
        print("  (none)")
        return
    for i, call in enumerate(calls, 1):
        print(f"  CALL {i}: {call['name']}(")
        for k, v in call["args"].items():
            print(f"    {k}={v!r},")
        print("  )")


def _print_plan(plan_texts: list[str]) -> None:
    print("\n--- PLANNER'S PLAN (verbatim, all non-empty AIMessage.content) ---")
    if not plan_texts:
        print("  (none)")
        return
    for i, text in enumerate(plan_texts, 1):
        print(f"  [planner message {i}]")
        for line in text.splitlines():
            print(f"    {line}")


def _print_hoc_invocations(entries: list[dict]) -> None:
    print("\n--- HOC INVOCATIONS OF redline-executor (verbatim descriptions) ---")
    if not entries:
        print("  (none — HOC did not call redline-executor)")
        return
    for i, entry in enumerate(entries, 1):
        print(f"  [invocation {i}] subagent_type={entry['subagent_type']!r}")
        for line in entry["description"].splitlines():
            print(f"    {line}")


def _run_primary() -> tuple[bool, list[str]]:
    """Primary Shape A run — GC → HOC → planner → HOC → executor → HOC → GC."""
    gc_agent = build_agents(INPUT_DOCX, OUTPUT_DOCX)

    print("=" * 72)
    print("PRIMARY INVOCATION")
    print("=" * 72)
    print(f"PROMPT:\n{INVOCATION_PROMPT}")
    print("=" * 72)

    result = gc_agent.invoke({"messages": [HumanMessage(INVOCATION_PROMPT)]})

    trace_lines: list[str] = []
    print("\n--- GC MESSAGE TRACE ---")
    for i, msg in enumerate(result["messages"], 1):
        line = f"  {i:2}. {_summary(msg)}"
        print(line)
        trace_lines.append(line)

    subagent_names = _gc_task_subagent_names(result["messages"])
    print("\n--- GC task() subagent_types ---")
    for n in subagent_names:
        print(f"  {n}")

    final = _final_text(result["messages"])
    print("\n--- FINAL RESPONSE (GC → user) ---")
    print(final)

    _print_plan(_PLAN_CAPTURE)
    _print_hoc_invocations(_HOC_INVOCATION_CAPTURE)
    _print_tool_calls(
        "EXECUTOR TOOL CALLS", get_recorded_tool_calls()
    )

    print("\n--- MECHANICAL VERIFICATION ---")
    ok, notes = verify_output(OUTPUT_DOCX)
    for n in notes:
        print(f"  {n}")

    print("\n--- CLEAN-VIEW READ-BACK (simulated Accept-All), §9 excerpt ---")
    try:
        with open(OUTPUT_DOCX, "rb") as f:
            clean_view = extract_text_from_stream(
                io.BytesIO(f.read()), clean_view=True
            )
        idx = clean_view.find("9. Governing Law")
        if idx < 0:
            idx = clean_view.find("England and Wales")
            excerpt = clean_view[max(0, idx - 200) : idx + 1000] if idx >= 0 else clean_view[:1500]
        else:
            excerpt = clean_view[idx : idx + 1200]
        for line in excerpt.splitlines():
            print(f"  {line}")
    except Exception as exc:
        print(f"  <clean-view extraction failed: {exc}>")

    with open(TRANSCRIPT, "w") as f:
        f.write("=" * 72 + "\n")
        f.write("Sprint 10H PRIMARY — transcript\n")
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
        f.write("\n--- PLANNER'S PLAN (verbatim) ---\n")
        for i, text in enumerate(_PLAN_CAPTURE, 1):
            f.write(f"[planner message {i}]\n{text}\n\n")
        f.write("--- HOC INVOCATIONS OF redline-executor (verbatim) ---\n")
        for i, entry in enumerate(_HOC_INVOCATION_CAPTURE, 1):
            f.write(f"[invocation {i}]\n{entry['description']}\n\n")
        f.write("--- EXECUTOR TOOL CALLS (verbatim) ---\n")
        calls = get_recorded_tool_calls()
        if not calls:
            f.write("  (none)\n")
        else:
            for i, call in enumerate(calls, 1):
                f.write(f"  CALL {i}: {call['name']}(\n")
                for k, v in call["args"].items():
                    f.write(f"    {k}={v!r},\n")
                f.write("  )\n")
        f.write("\n--- MECHANICAL VERIFICATION ---\n")
        for n in notes:
            f.write(f"  {n}\n")

    print(f"\ntranscript written to {TRANSCRIPT}")
    return ok, notes


def _run_control() -> tuple[bool, list[str]]:
    """Control — executor alone, handed 10E's spans as a 10H plan."""
    _TOOL_CALL_CAPTURE.clear()

    executor_spec = _build_redline_executor_spec(
        INPUT_DOCX, CONTROL_OUTPUT_DOCX, CONTROL_TOOL_CALL_LOG
    )
    executor_graph = create_deep_agent(
        model=executor_spec["model"],
        tools=executor_spec["tools"],
        system_prompt=executor_spec["system_prompt"],
    )

    inv = _control_invocation_message()
    print("=" * 72)
    print("CONTROL INVOCATION")
    print("=" * 72)
    print(f"PROMPT (plan handed to executor, HumanMessage):\n{inv.content}")
    print("=" * 72)

    result = executor_graph.invoke({"messages": [inv]})

    trace_lines: list[str] = []
    print("\n--- EXECUTOR MESSAGE TRACE ---")
    for i, msg in enumerate(result["messages"], 1):
        line = f"  {i:2}. {_summary(msg)}"
        print(line)
        trace_lines.append(line)

    final = _final_text(result["messages"])
    print("\n--- FINAL RESPONSE (executor → user) ---")
    print(final)

    _print_tool_calls(
        "CONTROL EXECUTOR TOOL CALLS", get_recorded_tool_calls()
    )

    print("\n--- MECHANICAL VERIFICATION (control) ---")
    ok, notes = verify_output(CONTROL_OUTPUT_DOCX)
    for n in notes:
        print(f"  {n}")

    with open(CONTROL_TRANSCRIPT, "w") as f:
        f.write("=" * 72 + "\n")
        f.write("Sprint 10H CONTROL — transcript\n")
        f.write("=" * 72 + "\n\n")
        f.write(f"INVOCATION:\n{inv.content}\n\n")
        f.write("--- EXECUTOR MESSAGE TRACE ---\n")
        for line in trace_lines:
            f.write(line + "\n")
        f.write("\n--- FINAL RESPONSE (executor → user) ---\n")
        f.write(final + "\n")
        f.write("\n--- EXECUTOR TOOL CALLS (verbatim) ---\n")
        calls = get_recorded_tool_calls()
        if not calls:
            f.write("  (none)\n")
        else:
            for i, call in enumerate(calls, 1):
                f.write(f"  CALL {i}: {call['name']}(\n")
                for k, v in call["args"].items():
                    f.write(f"    {k}={v!r},\n")
                f.write("  )\n")
        f.write("\n--- MECHANICAL VERIFICATION ---\n")
        for n in notes:
            f.write(f"  {n}\n")

    print(f"\ntranscript written to {CONTROL_TRANSCRIPT}")
    return ok, notes


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    _echo_env()
    print()

    if not INPUT_DOCX.exists():
        from build_input import build_document

        build_document()
        print(f"generated {INPUT_DOCX}")

    _reset_capture_and_logs()

    primary_ok, primary_notes = _run_primary()

    print("\n" + "#" * 72)
    print("# CONTROL RUN — executor alone, handed 10E's spans in 10H plan format")
    print("#" * 72 + "\n")

    control_ok, control_notes = _run_control()

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"primary mechanical-gates ok: {primary_ok}")
    print(f"control mechanical-gates ok: {control_ok}")

    if not primary_ok:
        raise AssertionError(
            "Primary run failed mechanical gates — see notes above."
        )
    if not control_ok:
        raise AssertionError(
            "Control run failed mechanical gates — see notes above."
        )

    print(
        "\nsprint-10h: primary + control runs completed (hard gates).\n"
        "Lawyer-shape judgement from WARN/OK lines feeds the sprint-log "
        "entry; outcome classification (A / B / C) is separate."
    )


if __name__ == "__main__":
    main()
