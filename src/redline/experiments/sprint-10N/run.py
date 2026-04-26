"""Sprint 10N — driver for the real-solicitor-brief MiniMax single-shot run.

Executes Vibe's verbatim pipeline against Oscar's NDA with the 10N
solicitor's brief replacing the 10M playbook:

    1. Regenerate nda-input.docx via build_input
    2. pipeline.prepare(docx_bytes, clean_view=False)
       → contract text with doc_analyser structural-context header
    3. Load system_prompt.txt (B1 trimmed Vibe per Phase 2 approval)
    4. Assemble user message: solicitor brief + contract + data contract note
    5. Invoke MiniMax via OSCAR_LLM_REDLINE_EXECUTOR_*
    6. Parse via response_parser (looks for `changes`, falls back to `edits`)
    7. pipeline.apply_edits(edits_json, polish_formatting=False)
       → nda-output.docx
    8. verify_output mechanical layer
    9. Append to transcript.txt

One invocation (no two-model protocol). Mechanical fixes (env vars,
imports, paths, JSON parse fences) are allowed; prompt and parser
logic are not iterated. Substantive verdict deferred to Arturs's
review of the .docx in Word.

Usage:
    python src/redline/experiments/sprint-10N/run.py
"""
from __future__ import annotations

import io
import json
import logging
import os
import sys
import zipfile
from collections import Counter
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

import build_input  # noqa: E402
import pipeline  # noqa: E402
from adeu.models import ModifyText  # noqa: E402
from prompt_builder import build_user_prompt, load_system_prompt  # noqa: E402
from response_parser import parse_ai_response  # noqa: E402


# --- verify_output (verbatim from sprint-10e/run.py:573-717 via 10M) ------

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

    Reused verbatim from 10M. Span-width warnings are still captured but
    are diagnostic only — Arturs's substantive review of the .docx is
    the bar (per 10N brief).
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

    # (1) Span widths — diagnostic only for 10N (Arturs reviews the .docx)
    for el in ins_elements + del_elements:
        tag = etree.QName(el.tag).localname
        wid = el.get(f"{{{W_NS}}}id", "?")
        wc = _element_word_count(el)
        if wc > 50:
            notes.append(
                f"INFO: w:{tag}[id={wid}] span={wc} words (>50)"
            )
        elif wc > 20:
            notes.append(
                f"INFO: w:{tag}[id={wid}] span={wc} words (>20)"
            )

    # (2) Nested w:del with empty w:delText — audit-trail integrity check
    from lxml import etree as _etree

    for d in del_elements:
        empty_dts = [
            dt
            for dt in d.findall(".//w:delText", _NS)
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
                f"WARN: w:del[id={wid}] is a nested w:del with empty "
                f"w:delText — original text not preserved in audit trail"
            )

    # (3) Duplicate w:ins content (>10 words, ≥2 copies)
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
                f"content — duplicate insertion. Content starts: "
                f"{content[:80]!r}"
            )

    # (4) Litigation-text preservation spot-check — for 10N, the brief
    #     mandates LCIA arbitration so the jurisdiction phrase SHOULD
    #     end up in w:delText. Spot-check still applies.
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
            f"INFO: litigation phrase {needle!r} not in w:delText (LLM "
            f"may have produced a wider edit that targeted the whole "
            f"§9 paragraph including the jurisdiction phrase)."
        )

    return True, notes


# --- main -----------------------------------------------------------------


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(f"[10N] wrote {path.name} ({len(text)} chars)")


def _append_transcript(transcript: Path, text: str) -> None:
    with transcript.open("a", encoding="utf-8") as f:
        f.write(text)
        f.write("\n")


