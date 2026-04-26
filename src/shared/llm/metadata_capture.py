"""LangChain reply metadata capture for routing-verification provenance.

Sprint 10O surfaced that experiment harnesses extracting only
``reply.content`` cannot prove which model actually served a call —
the canonical OpenRouter (and direct-provider) ``model`` field lives
in LangChain's ``response_metadata`` / ``additional_kwargs``, not in
the message body. CLAUDE.md § Redline Track Discipline requires that
sprints whose result depends on routing capture this metadata
alongside the .content output for every LLM call.

This module provides one helper, ``capture_reply_metadata``, that
experiment harnesses call after each ``chat_model.invoke()`` to write
a side-car JSON file. The helper is provider-agnostic: it pulls
``response_metadata``, ``additional_kwargs``, and ``usage_metadata``
from the reply object via ``getattr`` with ``None`` defaults, so
providers that omit any field do not raise. JSON serialisation uses
``default=str`` so any non-JSON-serialisable values (timestamps,
provider-specific objects) stringify cleanly.

Usage in a run.py:

    from src.shared.llm.metadata_capture import capture_reply_metadata

    reply = chat_model.invoke([...])
    capture_reply_metadata(reply, HERE / "llm-meta-planner.json")
    raw = reply.content if hasattr(reply, "content") else str(reply)
    ...

Naming convention for the destination path:
    llm-meta-{role}-{N}.json   for executor loops (N is the call index)
    llm-meta-{role}.json       for single-call roles (planner, etc.)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def capture_reply_metadata(reply: Any, dest_path: Path) -> None:
    """Write LangChain reply metadata to dest_path as JSON.

    Captured fields (all via getattr with None default — missing fields
    serialise as null rather than raising):

    - ``content_len``: length of ``reply.content`` (sanity-check the
      same content the harness wrote separately to llm-output-*.txt)
    - ``response_metadata``: provider-side envelope; for OpenRouter
      this typically includes the actual upstream ``model`` string
      after any version-pinning or fallback routing. For direct
      MiniMax this includes provider-specific fields.
    - ``additional_kwargs``: LangChain-merged extras; sometimes
      carries the model name when ``response_metadata`` does not.
    - ``usage_metadata``: token counts (input_tokens, output_tokens,
      total_tokens) if the provider reports them. Useful for cost
      reconciliation against the per-redline estimates in sprint plans.

    The destination directory must already exist. The function does
    not return anything; it raises only on disk I/O failures.
    """
    content = getattr(reply, "content", None)
    content_len = len(content) if isinstance(content, str) else None

    meta = {
        "content_len": content_len,
        "response_metadata": getattr(reply, "response_metadata", None),
        "additional_kwargs": getattr(reply, "additional_kwargs", None),
        "usage_metadata": getattr(reply, "usage_metadata", None),
    }

    dest_path.write_text(
        json.dumps(meta, default=str, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
