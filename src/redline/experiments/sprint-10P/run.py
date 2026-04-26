"""Sprint 10P — driver for the counterparty-response pipeline.

End-to-end:
    1. Load nda-input-minimal.docx (cut-down 3-change Zenith fixture)
       and nda-original.docx (clean Acme draft, pre-Zenith) — both
       prepared by build_input.py.
    2. pipeline.extract_state_of_play(nda-input-minimal.docx)
       → StateOfPlay (Zenith's tracked changes structured per-change)
    3. doc_analyser.build_context_header(nda-original.docx) +
       Adeu clean-view extraction → contract_text for the planner
    4. Build planner system + user prompts
    5. Invoke the planner (GPT-5.5 non-Pro) via OSCAR_LLM_REDLINE_PLANNER_*
    6. Parse decisions via response_parser.parse_decisions_response
    7. Per counter_propose decision: build executor user prompt, invoke
       MiniMax via OSCAR_LLM_REDLINE_EXECUTOR_*, parse via
       parse_single_edit_response. Mechanical decisions (accept,
       no_action, comment, reply) skip the executor.
    8. pipeline.apply_decisions: applies all decisions on a single
       in-memory Document via Adeu native (accept/reply) + ported
       counter_propose and add_comment helpers; saves nda-output-minimal.docx
    9. verify_output: mechanical layer (valid zip, OOXML parses, two
       authors visible, per-decision shape sanity)
    10. Append transcript

One Phase 2.3 run. Mechanical fixes only. No prompt iteration.

Usage:
    python src/redline/experiments/sprint-10P/run.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path

import structlog
from dotenv import load_dotenv

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

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HERE))

load_dotenv(REPO_ROOT / ".env")

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

from src.shared.llm.chat_model import get_chat_model  # noqa: E402
from src.shared.llm.metadata_capture import capture_reply_metadata  # noqa: E402

from src.redline.lib.author_config import AuthorConfig  # noqa: E402

import pipeline  # noqa: E402
from prompt_builder import (  # noqa: E402
    build_executor_user_prompt,
    build_planner_user_prompt,
    load_executor_system_prompt,
    load_planner_system_prompt,
)
from response_parser import (  # noqa: E402
    parse_decisions_response,
    parse_single_edit_response,
)


# --- contract-text extraction -------------------------------------------
#
# The planner reads the original (clean, pre-Zenith) NDA for cross-
# reference. We extract the clean text via Adeu's standard ingest path
# without going through the inline-pipeline's 10O-style PlainTextIndex
# layer (that's a first-pass-redline concern). The doc_analyser header
# adds structural context (numbering, styles) that helps the planner
# reference clauses correctly.

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": W_NS}


def _extract_clean_contract_text(docx_bytes: bytes) -> str:
    """Extract clean accepted-view text from the original NDA bytes.

    Uses Adeu's ingest helpers + doc_analyser header as in 10O. The
    clean_view=True flag asks Adeu to emit the accepted-all view (no
    tracked-change markers); since the original NDA has no tracked
    changes, this is equivalent to plain text extraction.
    """
    from adeu.ingest import _extract_blocks
    from adeu.redline.comments import CommentsManager
    from adeu.redline.engine import RedlineEngine
    from adeu.utils.docx import iter_document_parts

    stream = BytesIO(docx_bytes)
    try:
        engine = RedlineEngine(stream, author="Acme Counsel")
    finally:
        stream.close()

    comments_mgr = CommentsManager(engine.doc)
    comments_map = comments_mgr.extract_comments_data()

    parts_text = []
    for part in iter_document_parts(engine.doc):
        block_text = _extract_blocks(part, comments_map, clean_view=True)
        if block_text:
            parts_text.append(block_text)

    extracted = "\n\n".join(parts_text)

    # doc_analyser header (10O pattern). Best-effort.
    try:
        from doc_analyser import build_context_header
        header = build_context_header(bytes(docx_bytes))
        return header + "\n\n---\n\nCONTRACT TEXT:\n\n" + extracted
    except Exception as exc:  # noqa: BLE001 — non-fatal
        print(f"[10P] doc_analyser failed (non-fatal): {exc}")
        return extracted


# --- verify_output (10O pattern, adapted for two-author counterparty
# response) ------------------------------------------------------------


def _element_text(el) -> str:
    texts = el.xpath(".//w:t/text() | .//w:delText/text()", namespaces=_NS)
    return "".join(texts)


def _element_word_count(el) -> int:
    text = _element_text(el).strip()
    return len(text.split()) if text else 0


def verify_output(output_path: Path) -> tuple[bool, list[str]]:
    """Mechanical checks + two-author / per-decision shape diagnostics."""
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

    # Per-author breakdown — load-bearing for two-author rule (rule 2).
    author_ins = Counter()
    author_del = Counter()
    for el in ins_elements:
        a = el.get(f"{{{W_NS}}}author") or "(unknown)"
        author_ins[a] += 1
    for el in del_elements:
        a = el.get(f"{{{W_NS}}}author") or "(unknown)"
        author_del[a] += 1
    for a, n in author_ins.most_common():
        notes.append(f"  w:ins by author={a!r}: {n}")
    for a, n in author_del.most_common():
        notes.append(f"  w:del by author={a!r}: {n}")

    distinct_authors = set(author_ins) | set(author_del)
    if len(distinct_authors) >= 2:
        notes.append(f"TWO-AUTHOR OK: {sorted(distinct_authors)}")
    else:
        notes.append(
            f"WARN: only {len(distinct_authors)} author(s) visible "
            f"({sorted(distinct_authors)}) — rule 2 requires multi-author"
        )

    # Comments — count w:commentReference + w:commentRangeStart in body.
    comment_refs = root.findall(".//w:commentReference", _NS)
    comment_ranges = root.findall(".//w:commentRangeStart", _NS)
    notes.append(
        f"comments: w:commentReference={len(comment_refs)}, "
        f"w:commentRangeStart={len(comment_ranges)}"
    )

    # Span-shape sanity.
    for el in ins_elements + del_elements:
        tag = etree.QName(el.tag).localname
        wid = el.get(f"{{{W_NS}}}id", "?")
        wc = _element_word_count(el)
        if wc > 50:
            notes.append(f"INFO: w:{tag}[id={wid}] span={wc} words (>50)")
        elif wc > 20:
            notes.append(f"INFO: w:{tag}[id={wid}] span={wc} words (>20)")

    return True, notes


# --- helpers ------------------------------------------------------------


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(f"[10P] wrote {path.name} ({len(text)} chars)")


def _append_transcript(transcript: Path, text: str) -> None:
    with transcript.open("a", encoding="utf-8") as f:
        f.write(text)
        f.write("\n")


def _state_to_jsonable(state) -> dict:
    """Convert StateOfPlay to a plain dict for JSON serialisation."""
    return json.loads(state.model_dump_json())


# --- run ----------------------------------------------------------------


def run_once() -> int:
    t0 = datetime.now(timezone.utc)
    p_provider = os.environ.get("OSCAR_LLM_REDLINE_PLANNER_PROVIDER", "<unset>")
    p_model = os.environ.get("OSCAR_LLM_REDLINE_PLANNER_MODEL", "<unset>")
    e_provider = os.environ.get("OSCAR_LLM_REDLINE_EXECUTOR_PROVIDER", "<unset>")
    e_model = os.environ.get("OSCAR_LLM_REDLINE_EXECUTOR_MODEL", "<unset>")
    print(
        f"[10P] planner={p_provider}/{p_model} | executor={e_provider}/{e_model} | "
        f"started={t0.isoformat()}"
    )

    transcript = HERE / "transcript.txt"
    _append_transcript(
        transcript,
        f"\n=== Sprint 10P Phase 2.3 | planner={p_provider}/{p_model} | "
        f"executor={e_provider}/{e_model} | started {t0.isoformat()} ===",
    )

    # 1. Inputs.
    full_run = "--full" in sys.argv
    cache_run = "--cache" in sys.argv  # reuse cached LLM output if present
    nda_input = HERE / ("nda-input-full.docx" if full_run else "nda-input-minimal.docx")
    nda_original = HERE / "nda-original.docx"
    nda_output = HERE / ("nda-output.docx" if full_run else "nda-output-minimal.docx")
    if not nda_input.exists():
        print(f"[10P] missing input: {nda_input}", file=sys.stderr)
        print("[10P] run build_input.py first to assemble the cut-down fixture.", file=sys.stderr)
        return 2
    if not nda_original.exists():
        print(f"[10P] missing original NDA: {nda_original}", file=sys.stderr)
        return 2
    print(f"[10P] nda-input-minimal.docx = {nda_input.stat().st_size} bytes")
    print(f"[10P] nda-original.docx     = {nda_original.stat().st_size} bytes")

    # 2. State of play from Zenith's tracked .docx.
    state = pipeline.extract_state_of_play(nda_input)
    state_jsonable = _state_to_jsonable(state)
    _write(
        HERE / "state-of-play.json",
        json.dumps(state_jsonable, ensure_ascii=False, indent=2),
    )
    print(f"[10P] state-of-play: {len(state.changes)} changes, {len(state.authors)} authors")

    # 3. Clean original NDA text for the planner (cross-reference).
    original_bytes = nda_original.read_bytes()
    contract_text = _extract_clean_contract_text(original_bytes)
    print(f"[10P] original NDA clean text = {len(contract_text)} chars (with header)")

    # 4. Planner prompts.
    planner_system = load_planner_system_prompt()
    planner_user = build_planner_user_prompt(state, contract_text)
    _write(
        HERE / "llm-input-planner.txt",
        f"=== SYSTEM (len={len(planner_system)}) ===\n{planner_system}\n\n"
        f"=== USER (len={len(planner_user)}) ===\n{planner_user}\n",
    )

    # 5. Invoke planner.
    planner_output_path = HERE / "llm-output-planner.txt"
    if cache_run and planner_output_path.exists():
        p_raw = planner_output_path.read_text(encoding="utf-8")
        print(f"[10P] CACHE: loaded planner output ({len(p_raw)} chars)")
    else:
        planner_chat = get_chat_model(env_prefix="OSCAR_LLM_REDLINE_PLANNER")
        print(f"[10P] invoking planner {p_provider}/{p_model} ...")
        p_reply = planner_chat.invoke(
            [SystemMessage(content=planner_system), HumanMessage(content=planner_user)]
        )
        capture_reply_metadata(p_reply, HERE / "llm-meta-planner.json")
        p_raw = p_reply.content if hasattr(p_reply, "content") else str(p_reply)
        if not isinstance(p_raw, str):
            p_raw = json.dumps(p_raw, ensure_ascii=False)
        _write(planner_output_path, p_raw)
        print(f"[10P] planner reply = {len(p_raw)} chars")

    # 6. Parse decisions.
    try:
        parsed = parse_decisions_response(p_raw)
    except ValueError as exc:
        print(f"[10P] PLANNER PARSE FAILED: {exc}")
        _append_transcript(transcript, f"PLANNER PARSE FAILED: {exc}\n")
        return 2

    decisions = parsed["decisions"]
    cross_clause_notes = parsed["cross_clause_notes"]
    plan_method = parsed["parse_method"]
    action_counts = Counter(d["action"] for d in decisions)
    print(
        f"[10P] decisions: parse_method={plan_method} | total={len(decisions)} "
        f"| {dict(action_counts)} | cross_clause_notes={len(cross_clause_notes)}"
    )
    _write(
        HERE / "parsed-plan.json",
        json.dumps(
            {
                "decisions": decisions,
                "cross_clause_notes": cross_clause_notes,
                "parse_method": plan_method,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )

    if not decisions:
        print("[10P] empty decision list — nothing to apply (Outcome C)")
        _append_transcript(transcript, "Empty decision list — Outcome C\n")
        return 1

    # 7. Build executor callback. One LLM call per counter_propose
    # decision. Mechanical decisions skip the LLM.
    executor_system = load_executor_system_prompt()
    executor_chat = get_chat_model(env_prefix="OSCAR_LLM_REDLINE_EXECUTOR")
    counter_idx = {"n": 0}  # mutable counter for closure

    def executor_callback(decision, state_entry):
        counter_idx["n"] += 1
        n = counter_idx["n"]
        cid = decision.get("change_id", "?")
        cid_safe = cid.replace(":", "_")
        executor_output_path = HERE / f"llm-output-executor-{n:02d}-{cid_safe}.txt"
        if cache_run and executor_output_path.exists():
            e_raw = executor_output_path.read_text(encoding="utf-8")
            print(f"[10P] CACHE: loaded executor output for {cid} ({len(e_raw)} chars)")
            return parse_single_edit_response(e_raw)
        # Convert state_entry (Pydantic) to dict for prompt_builder.
        entry_dict = json.loads(state_entry.model_dump_json())
        executor_user = build_executor_user_prompt(decision, entry_dict)
        _write(
            HERE / f"llm-input-executor-{n:02d}-{cid_safe}.txt",
            f"=== SYSTEM (len={len(executor_system)}) ===\n{executor_system}\n\n"
            f"=== USER (len={len(executor_user)}) ===\n{executor_user}\n",
        )
        print(f"[10P] invoking executor for {cid} (counter-propose call {n}) ...")
        e_reply = executor_chat.invoke(
            [SystemMessage(content=executor_system), HumanMessage(content=executor_user)]
        )
        capture_reply_metadata(e_reply, HERE / f"llm-meta-executor-{n:02d}-{cid_safe}.json")
        e_raw = e_reply.content if hasattr(e_reply, "content") else str(e_reply)
        if not isinstance(e_raw, str):
            e_raw = json.dumps(e_raw, ensure_ascii=False)
        _write(executor_output_path, e_raw)
        return parse_single_edit_response(e_raw)

    # 8. Apply decisions. Author = "Acme Counsel" — rule 2.
    author_config = AuthorConfig(name="Acme Counsel", date_override=date(2026, 4, 26))
    apply_result = pipeline.apply_decisions(
        input_path=nda_input,
        output_path=nda_output,
        state=state,
        decisions=decisions,
        author_config=author_config,
        executor_callback=executor_callback,
    )

    print(f"[10P] applied:")
    print(f"  accepts:      {apply_result.accepts_applied} applied / {apply_result.accepts_skipped} skipped")
    print(f"  replies:      {apply_result.replies_applied} applied / {apply_result.replies_skipped} skipped")
    print(f"  counters:     {sum(1 for o in apply_result.counter_proposes if o.status == 'success')} applied / "
          f"{sum(1 for o in apply_result.counter_proposes if o.status != 'success')} skipped")
    print(f"  comments:     {sum(1 for o in apply_result.add_comments if o.status == 'success')} applied / "
          f"{sum(1 for o in apply_result.add_comments if o.status != 'success')} skipped")
    print(f"  no_actions:   {len(apply_result.no_actions)}")
    print(f"  decisions_skipped: {len(apply_result.decisions_skipped)}")

    # 8b. Persist a parsed-edits.json analogue summarising what was applied.
    audit_trail = {
        "accepts_applied": apply_result.accepts_applied,
        "accepts_skipped": apply_result.accepts_skipped,
        "replies_applied": apply_result.replies_applied,
        "replies_skipped": apply_result.replies_skipped,
        "counter_proposes": [
            {
                "target_id": o.target_id,
                "status": o.status,
                "method": o.method,
                "reason": o.reason,
                "original_text": o.original_text,
                "new_text": o.new_text,
            }
            for o in apply_result.counter_proposes
        ],
        "add_comments": [
            {
                "target_id": o.target_id,
                "status": o.status,
                "reason": o.reason,
                "comment_text": o.new_text,
            }
            for o in apply_result.add_comments
        ],
        "no_actions": apply_result.no_actions,
        "decisions_skipped": apply_result.decisions_skipped,
        "process_batch_skipped_details": apply_result.process_batch_skipped_details,
    }
    _write(HERE / "parsed-edits.json", json.dumps(audit_trail, ensure_ascii=False, indent=2))

    # 9. Verify.
    print(f"[10P] nda-output-minimal.docx = {nda_output.stat().st_size} bytes")
    ok, notes = verify_output(nda_output)
    print(f"[10P] verify_output ok={ok}")
    for line in notes:
        print(f"  {line}")

    # 10. Transcript.
    t1 = datetime.now(timezone.utc)
    elapsed = (t1 - t0).total_seconds()
    _append_transcript(
        transcript,
        "\n".join(
            [
                f"planner={p_provider}/{p_model} | executor={e_provider}/{e_model}",
                f"state-of-play: {len(state.changes)} changes, {len(state.authors)} authors",
                f"decisions: parse_method={plan_method} | total={len(decisions)} | {dict(action_counts)}",
                f"cross_clause_notes_count: {len(cross_clause_notes)}",
                f"applied: accepts={apply_result.accepts_applied}/{apply_result.accepts_skipped}, "
                f"counters={sum(1 for o in apply_result.counter_proposes if o.status == 'success')}/"
                f"{sum(1 for o in apply_result.counter_proposes if o.status != 'success')}, "
                f"comments={sum(1 for o in apply_result.add_comments if o.status == 'success')}/"
                f"{sum(1 for o in apply_result.add_comments if o.status != 'success')}, "
                f"no_actions={len(apply_result.no_actions)}, "
                f"decisions_skipped={len(apply_result.decisions_skipped)}",
                "verify_output:",
                *[f"  {n}" for n in notes],
                "",
                f"finished={t1.isoformat()} | elapsed_seconds={elapsed:.1f}",
            ]
        ),
    )
    print(f"[10P] done in {elapsed:.1f}s | mechanical_ok={ok}")
    return 0 if ok else 1


def main() -> None:
    rc = run_once()
    sys.exit(rc)


if __name__ == "__main__":
    main()
