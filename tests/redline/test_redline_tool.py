"""Unit tests for the M3 redline tool wrapper.

Mocks `run_redline` at the wrapper boundary — the real 10P pipeline is
exercised end-to-end in the live integration test (Phase 3).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from redline.tools._paths import (
    DEFAULT_NDA_INPUT,
    DEFAULT_NDA_ORIGINAL,
    DEFAULT_NDA_OUTPUT,
)
from redline.tools.redline import (
    RedlineToolInput,
    RedlineToolOutput,
    build_redline_tool,
)


def _fake_result(output_path: Path) -> SimpleNamespace:
    """Stand-in for `RedlineResult` shaped just enough for the wrapper."""
    return SimpleNamespace(
        output_path=output_path,
        elapsed_seconds=42.5,
        decisions_total=3,
        decisions_accepted=2,
        decisions_countered=1,
        decisions_commented=2,
        output_size_bytes=12345,
        mechanical_ok=True,
        notes=["fake"],
    )


def test_redline_tool_input_schema_accepts_brief_only() -> None:
    """The three path fields are Optional — `brief` alone validates."""
    parsed = RedlineToolInput(brief="please review")
    assert parsed.brief == "please review"
    assert parsed.input_path is None
    assert parsed.original_path is None
    assert parsed.output_path is None


def test_redline_tool_output_schema_round_trips() -> None:
    """`RedlineToolOutput` round-trips through `model_dump`/`__init__`."""
    output = RedlineToolOutput(
        output_path="/tmp/out.docx",
        elapsed_seconds=42.0,
        decisions_total=3,
        decisions_accepted=2,
        decisions_countered=1,
        decisions_commented=2,
        summary="Done in 42s.",
    )
    rebuilt = RedlineToolOutput(**output.model_dump())
    assert rebuilt == output


@pytest.mark.asyncio
async def test_redline_tool_substitutes_default_paths_when_not_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM-supplied input with `brief` only flows the factory defaults through."""
    captured: dict = {}

    async def fake_run_redline(
        *,
        input_path,
        output_path,
        original_path,
        brief,
        progress_callback=None,
    ):
        captured["input_path"] = input_path
        captured["output_path"] = output_path
        captured["original_path"] = original_path
        captured["brief"] = brief
        return _fake_result(output_path)

    monkeypatch.setattr("redline.tools.redline.run_redline", fake_run_redline)

    tool = build_redline_tool(
        default_input_path=DEFAULT_NDA_INPUT,
        default_original_path=DEFAULT_NDA_ORIGINAL,
        default_output_path=DEFAULT_NDA_OUTPUT,
    )
    await tool.ainvoke({"brief": "fixture-path test"})

    assert captured["brief"] == "fixture-path test"
    assert captured["input_path"] == DEFAULT_NDA_INPUT
    assert captured["original_path"] == DEFAULT_NDA_ORIGINAL
    assert captured["output_path"] == DEFAULT_NDA_OUTPUT


@pytest.mark.asyncio
async def test_redline_tool_uses_supplied_paths_over_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Explicit paths in the LLM-supplied input override factory defaults.

    M4 (Slack file upload) needs this — the LLM will be passing real
    paths derived from Slack attachments, not the M3 fixtures.
    """
    captured: dict = {}

    async def fake_run_redline(
        *,
        input_path,
        output_path,
        original_path,
        brief,
        progress_callback=None,
    ):
        captured["input_path"] = input_path
        captured["output_path"] = output_path
        captured["original_path"] = original_path
        return _fake_result(output_path)

    monkeypatch.setattr("redline.tools.redline.run_redline", fake_run_redline)

    tool = build_redline_tool(
        default_input_path=DEFAULT_NDA_INPUT,
        default_original_path=DEFAULT_NDA_ORIGINAL,
        default_output_path=DEFAULT_NDA_OUTPUT,
    )
    custom_in = tmp_path / "custom_in.docx"
    custom_orig = tmp_path / "custom_orig.docx"
    custom_out = tmp_path / "custom_out.docx"
    await tool.ainvoke(
        {
            "brief": "custom",
            "input_path": str(custom_in),
            "original_path": str(custom_orig),
            "output_path": str(custom_out),
        }
    )

    assert captured["input_path"] == custom_in
    assert captured["original_path"] == custom_orig
    assert captured["output_path"] == custom_out


@pytest.mark.asyncio
async def test_redline_tool_threads_progress_callback_to_run_redline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The factory's `progress_callback` is forwarded to `run_redline`.

    Progress narration is the load-bearing user-facing contract for M3
    (ADR 028). This test pins the wiring from `build_redline_tool`'s
    closure through to the pipeline.
    """
    captured_cbs: list = []

    async def fake_run_redline(
        *,
        input_path,
        output_path,
        original_path,
        brief,
        progress_callback=None,
    ):
        captured_cbs.append(progress_callback)
        return _fake_result(output_path)

    monkeypatch.setattr("redline.tools.redline.run_redline", fake_run_redline)

    async def my_cb(msg: str) -> None:
        return None

    tool = build_redline_tool(
        default_input_path=DEFAULT_NDA_INPUT,
        default_original_path=DEFAULT_NDA_ORIGINAL,
        default_output_path=DEFAULT_NDA_OUTPUT,
        progress_callback=my_cb,
    )
    await tool.ainvoke({"brief": "test"})

    assert captured_cbs == [my_cb]


def test_run_once_unchanged_byte_for_byte_smoke() -> None:
    """`run_once` preserved as the 10P demonstrator entry point.

    The 10P fixture baseline (`nda-output-minimal.docx`) was produced by
    `run_once()` with author="Acme Counsel". M3 must not edit `run_once`
    — see plan § 5 Phase 1. This smoke test fails if the function gains
    parameters or loses its hardcoded author identity.
    """
    import importlib
    import inspect
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    tenp_dir = repo_root / "src/redline/experiments/sprint-10P"
    if str(tenp_dir) not in sys.path:
        sys.path.insert(0, str(tenp_dir))
    run_module = importlib.import_module("run")

    sig = inspect.signature(run_module.run_once)
    assert list(sig.parameters) == [], (
        f"run_once must take no parameters; got {sig.parameters}"
    )
    # `from __future__ import annotations` stringifies the annotation.
    assert sig.return_annotation in (int, "int"), (
        f"run_once must return int (exit code); got {sig.return_annotation}"
    )

    source = inspect.getsource(run_module.run_once)
    assert "Acme Counsel" in source, (
        "run_once author must remain Acme Counsel — M3 fixture baseline"
    )