def run_once() -> int:
    t0 = datetime.now(timezone.utc)
    provider = os.environ.get("OSCAR_LLM_REDLINE_EXECUTOR_PROVIDER", "<unset>")
    model = os.environ.get("OSCAR_LLM_REDLINE_EXECUTOR_MODEL", "<unset>")
    print(f"[10N] provider={provider} | model={model} | started={t0.isoformat()}")

    transcript = HERE / "transcript.txt"
    _append_transcript(
        transcript,
        f"\n=== Sprint 10N Phase 3 | provider={provider} | model={model} | "
        f"started {t0.isoformat()} ===",
    )

    # 1. Regenerate NDA.
    if hasattr(build_input, "main"):
        build_input.main()
    else:
        import runpy
        runpy.run_path(str(HERE / "build_input.py"), run_name="__main__")
    nda_input = HERE / "nda-input.docx"
    assert nda_input.exists(), f"missing input: {nda_input}"
    print(f"[10N] nda-input.docx = {nda_input.stat().st_size} bytes")

    # 2. pipeline.prepare.
    docx_bytes = nda_input.read_bytes()
    contract_text = pipeline.prepare(docx_bytes, clean_view=False, author="Oscar")
    print(f"[10N] contract text = {len(contract_text)} chars (with header)")

    # 3. Load chosen system prompt + assemble user prompt.
    system_prompt = load_system_prompt("")
    user_prompt = build_user_prompt(contract_text)
    llm_input = (
        f"=== SYSTEM (len={len(system_prompt)}) ===\n{system_prompt}\n\n"
        f"=== USER (len={len(user_prompt)}) ===\n{user_prompt}\n"
    )
    _write(HERE / "llm-input.txt", llm_input)

    # 4. Invoke MiniMax.
    chat_model = get_chat_model(env_prefix="OSCAR_LLM_REDLINE_EXECUTOR")
    print(f"[10N] invoking {provider}/{model} ...")
    reply = chat_model.invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    raw_content = reply.content if hasattr(reply, "content") else str(reply)
    if not isinstance(raw_content, str):
        raw_content = json.dumps(raw_content, ensure_ascii=False)
    _write(HERE / "llm-output.txt", raw_content)
    print(f"[10N] LLM reply = {len(raw_content)} chars")

    # 5. Parse.
    try:
        parsed = parse_ai_response(raw_content)
    except ValueError as exc:
        print(f"[10N] PARSE FAILED: {exc}")
        _append_transcript(transcript, f"PARSE FAILED: {exc}\n")
        return 2

    edits = parsed["edits"]
    parse_method = parsed["parse_method"]
    source_key = parsed.get("source_key")
    reasoning = parsed.get("reasoning")
    summary_text = parsed.get("summary", "")
    print(
        f"[10N] parse_method={parse_method} | source_key={source_key} | "
        f"edits={len(edits)} | reasoning={'present' if reasoning else 'absent'}"
    )

    _write(
        HERE / "parsed-edits.json",
        json.dumps(edits, ensure_ascii=False, indent=2),
    )

    # 6. Adeu calls capture.
    modify_texts = [
        ModifyText(
            target_text=e.get("target_text", ""),
            new_text=e.get("new_text", ""),
            comment=e.get("comment") or None,
        )
        for e in edits
    ]
    with (HERE / "adeu-calls.jsonl").open("w", encoding="utf-8") as f:
        for mt in modify_texts:
            f.write(
                json.dumps(
                    {
                        "target_text": mt.target_text,
                        "new_text": mt.new_text,
                        "comment": mt.comment,
                    },
                    ensure_ascii=False,
                )
            )
            f.write("\n")
    print(f"[10N] captured {len(modify_texts)} ModifyText call(s)")

    # 7. Apply via pipeline.apply_edits (Vibe's pipeline; comment dropped at
    #    the pipeline.py boundary per pipeline.py:228-231).
    edits_for_pipeline = [
        {"target_text": e.get("target_text", ""), "new_text": e.get("new_text", "")}
        for e in edits
    ]
    result = pipeline.apply_edits(
        json.dumps(edits_for_pipeline),
        fallback_bytes=docx_bytes,
        polish_formatting=False,
    )
    output_path = HERE / "nda-output.docx"
    output_path.write_bytes(result["doc_bytes"])
    print(
        f"[10N] nda-output.docx = {output_path.stat().st_size} bytes | "
        f"applied={result['applied']} | skipped={result['skipped']}"
    )

    # 8. Verify mechanical layer.
    ok, notes = verify_output(output_path)
    print(f"[10N] verify_output ok={ok}")
    for line in notes:
        print(f"  {line}")

    # 9. Transcript.
    t1 = datetime.now(timezone.utc)
    elapsed = (t1 - t0).total_seconds()
    _append_transcript(
        transcript,
        "\n".join(
            [
                f"provider={provider} model={model}",
                f"parse_method={parse_method} | source_key={source_key}",
                f"edits_returned={len(edits)} | applied={result['applied']} | skipped={result['skipped']}",
                f"reasoning_present={reasoning is not None}",
                "verify_output:",
                *[f"  {n}" for n in notes],
                "",
                f"finished={t1.isoformat()} | elapsed_seconds={elapsed:.1f}",
            ]
        ),
    )
    print(f"[10N] done in {elapsed:.1f}s | mechanical_ok={ok}")
    return 0 if ok else 1


def main() -> None:
    rc = run_once()
    sys.exit(rc)


if __name__ == "__main__":
    main()
