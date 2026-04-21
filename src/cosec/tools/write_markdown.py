"""The CoSec drafter's single agent-tool — Sprint C1.

``write_markdown_draft`` is the drafter's completion ritual: it writes the
drafted markdown to the per-case output directory and returns ``{md_path,
doc_type}`` so the entry-point script can pick up the file for post-agent
``.docx`` conversion (ADR 022 — markdown is the intermediate representation;
conversion is a post-agent step, not a tool).

Paths are bound at factory time via closure, matching ADR 017's discipline
that binary/path state does not flow through the agent's message graph.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from langchain_core.tools import BaseTool, tool


def make_write_markdown_tool(
    output_dir: Path,
    *,
    case_id: str,
) -> list[BaseTool]:
    """Build the single agent tool bound to the case's output directory.

    The tool writes to ``output_dir / {case_id}-{doc_type}.md`` — one file
    per invocation; the case id prefix keeps multi-case runs grouped on disk
    even though each agent invocation sees only its own case.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    @tool
    def write_markdown_draft(markdown: str, document_type: str) -> dict:
        """Save the drafted CoSec document to disk and complete the task.

        Call this ONCE when your markdown draft is complete. There is no
        other way to finish — you must call this tool with the full markdown
        and the document_type.

        Args:
            markdown: The full drafted document as markdown. Must be
                non-empty.
            document_type: A short slug naming the document type — one of:
                ``board-written-resolution``, ``shareholder-written-resolution``,
                ``board-minutes``, ``notice-of-meeting``, or
                ``director-consent``. Used for the output filename only.

        Returns:
            ``{"md_path": <absolute path to the saved .md>,
               "doc_type": <document_type as passed>}``.
        """
        if not markdown or not markdown.strip():
            return {
                "error": (
                    "ERROR: markdown was empty. Draft the document first, "
                    "then call write_markdown_draft with the full markdown."
                )
            }
        if not document_type or not document_type.strip():
            return {
                "error": (
                    "ERROR: document_type was empty. Pass a short slug "
                    "naming the document type (e.g. "
                    "'board-written-resolution')."
                )
            }
        slug = document_type.strip().lower().replace(" ", "-").replace("_", "-")
        filename = f"{case_id}-{slug}.md"
        md_path = output_dir / filename
        md_path.write_text(markdown, encoding="utf-8")
        return {
            "md_path": str(md_path.resolve()),
            "doc_type": slug,
            "saved_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        }

    return [write_markdown_draft]
