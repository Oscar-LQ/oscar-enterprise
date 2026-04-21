"""Sprint 10I — Sonnet reference run (sub-experiment of 10I).

Same Deep Agents setup as ``../run.py``: same EXECUTIONER_SYSTEM_PROMPT,
same INVOCATION_PROMPT wording, same make_redline_tools, same
create_deep_agent call shape, same subagents=[], same NDA. Only the
model is swapped — Sonnet via OpenRouter (env prefix
``OSCAR_LLM_REDLINE_EXECUTOR_SONNET``).

Purpose: disentangle model-level vs framework-level failure mode. 10I's
MiniMax run stopped at framework filesystem-tool verification before
any decomposition (read_file → ls → glob → "file not found"). Is that
a Deep Agents framework issue any model would trip on, or is it
MiniMax-specific instruction-following fragility a frontier model would
ignore? One invocation, one attempt; whatever shape the output takes
is the data point.

Artefacts: ``nda-input.docx``, ``nda-output.docx``, ``transcript.txt``,
``tool-calls.jsonl`` in this directory (sonnet-reference/).
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

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, tool

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

_TOOL_CALL_CAPTURE: list[dict] = []


# ---------------------------------------------------------------------------
# Tool factory — reused verbatim from Sprint 10E (ADR 017, 018)
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


def make_redline_tools(input_path: Path, output_path: Path) -> list[BaseTool]:
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
# Executioner system prompt
# ---------------------------------------------------------------------------


def executioner_system_prompt(output_path: Path) -> str:
    """System prompt for the clause-9 executioner.

    Derived from Sprint 10E's disciplinary spine — OUTPUT DISCIPLINE, NO-RETRY,
    SURGICAL-SPAN, RULES FOR TARGET/ANCHOR, final-reply template — with
    10E's "DECOMPOSITION FOR THIS TRANSFORMATION" (which handed exact
    target_text/new_text values) replaced by executioner framing: scope
    fixed to Clause 9, pre-decided goal, count-and-shape decomposition
    guidance only. Deliberately omits 10G's "PLAN BEFORE YOU ACT" scaffolding
    (falsified) and 10E's worked RIGHT example (would hand-wire spans).

    The §9 current text is embedded verbatim under "THE INSTRUCTION"
    because Adeu's tool surface has no read primitive — the executioner
    needs exact-match strings to target.
    """
    return f"""You are the clause-9 executioner on an NDA redline. A planner (separate agent, not you) has already decided that Clause 9 of this NDA must change from court litigation (exclusive jurisdiction of the courts of England and Wales) to LCIA arbitration, with these five elements: (1) seat London, (2) LCIA Rules, (3) a sole arbitrator, (4) English language, (5) final and binding.

THE DECISION IS MADE.
You are NOT deciding whether to make this change — that decision is already taken. You are NOT reasoning about which clause to touch, or about the document's overall structure. Your scope is Clause 9 only; do not edit any other clause and do not propose any other changes. Your job is to work out the narrow edits that realise the planner's decision and to apply them via the tools.

THE INSTRUCTION.
Clause 9 of the on-disk NDA currently reads (verbatim): "This Agreement and any dispute or claim arising out of or in connection with it or its subject matter or formation (including non-contractual disputes or claims) shall be governed by and construed in accordance with the laws of England and Wales. The parties submit to the exclusive jurisdiction of the courts of England and Wales for the resolution of all disputes arising out of or in connection with this Agreement." Leave the governing-law sentence (first sentence, ending "...laws of England and Wales.") intact. Change the dispute-resolution sentence (second sentence) so that disputes are resolved by binding LCIA arbitration, with the five elements above.

OUTPUT DISCIPLINE — READ THIS FIRST.
Your ONLY way to change the document is by calling ``modify_text`` or ``insert_text``. You do NOT hand-edit OOXML. You do NOT produce the final .docx yourself. When you are finished, reply with ONE sentence naming the output path exactly as given below — no extra prose.
The output file is: ``{output_path}``. After your final planned edit returns ``applied: edits_applied=1 edits_skipped=0``, reply exactly with: "Redline saved to {output_path}."

