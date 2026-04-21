"""Sprint 10M — driver for the Vibe Legal Redliner port on Oscar's stack.

Executes Vibe's verbatim pipeline against Oscar's NDA:

    1. Regenerate nda-input.docx via build_input.main()
    2. pipeline.prepare(docx_bytes, clean_view=False)
       → contract text with doc_analyser structural-context header
    3. Build Vibe's system + user prompts (prompt_builder)
    4. Invoke the configured chat model
       (OSCAR_LLM_REDLINE_EXECUTOR_* env triple)
    5. Parse the reply (response_parser 4-layer fallback)
    6. pipeline.apply_edits(edits_json, polish_formatting=False)
       → nda-output-{label}.docx
    7. verify_output on the output
    8. Append to transcript.txt

One invocation per model (no iteration). Mechanical fixes (env vars,
imports, paths, JSON parse fences) are allowed per brief; prompt and
parser logic are not to be iterated.

Usage:
    python src/redline/experiments/sprint-10M/run.py --label minimax
    python src/redline/experiments/sprint-10M/run.py --label gemini
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# 10E-style structlog silencing; must run before any `adeu` import.
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

# Make `src/shared/llm` importable.
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HERE))

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

from src.shared.llm.chat_model import get_chat_model  # noqa: E402

import build_input  # noqa: E402
import pipeline  # Vibe's pipeline (verbatim, Adeu 1.1.0 translated) # noqa: E402
from adeu.models import ModifyText  # noqa: E402
from prompt_builder import build_system_prompt, build_user_prompt  # noqa: E402
from response_parser import parse_ai_response  # noqa: E402


# --- verify_output (copied from sprint-10e/run.py:573-717 verbatim) -------

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": W_NS}


def _element_text(el) -> str:
    texts = el.xpath(".//w:t/text() | .//w:delText/text()", namespaces=_NS)
    return "".join(texts)


def _element_word_count(el) -> int:
    text = _element_text(el).strip()
    return len(text.split()) if text else 0


def verify_output(output_path: Path) -> tuple[bool, list[str]]:
    """Three mechanical checks + four Sprint 10E lawyer-shape warnings."""
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

    # (2) Nested w:del with empty w:delText
    from lxml import etree as _etree  # already imported but keep scope clean

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

    # (4) Litigation-text preservation spot-check
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

    return True, notes


# --- clean-view §9 read-back ---------------------------------------------


def clean_view_section_9(output_path: Path) -> str:
    """Accept-all-changes simulation: read §9 text with deletes removed
    and inserts kept. Returns the concatenated paragraph text.
    """
    from lxml import etree

    with zipfile.ZipFile(output_path) as zf:
        doc_xml = zf.read("word/document.xml")
    root = etree.fromstring(doc_xml)

    lines: list[str] = []
    in_section_9 = False
    for p in root.findall(".//w:p", _NS):
        # Heading detection: w:t text starts with "9."
        heading = "".join(p.xpath(".//w:t/text()", namespaces=_NS))
        if heading.strip().startswith("9."):
            in_section_9 = True
            lines.append(heading)
            continue
        if in_section_9:
            if heading.strip().startswith("10."):
                break
            # Accept-all: include w:ins content, exclude w:del / w:delText
            parts: list[str] = []
            for t in p.xpath(".//w:t", namespaces=_NS):
                # skip text inside a w:del
                ancestor_del = False
                node = t
                while node is not None:
                    if etree.QName(node.tag).localname == "del":
                        ancestor_del = True
                        break
                    node = node.getparent()
                if not ancestor_del:
                    parts.append(t.text or "")
            lines.append("".join(parts))
    return "\n".join(lines)


# --- main -----------------------------------------------------------------


def _env_triple(label: str) -> dict[str, str]:
    """Read the three OSCAR_LLM_REDLINE_EXECUTOR_* vars for artefact logging."""
    return {
        key: os.environ.get(f"OSCAR_LLM_REDLINE_EXECUTOR_{key}", "")
        for key in ("PROVIDER", "MODEL")
    }


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(f"[10M] wrote {path.name} ({len(text)} chars)")


def _append_transcript(transcript: Path, text: str) -> None:
    with transcript.open("a", encoding="utf-8") as f:
        f.write(text)
        f.write("\n")


def run_once(label: str) -> None:
    env = _env_triple(label)
    t0 = datetime.now(timezone.utc)
    provider = env["PROVIDER"] or "<unset>"
    model = env["MODEL"] or "<unset>"

    print(
        f"[10M] run label={label} | provider={provider} | model={model} | "
        f"started={t0.isoformat()}"
    )

    transcript = HERE / "transcript.txt"
    _append_transcript(
        transcript,
        f"\n=== Run {label} | provider={provider} | model={model} | "
        f"started {t0.isoformat()} ===",
    )

    # 1. Regenerate NDA (deterministic; same source as 10E/10K).
    build_input.main() if hasattr(build_input, "main") else _regenerate_nda()
    nda_input = HERE / "nda-input.docx"
    assert nda_input.exists(), f"missing input: {nda_input}"
    print(f"[10M] nda-input.docx = {nda_input.stat().st_size} bytes")

    # 2. pipeline.prepare — contract text with doc_analyser header.
    docx_bytes = nda_input.read_bytes()
    contract_text = pipeline.prepare(docx_bytes, clean_view=False, author="Oscar")
    print(f"[10M] contract text = {len(contract_text)} chars (with header)")

    # 3. Load playbook and assemble prompts.
    playbook_text = (HERE / "playbook.md").read_text(encoding="utf-8")
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(contract_text, playbook_text)
    llm_input = f"=== SYSTEM ===\n{system_prompt}\n\n=== USER ===\n{user_prompt}\n"
    _write(HERE / f"llm-input-{label}.txt", llm_input)

    # 4. Invoke chat model.
    chat_model = get_chat_model(env_prefix="OSCAR_LLM_REDLINE_EXECUTOR")
    reply = chat_model.invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    raw_content = reply.content if hasattr(reply, "content") else str(reply)
    if not isinstance(raw_content, str):
        # Some providers return content as a list of parts; coerce.
        raw_content = json.dumps(raw_content, ensure_ascii=False)
    _write(HERE / f"llm-output-{label}.txt", raw_content)
    print(f"[10M] LLM reply = {len(raw_content)} chars")

    # 5. Parse.
    parsed = parse_ai_response(raw_content)
    parse_method = parsed["parse_method"]
    edits = parsed["edits"]
    reasoning = parsed.get("reasoning")
    summary = parsed.get("summary", "")
    print(
        f"[10M] parse_method={parse_method} | edits={len(edits)} | "
        f"reasoning={'present' if reasoning else 'absent'}"
    )

    _write(
        HERE / f"parsed-edits-{label}.json",
        json.dumps(edits, ensure_ascii=False, indent=2),
    )

    # Classifications (reasoning.analysis[]) — Arturs re-emphasis.
    classifications: list | None = None
    if isinstance(reasoning, dict):
        classifications = reasoning.get("analysis")
    _write(
        HERE / f"classifications-{label}.json",
        json.dumps(
            {
                "parse_method": parse_method,
                "summary": summary,
                "reasoning": reasoning,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
    )

    # 6. Adeu calls capture — construct the same ModifyText list pipeline
    #    will consume, write pre-apply.
    modify_texts = [
        ModifyText(
            target_text=e.get("target_text", ""),
            new_text=e.get("new_text", ""),
            comment=e.get("comment") or None,
        )
        for e in edits
    ]
    with (HERE / f"adeu-calls-{label}.jsonl").open("w", encoding="utf-8") as f:
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
    print(f"[10M] captured {len(modify_texts)} ModifyText call(s)")

    # 7. Apply edits via Vibe's pipeline.apply_edits.
    #    Vibe's apply_edits reconstructs ModifyText from the JSON string,
    #    so we re-serialise the edit list (comment dropped at its
    #    boundary per pipeline.py:228-231 — faithful).
    edits_for_pipeline = [
        {"target_text": e.get("target_text", ""), "new_text": e.get("new_text", "")}
        for e in edits
    ]
    result = pipeline.apply_edits(
        json.dumps(edits_for_pipeline),
        fallback_bytes=docx_bytes,
        polish_formatting=False,
    )
    output_path = HERE / f"nda-output-{label}.docx"
    output_path.write_bytes(result["doc_bytes"])
    print(
        f"[10M] nda-output-{label}.docx = {output_path.stat().st_size} bytes | "
        f"applied={result['applied']} | skipped={result['skipped']}"
    )

    # 8. Verify.
    ok, notes = verify_output(output_path)
    print(f"[10M] verify_output ok={ok}")
    for line in notes:
        print(f"  {line}")

    # 9. Clean-view §9 read-back.
    cv9 = clean_view_section_9(output_path)
    print(f"[10M] clean-view §9:\n{cv9}\n")

    # 10. Transcript append.
    t1 = datetime.now(timezone.utc)
    elapsed = (t1 - t0).total_seconds()
    _append_transcript(
        transcript,
        "\n".join(
            [
                f"provider={provider} model={model}",
                f"parse_method={parse_method}",
                f"edits_returned={len(edits)} | applied={result['applied']} | skipped={result['skipped']}",
                f"reasoning_present={reasoning is not None} | classifications_count={len(classifications or [])}",
                "verify_output:",
                *[f"  {n}" for n in notes],
                "",
                "clean-view §9:",
                cv9,
                "",
                f"finished={t1.isoformat()} | elapsed_seconds={elapsed:.1f}",
            ]
        ),
    )
    print(f"[10M] done in {elapsed:.1f}s")


def _regenerate_nda() -> None:
    """Fallback if build_input.main() isn't defined — invoke the module
    script-style. Copy of 10E's invocation shape.
    """
    import runpy

    runpy.run_path(str(HERE / "build_input.py"), run_name="__main__")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--label",
        required=True,
        help="Artefact suffix for this run (e.g. 'minimax', 'gemini').",
    )
    args = ap.parse_args()
    run_once(args.label)


if __name__ == "__main__":
    main()
