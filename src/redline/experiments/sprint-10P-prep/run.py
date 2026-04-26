"""Sprint 10P-prep — Oscar acts for Zenith, first-pass redline on Acme NDA.

End-to-end:
    1. Regenerate nda-input.docx via build_input
    2. pipeline.prepare(docx_bytes, clean_view=False)
       → contract text with doc_analyser structural-context header
    3. Build planner system + user prompts
    4. Invoke the planner (GPT-5.5 non-Pro) via OSCAR_LLM_REDLINE_PLANNER_*
    5. Parse the plan via response_parser.parse_plan_response
    6. Topological sort by depends_on (flat if all standalone)
    7. Per instruction: build executor user prompt, invoke MiniMax via
       OSCAR_LLM_REDLINE_EXECUTOR_*, parse via parse_single_edit_response,
       collect into edit list
    8. Apply via pipeline.apply_edits (with Q1 comment-fix at the
       re-serialisation step — comment field carried through)
    9. verify_output mechanical layer
    10. Append transcript

One Phase 3 run. Mechanical fixes only. No prompt iteration.

Usage:
    python src/redline/experiments/sprint-10P-prep/run.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
import zipfile
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
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

import build_input  # noqa: E402
import pipeline  # noqa: E402
from adeu.models import ModifyText  # noqa: E402
from prompt_builder import (  # noqa: E402
    build_executor_user_prompt,
    build_planner_user_prompt,
    load_executor_system_prompt,
    load_planner_system_prompt,
)
from response_parser import parse_plan_response, parse_single_edit_response  # noqa: E402


# --- verify_output (verbatim from 10N; unchanged for 10O) -----------------

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": W_NS}


def _element_text(el) -> str:
    texts = el.xpath(".//w:t/text() | .//w:delText/text()", namespaces=_NS)
    return "".join(texts)


def _element_word_count(el) -> int:
    text = _element_text(el).strip()
    return len(text.split()) if text else 0


def verify_output(output_path: Path) -> tuple[bool, list[str]]:
    """Three mechanical checks + four lawyer-shape diagnostics."""
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
            notes.append(f"INFO: w:{tag}[id={wid}] span={wc} words (>50)")
        elif wc > 20:
            notes.append(f"INFO: w:{tag}[id={wid}] span={wc} words (>20)")

    from lxml import etree as _etree
    for d in del_elements:
        empty_dts = [
            dt for dt in d.findall(".//w:delText", _NS)
            if (dt.text is None or dt.text == "")
        ]
        has_ancestor_del = False
        parent = d.getparent()
        while parent is not None:
            if _etree.QName(parent.tag).localname == "del":
                has_ancestor_del = True
                break
            parent = parent.getparent()
        if empty_dts and has_ancestor_del:
            wid = d.get(f"{{{W_NS}}}id", "?")
            notes.append(
                f"WARN: w:del[id={wid}] is a nested w:del with empty w:delText"
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
                f"WARN: {count} w:ins elements share identical {wc}-word content"
            )

    all_del_text = "".join(root.xpath(".//w:delText/text()", namespaces=_NS))
    needle = "exclusive jurisdiction of the courts of England and Wales"
    if needle in all_del_text:
        notes.append(f"SPOT-CHECK OK: litigation phrase preserved in w:delText.")
    else:
        notes.append(f"INFO: litigation phrase not in w:delText.")

    return True, notes


# --- planner-executor coordination ---------------------------------------


def _topological_sort(plan: list[dict]) -> list[dict]:
    """Sort plan instructions by depends_on. Detects cycles.

    Most plans are flat (no depends_on); this preserves original
    order in that case.
    """
    if not any(item.get("depends_on") for item in plan):
        return list(plan)

    by_id = {p["id"]: p for p in plan}
    in_degree: dict[str, int] = defaultdict(int)
    deps_of: dict[str, list[str]] = defaultdict(list)
    for p in plan:
        for d in p.get("depends_on") or []:
            if d not in by_id:
                print(f"[10P-prep] depends_on: instruction {p['id']!r} references missing id {d!r}; ignoring")
                continue
            in_degree[p["id"]] += 1
            deps_of[d].append(p["id"])

    queue = deque(p["id"] for p in plan if in_degree[p["id"]] == 0)
    sorted_ids: list[str] = []
    while queue:
        nid = queue.popleft()
        sorted_ids.append(nid)
        for dependent in deps_of[nid]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(sorted_ids) != len(plan):
        cycle_ids = [pid for pid in by_id if pid not in sorted_ids]
        raise RuntimeError(f"depends_on cycle detected among instructions: {cycle_ids}")

    return [by_id[i] for i in sorted_ids]


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(f"[10P-prep] wrote {path.name} ({len(text)} chars)")


def _append_transcript(transcript: Path, text: str) -> None:
    with transcript.open("a", encoding="utf-8") as f:
        f.write(text)
        f.write("\n")


def run_once() -> int:
    t0 = datetime.now(timezone.utc)
    p_provider = os.environ.get("OSCAR_LLM_REDLINE_PLANNER_PROVIDER", "<unset>")
    p_model = os.environ.get("OSCAR_LLM_REDLINE_PLANNER_MODEL", "<unset>")
    e_provider = os.environ.get("OSCAR_LLM_REDLINE_EXECUTOR_PROVIDER", "<unset>")
    e_model = os.environ.get("OSCAR_LLM_REDLINE_EXECUTOR_MODEL", "<unset>")
    print(
        f"[10P-prep] planner={p_provider}/{p_model} | executor={e_provider}/{e_model} | "
        f"started={t0.isoformat()}"
    )

    transcript = HERE / "transcript.txt"
    _append_transcript(
        transcript,
        f"\n=== Sprint 10P-prep Phase 3 | planner={p_provider}/{p_model} | "
        f"executor={e_provider}/{e_model} | started {t0.isoformat()} ===",
    )

    # 1. Regenerate NDA.
    if hasattr(build_input, "main"):
        build_input.main()
    else:
        import runpy
        runpy.run_path(str(HERE / "build_input.py"), run_name="__main__")
    nda_input = HERE / "nda-input.docx"
    assert nda_input.exists(), f"missing input: {nda_input}"
    print(f"[10P-prep] nda-input.docx = {nda_input.stat().st_size} bytes")

    # 2. pipeline.prepare.
    docx_bytes = nda_input.read_bytes()
    contract_text = pipeline.prepare(docx_bytes, clean_view=False, author="Zenith Counsel")
    print(f"[10P-prep] contract text = {len(contract_text)} chars (with header)")

    # 3+4. Planner: assemble + invoke.
    planner_system = load_planner_system_prompt()
    planner_user = build_planner_user_prompt(contract_text)
    _write(
        HERE / "llm-input-planner.txt",
        f"=== SYSTEM (len={len(planner_system)}) ===\n{planner_system}\n\n"
        f"=== USER (len={len(planner_user)}) ===\n{planner_user}\n",
    )

    planner_chat = get_chat_model(env_prefix="OSCAR_LLM_REDLINE_PLANNER")
    print(f"[10P-prep] invoking planner {p_provider}/{p_model} ...")
    p_reply = planner_chat.invoke(
        [SystemMessage(content=planner_system), HumanMessage(content=planner_user)]
    )
    capture_reply_metadata(p_reply, HERE / "llm-meta-planner.json")
    p_raw = p_reply.content if hasattr(p_reply, "content") else str(p_reply)
    if not isinstance(p_raw, str):
        p_raw = json.dumps(p_raw, ensure_ascii=False)
    _write(HERE / "llm-output-planner.txt", p_raw)
    print(f"[10P-prep] planner reply = {len(p_raw)} chars")

    # 5. Parse plan.
    try:
        parsed_plan = parse_plan_response(p_raw)
    except ValueError as exc:
        print(f"[10P-prep] PLANNER PARSE FAILED: {exc}")
        _append_transcript(transcript, f"PLANNER PARSE FAILED: {exc}\n")
        return 2

    plan = parsed_plan["plan"]
    cross_clause_notes = parsed_plan["cross_clause_notes"]
    plan_method = parsed_plan["parse_method"]
    print(
        f"[10P-prep] plan: parse_method={plan_method} | instructions={len(plan)} "
        f"| cross_clause_notes={len(cross_clause_notes)}"
    )
    _write(
        HERE / "parsed-plan.json",
        json.dumps(
            {
                "plan": plan,
                "cross_clause_notes": cross_clause_notes,
                "parse_method": plan_method,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )

    if not plan:
        print("[10P-prep] empty plan — nothing to execute")
        _append_transcript(transcript, "Empty plan — Outcome C\n")
        return 1

    # 6. Topological sort.
    try:
        sorted_plan = _topological_sort(plan)
    except RuntimeError as exc:
        print(f"[10P-prep] TOPO SORT FAILED: {exc}")
        _append_transcript(transcript, f"TOPO SORT FAILED: {exc}\n")
        return 2

    # 7. Executor loop.
    executor_system = load_executor_system_prompt()
    executor_chat = get_chat_model(env_prefix="OSCAR_LLM_REDLINE_EXECUTOR")
    edits: list[dict] = []
    executor_methods: list[str] = []
    skipped_instructions: list[tuple[str, str]] = []

    for idx, instruction in enumerate(sorted_plan, start=1):
        pid = instruction["id"]
        executor_user = build_executor_user_prompt(instruction, contract_text)
        _write(
            HERE / f"llm-input-executor-{idx:02d}-{pid}.txt",
            f"=== SYSTEM (len={len(executor_system)}) ===\n{executor_system}\n\n"
            f"=== USER (len={len(executor_user)}) ===\n{executor_user}\n",
        )
        print(f"[10P-prep] invoking executor for instruction {pid} ({idx}/{len(sorted_plan)}) ...")
        e_reply = executor_chat.invoke(
            [SystemMessage(content=executor_system), HumanMessage(content=executor_user)]
        )
        capture_reply_metadata(e_reply, HERE / f"llm-meta-executor-{idx:02d}-{pid}.json")
        e_raw = e_reply.content if hasattr(e_reply, "content") else str(e_reply)
        if not isinstance(e_raw, str):
            e_raw = json.dumps(e_raw, ensure_ascii=False)
        _write(HERE / f"llm-output-executor-{idx:02d}-{pid}.txt", e_raw)

        try:
            parsed_edit = parse_single_edit_response(e_raw)
        except ValueError as exc:
            print(f"[10P-prep] EXECUTOR {pid} PARSE FAILED: {exc}")
            skipped_instructions.append((pid, f"parse failure: {exc}"))
            continue

        target = parsed_edit["target_text"]
        new = parsed_edit["new_text"]
        if not target or not new:
            print(f"[10P-prep] EXECUTOR {pid}: empty target_text or new_text — skipping")
            skipped_instructions.append((pid, "empty target_text or new_text"))
            continue

        executor_methods.append(parsed_edit["parse_method"])
        edits.append({
            "id": pid,
            "target_text": target,
            "new_text": new,
            "comment": parsed_edit["comment"] or instruction.get("comment_for_partner") or "",
        })

    print(
        f"[10P-prep] executor pass complete: {len(edits)} edits, "
        f"{len(skipped_instructions)} skipped"
    )

    _write(
        HERE / "parsed-edits.json",
        json.dumps(edits, ensure_ascii=False, indent=2),
    )

    # 8. Apply via pipeline.apply_edits with Q1 comment-fix.
    # The fix preserves the comment field through the re-serialisation;
    # however, comments only land in OOXML for edges that route through
    # Adeu's delegation path (engine.apply_edits). The inline word-diff
    # path bypasses Adeu's comment integration. Documented in pipeline.py
    # docstring; full resolution is part of the 10P+ refactor.
    edits_for_pipeline = [
        {
            "target_text": e["target_text"],
            "new_text": e["new_text"],
            "comment": e.get("comment") or None,
        }
        for e in edits
    ]
    with (HERE / "adeu-calls.jsonl").open("w", encoding="utf-8") as f:
        for e in edits_for_pipeline:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    if not edits_for_pipeline:
        print("[10P-prep] no edits to apply — Outcome C")
        _append_transcript(transcript, "No edits to apply\n")
        return 1

    result = pipeline.apply_edits(
        json.dumps(edits_for_pipeline),
        fallback_bytes=docx_bytes,
        polish_formatting=False,
    )
    output_path = HERE / "nda-output.docx"
    output_path.write_bytes(result["doc_bytes"])
    print(
        f"[10P-prep] nda-output.docx = {output_path.stat().st_size} bytes | "
        f"applied={result['applied']} | skipped={result['skipped']}"
    )

    # 9. Verify.
    ok, notes = verify_output(output_path)
    print(f"[10P-prep] verify_output ok={ok}")
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
                f"plan: parse_method={plan_method} | instructions={len(plan)} | "
                f"executed={len(edits)} | skipped_executor={len(skipped_instructions)}",
                f"executor parse_methods: {dict(Counter(executor_methods))}",
                f"cross_clause_notes_count: {len(cross_clause_notes)}",
                f"applied={result['applied']} | skipped_apply={result['skipped']}",
                "verify_output:",
                *[f"  {n}" for n in notes],
                "",
                f"finished={t1.isoformat()} | elapsed_seconds={elapsed:.1f}",
            ]
        ),
    )
    print(f"[10P-prep] done in {elapsed:.1f}s | mechanical_ok={ok}")
    return 0 if ok else 1


def main() -> None:
    rc = run_once()
    sys.exit(rc)


if __name__ == "__main__":
    main()