NO-RETRY RULE.
After each tool call, READ the return value. If it begins with ``applied: edits_applied=1 edits_skipped=0``, that edit is DONE. Do NOT call modify_text or insert_text on the same or overlapping text again. Do NOT "improve" or "re-verify" a successful edit. Re-targeting a region you already edited will nest a new redline inside your previous one, clear the original text from the audit trail, and produce a broken redline. Move on to the next planned call or stop.

DECOMPOSITION DISCIPLINE.
A complete target for this transformation takes 2-4 narrow edits: one ``modify_text`` to replace the forum-submission phrase ("the exclusive jurisdiction of the courts of England and Wales") with arbitration-rules language, plus one or more narrow ``insert_text`` calls to add the remaining arbitration-machinery elements (seat, language, arbitrator, finality) after the dispute-resolution sentence's closing punctuation. Do NOT bundle all five elements into one wide ``modify_text`` — that produces a 30+ word w:ins / 30+ word w:del pair with no shared prefix/suffix and no audit-trail narrowing. Do NOT fragment down to word-by-word edits. 2-4 compositional edits is the target.

SURGICAL-SPAN RULE — CORE DISCIPLINE.
Your ``target_text`` is a locator for the smallest slice of the document that actually changes. Target 5-15 words, only the phrase that differs, plus just enough anchor context for a unique match. Never use a whole sentence or paragraph as target_text when only part of it differs. Never rewrite what you are not changing.

RULES FOR TARGET / ANCHOR TEXT (apply to both tools).
  * MUST match the document exactly — case, punctuation, whitespace.
  * MUST match exactly one span. Zero or multiple matches return ERROR; read it, adjust the target once, retry.
  * Do NOT include CriticMarkup markers ({{--...--}}, {{++...++}}) in either field.
  * Do NOT use markdown bold (**) or italic (_) in new_text.
  * Do NOT pass ``comment`` on a pure deletion (new_text=""); Adeu drops it.

OPERATING DISCIPLINE.
You have no filesystem access of your own. Modifying the document happens ONLY through ``modify_text`` and ``insert_text``. Do NOT claim the file is missing, unreadable, or does not exist — you have no way to know. You do not delegate this work to a sub-agent. You perform the edits yourself by calling modify_text and insert_text directly. If a tool call returns ERROR, read the message and adjust the target ONCE, then retry. If it errors again, STOP and report the error in your final reply instead of the "Redline saved to..." line.

TOOL CONTRACT.
  * ``modify_text(target_text, new_text)`` — replaces an existing phrase (``target_text``) with ``new_text``. Deletion uses ``new_text=""``.
  * ``insert_text(anchor_text, new_text)`` — inserts ``new_text`` immediately AFTER ``anchor_text``. Pick an anchor ending in punctuation (e.g. a full stop) for clean boundaries. Use the shortest anchor that is still unique in the document.

Begin.
"""


# ---------------------------------------------------------------------------
# Invocation prompt (kickoff HumanMessage — minimal, per sprint brief)
# ---------------------------------------------------------------------------

INVOCATION_PROMPT = (
    f"Your clause-9 executioner task on {INPUT_DOCX.resolve()} is ready. "
    f"Execute the edits on §9 per your instructions."
)


# ---------------------------------------------------------------------------
# Agent construction — single agent, no GC/HOC/subagents
# ---------------------------------------------------------------------------


def build_agent(input_path: Path = INPUT_DOCX, output_path: Path = OUTPUT_DOCX):
    """Build the single clause-9 executioner agent bound to the given paths.

    Direct invocation shape: one ``create_deep_agent`` call with the redline
    tools, the executioner prompt, and no sub-agents declared. Deep Agents'
    ``SubAgentMiddleware`` still injects the ``task`` tool and a latent
    ``general-purpose`` sub-agent — OPERATING DISCIPLINE tells the model
    not to delegate.
    """
    tools = make_redline_tools(input_path, output_path)
    return create_deep_agent(
        model=get_chat_model(env_prefix="OSCAR_LLM_REDLINE_EXECUTOR_SONNET"),
        tools=tools,
        system_prompt=executioner_system_prompt(output_path),
        subagents=[],
    )


# ---------------------------------------------------------------------------
# Trace helpers (borrowed from Sprint 10E; _gc_task_subagent_names dropped)
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


def get_recorded_tool_calls() -> list[dict]:
    return list(_TOOL_CALL_CAPTURE)


# ---------------------------------------------------------------------------
# Mechanical output verification — reused verbatim from Sprint 10E
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
    """Three mechanical checks + four Sprint 10E lawyer-shape warnings.

    Copied verbatim from sprint-10e/run.py. The ``ok`` return reflects only
    the three mechanical checks (file exists, valid zip, parseable
    document.xml). Four warnings are diagnostic — appended to ``notes`` with
    ``WARN:`` prefix, never flip ``ok``.

    Warnings:
      (1) span widths — >20 words SUSPICIOUS, >50 words ALMOST CERTAINLY wrong
      (2) empty w:delText nested-delete signature (10D failure)
      (3) duplicate w:ins content (>10 words, ≥2 copies) (10D failure)
      (4) litigation phrase preserved somewhere in w:delText (audit-trail
          spot-check)
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
# Entrypoint
# ---------------------------------------------------------------------------


