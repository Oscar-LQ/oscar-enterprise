"""Sprint C1 entry point — run the three CoSec drafting test cases.

For each case:
  1. Build a fresh drafter Deep Agent bound to the outputs directory.
  2. Invoke it with the case's drafting request.
  3. Locate the ``write_markdown_draft`` ToolMessage in the trace; pick
     up ``md_path`` from its content.
  4. Convert the markdown to ``.docx`` via the narrow python-docx
     converter (ADR 022 — post-agent, not a tool).
  5. Print a one-line summary per case: ``{case_id}: {docx_path}``.

One attempt per case. No retries. No self-correction. If an agent run
produces no ``write_markdown_draft`` ToolMessage, log it and move on —
this is the single-attempt discipline the brief requires (same shape as
the redline track's unsuccessful-sprint rule).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

# Silence LangChain / langgraph / langsmith INFO noise before framework
# import, mirroring the sprint-10d pattern.
import structlog

logging.basicConfig(level=logging.WARNING)
for _name in (
    "langchain",
    "langgraph",
    "langsmith",
    "httpx",
    "openai",
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

from cosec.agents.drafter import build_drafter_agent
from cosec.conversion.md_to_docx import convert_markdown_to_docx

# sprint-c1 is hyphenated — not a python-importable package name — so
# ``cosec.experiments.sprint-c1`` is unreachable via dotted import. We
# load test_cases.py as a sibling file instead; Python auto-adds the
# script's directory to sys.path[0] when invoked as
# ``python src/cosec/experiments/sprint-c1/run.py``.
from test_cases import TEST_CASES  # type: ignore[import-not-found]


HERE = Path(__file__).parent
OUTPUTS_DIR = HERE / "outputs"


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


def _extract_md_path(messages) -> str | None:
    """Walk the message trace to find the write_markdown_draft result."""
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        if msg.name != "write_markdown_draft":
            continue
        content = _text_of(msg)
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        md_path = payload.get("md_path") if isinstance(payload, dict) else None
        if isinstance(md_path, str):
            return md_path
    return None


def _echo_env() -> None:
    for name in [
        "OSCAR_LLM_COSEC_DRAFTER_PROVIDER",
        "OSCAR_LLM_COSEC_DRAFTER_MODEL",
    ]:
        print(f"{name:45s} = {os.environ.get(name)!r}")


def _run_case(case: dict) -> dict:
    case_id = case["id"]
    request = case["request"]

    agent = build_drafter_agent(OUTPUTS_DIR, case_id=case_id)

    print("=" * 72)
    print(f"CASE: {case_id}")
    print(f"REQUEST: {request}")
    print("=" * 72)

    result = agent.invoke({"messages": [HumanMessage(request)]})

    print("\n--- MESSAGE TRACE ---")
    for i, msg in enumerate(result["messages"], 1):
        print(f"  {i:2}. {_summary(msg)}")

    md_path = _extract_md_path(result["messages"])
    if md_path is None:
        print(
            f"\n!! {case_id}: no write_markdown_draft result in trace — "
            "single-attempt discipline says move on."
        )
        return {"case_id": case_id, "md_path": None, "docx_path": None}

    md_path_p = Path(md_path)
    docx_path = md_path_p.with_suffix(".docx")
    try:
        convert_markdown_to_docx(md_path_p, docx_path)
    except Exception as exc:  # noqa: BLE001 — log and move on per brief
        print(
            f"\n!! {case_id}: md→docx conversion failed: {type(exc).__name__}: "
            f"{exc}"
        )
        return {
            "case_id": case_id,
            "md_path": str(md_path_p),
            "docx_path": None,
        }

    print(f"\n-- {case_id}: md  = {md_path_p}")
    print(f"-- {case_id}: docx = {docx_path}")
    return {
        "case_id": case_id,
        "md_path": str(md_path_p),
        "docx_path": str(docx_path),
    }


def main() -> None:
    _echo_env()
    print()

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for case in TEST_CASES:
        results.append(_run_case(case))

    print("\n" + "=" * 72)
    print("SPRINT C1 SUMMARY")
    print("=" * 72)
    for r in results:
        status = "OK" if r["docx_path"] else "MISS"
        print(f"  {r['case_id']:40s} {status:5s} {r.get('docx_path') or ''}")


if __name__ == "__main__":
    main()
