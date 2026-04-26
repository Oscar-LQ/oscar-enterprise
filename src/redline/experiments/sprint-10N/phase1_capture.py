"""Sprint 10N Phase 1B — capture B1 vs B2 LLM responses without applying.

Per the plan: build the NDA, prepare contract text, build prompt
(B1 trimmed Vibe OR B2 short solicitor + solicitor brief + data
contract note), invoke MiniMax once, parse, write artefacts. NO call
to pipeline.apply_edits — we are observing the LLM's edit list shape,
not producing a .docx.

Usage:
    python phase1_capture.py --variant B1
    python phase1_capture.py --variant B2

Artefacts written to this directory:
    llm-input-{B1,B2}.txt        full prompt (system + user) sent to MiniMax
    llm-output-{B1,B2}.txt       raw LLM reply
    parsed-edits-{B1,B2}.json    parsed edits list (validated)
    classifications-{B1,B2}.json reasoning object if LLM produced one
    phase1-summary-{B1,B2}.txt   human-readable run summary
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import structlog
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HERE))

# Quieten Adeu/structlog noise to keep stdout legible.
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

# Load .env so OSCAR_LLM_REDLINE_EXECUTOR_* are available.
load_dotenv(REPO_ROOT / ".env")

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

from src.shared.llm.chat_model import get_chat_model  # noqa: E402

import build_input  # noqa: E402
import pipeline  # noqa: E402
from prompt_builder import build_user_prompt, load_system_prompt  # noqa: E402
from response_parser import parse_ai_response  # noqa: E402


def run_one(variant: str) -> None:
    assert variant in ("B1", "B2"), f"variant must be B1 or B2, got {variant!r}"
    t0 = datetime.now(timezone.utc)
    provider = os.environ.get("OSCAR_LLM_REDLINE_EXECUTOR_PROVIDER", "<unset>")
    model = os.environ.get("OSCAR_LLM_REDLINE_EXECUTOR_MODEL", "<unset>")
    print(f"[10N-P1] variant={variant} | provider={provider} | model={model} | started={t0.isoformat()}")

    # 1. Regenerate NDA.
    if hasattr(build_input, "main"):
        build_input.main()
    else:
        import runpy
        runpy.run_path(str(HERE / "build_input.py"), run_name="__main__")
    nda_input = HERE / "nda-input.docx"
    assert nda_input.exists(), f"missing input: {nda_input}"
    print(f"[10N-P1] nda-input.docx = {nda_input.stat().st_size} bytes")

    # 2. pipeline.prepare — gives us contract text with doc_analyser header.
    docx_bytes = nda_input.read_bytes()
    contract_text = pipeline.prepare(docx_bytes, clean_view=False, author="Oscar")
    print(f"[10N-P1] contract text = {len(contract_text)} chars (with header)")

    # 3. Assemble prompts.
    system_prompt = load_system_prompt(variant)
    user_prompt = build_user_prompt(contract_text)
    llm_input = (
        f"=== SYSTEM (variant={variant}, len={len(system_prompt)}) ===\n"
        f"{system_prompt}\n\n"
        f"=== USER (len={len(user_prompt)}) ===\n"
        f"{user_prompt}\n"
    )
    (HERE / f"llm-input-{variant}.txt").write_text(llm_input, encoding="utf-8")
    print(f"[10N-P1] system={len(system_prompt)} chars | user={len(user_prompt)} chars")

    # 4. Invoke MiniMax.
    chat_model = get_chat_model(env_prefix="OSCAR_LLM_REDLINE_EXECUTOR")
    print(f"[10N-P1] invoking {provider}/{model} ...")
    reply = chat_model.invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    raw_content = reply.content if hasattr(reply, "content") else str(reply)
    if not isinstance(raw_content, str):
        raw_content = json.dumps(raw_content, ensure_ascii=False)
    (HERE / f"llm-output-{variant}.txt").write_text(raw_content, encoding="utf-8")
    print(f"[10N-P1] LLM reply = {len(raw_content)} chars")

    # 5. Parse response.
    try:
        parsed = parse_ai_response(raw_content)
    except ValueError as exc:
        # Parser exhausted all four fallbacks — capture as Phase 1 finding,
        # write empty parsed-edits file with diagnostic, return.
        print(f"[10N-P1] PARSE FAILED for {variant}: {exc}")
        diagnostic = {
            "parse_method": "exhausted-all-fallbacks",
            "error": str(exc),
            "raw_content_length": len(raw_content),
            "raw_content_preview": raw_content[:500],
        }
        (HERE / f"parsed-edits-{variant}.json").write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _write_summary(variant, t0, provider, model, len(raw_content), 0, "exhausted-all-fallbacks", None, None, str(exc))
        return

    edits = parsed["edits"]
    parse_method = parsed["parse_method"]
    source_key = parsed.get("source_key")
    reasoning = parsed.get("reasoning")
    summary_text = parsed.get("summary", "")

    # 6. Write parsed-edits-{variant}.json (the edit list itself).
    (HERE / f"parsed-edits-{variant}.json").write_text(
        json.dumps(edits, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Reasoning sidecar (Vibe-style structured reasoning if present).
    (HERE / f"classifications-{variant}.json").write_text(
        json.dumps(
            {
                "parse_method": parse_method,
                "source_key": source_key,
                "summary": summary_text,
                "reasoning": reasoning,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print(
        f"[10N-P1] parse_method={parse_method} | source_key={source_key} | "
        f"edits={len(edits)} | reasoning={'present' if reasoning else 'absent'}"
    )

    _write_summary(variant, t0, provider, model, len(raw_content), len(edits), parse_method, source_key, reasoning, None)


def _write_summary(
    variant: str,
    t0: datetime,
    provider: str,
    model: str,
    raw_len: int,
    edit_count: int,
    parse_method: str,
    source_key: str | None,
    reasoning: object,
    error: str | None,
) -> None:
    t1 = datetime.now(timezone.utc)
    elapsed = (t1 - t0).total_seconds()
    lines = [
        f"=== Sprint 10N Phase 1B — variant={variant} ===",
        f"started: {t0.isoformat()}",
        f"finished: {t1.isoformat()}",
        f"elapsed_seconds: {elapsed:.1f}",
        f"provider/model: {provider}/{model}",
        f"raw_response_chars: {raw_len}",
        f"edit_count: {edit_count}",
        f"parse_method: {parse_method}",
        f"source_key: {source_key}",
        f"reasoning_present: {reasoning is not None}",
    ]
    if isinstance(reasoning, dict) and isinstance(reasoning.get("analysis"), list):
        statuses: dict[str, int] = {}
        for a in reasoning["analysis"]:
            if isinstance(a, dict):
                s = a.get("status", "<none>")
                statuses[s] = statuses.get(s, 0) + 1
        lines.append(f"reasoning.analysis count: {len(reasoning['analysis'])}")
        lines.append(f"status_counts: {statuses}")
    if error:
        lines.append(f"ERROR: {error}")
    summary_text = "\n".join(lines) + "\n"
    (HERE / f"phase1-summary-{variant}.txt").write_text(summary_text, encoding="utf-8")
    print(summary_text)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", required=True, choices=["B1", "B2"])
    args = ap.parse_args()
    run_one(args.variant)


if __name__ == "__main__":
    main()