def _echo_env() -> None:
    for name in [
        "OSCAR_LLM_REDLINE_EXECUTOR_SONNET_PROVIDER",
        "OSCAR_LLM_REDLINE_EXECUTOR_SONNET_MODEL",
    ]:
        print(f"{name:52s} = {os.environ.get(name)!r}")


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

    system_prompt_text = executioner_system_prompt(OUTPUT_DOCX)
    agent = build_agent(INPUT_DOCX, OUTPUT_DOCX)

    print("=" * 72)
    print("EXECUTIONER SYSTEM PROMPT")
    print("=" * 72)
    print(system_prompt_text)
    print("=" * 72)
    print("INVOCATION")
    print(f"PROMPT:\n{INVOCATION_PROMPT}")
    print("=" * 72)

    result = agent.invoke({"messages": [HumanMessage(INVOCATION_PROMPT)]})

    print("\n--- MESSAGE TRACE ---")
    trace_lines = []
    for i, msg in enumerate(result["messages"], 1):
        line = f"  {i:2}. {_summary(msg)}"
        print(line)
        trace_lines.append(line)

    final = _final_text(result["messages"])
    print("\n--- FINAL RESPONSE ---")
    print(final)

    specialist_calls = get_recorded_tool_calls()
    print("\n--- SPECIALIST TOOL CALLS (VERBATIM) ---")
    if not specialist_calls:
        print("  (none — executioner made no modify_text/insert_text calls)")
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
        clean_view_excerpt = f"<clean-view extraction failed: {exc}>"
        print(f"  {clean_view_excerpt}")

    with open(TRANSCRIPT, "w") as f:
        f.write("=" * 72 + "\n")
        f.write("Sprint 10I — transcript\n")
        f.write("=" * 72 + "\n\n")
        f.write("EXECUTIONER SYSTEM PROMPT (verbatim):\n")
        f.write("-" * 72 + "\n")
        f.write(system_prompt_text)
        f.write("-" * 72 + "\n\n")
        f.write(f"INVOCATION PROMPT (verbatim):\n{INVOCATION_PROMPT}\n\n")
        f.write("--- MESSAGE TRACE ---\n")
        for line in trace_lines:
            f.write(line + "\n")
        f.write("\n--- FINAL RESPONSE ---\n")
        f.write(final + "\n")
        f.write("\n--- SPECIALIST TOOL CALLS (VERBATIM) ---\n")
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
        f.write("\n--- CLEAN-VIEW §9 READ-BACK (simulated Accept-All) ---\n")
        for line in clean_view_excerpt.splitlines():
            f.write(f"  {line}\n")
    print(f"\ntranscript written to {TRANSCRIPT}")

    print()
    if not ok:
        raise AssertionError(
            "Sprint 10I verification failed — see notes above. Output file "
            "either missing, not a valid zip, or word/document.xml did not "
            "parse."
        )
    print("sprint-10i: single-agent executioner run completed (mechanical checks).")
    print(
        f"\nOutput for human review: {OUTPUT_DOCX}\n"
        f"Shape assessment lives in the SPECIALIST TOOL CALLS section and "
        f"the WARN lines of MECHANICAL VERIFICATION."
    )


if __name__ == "__main__":
    main()
