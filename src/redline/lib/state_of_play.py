"""State-of-play builder for tracked changes in .docx documents.

Produces a flat list of all pending tracked changes with sequential
Chg:N and Com:N IDs, including type, author, date, paragraph context,
and changed text. Downstream phases (planner, dispatcher) consume
this list to act on individual changes by ID.

Source:
- build_state_of_play, _walk_document_for_changes, _get_paragraph_context:
  claude-plugin-mcp/src/ingestion/state_of_play.py
- IngestionError, validate_docx_path:
  claude-plugin-mcp/src/ingestion/validation.py (folded in — small)
See src/redline/lib/__init__.py for the package-level upgrade warning.
"""

from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from adeu.utils.docx import (
    get_paragraph_prefix,
    get_run_text,
    get_visible_runs,
    iter_document_parts,
)

from src.redline.lib.author_extractor import extract_authors_from_document
from src.redline.lib.comment_loader import (
    load_comments,
    load_comments_extended,
)
from src.redline.lib.reply_attachment import attach_reply_comments
from src.redline.lib.sdt_unwrapper import iter_effective_children
from src.redline.lib.state_of_play_helpers import (
    extract_del_text,
    make_deletion_entry,
    process_comment_ref,
    process_insertion,
)
from src.redline.lib.state_of_play_models import StateOfPlay, TrackedChangeEntry


class IngestionError(Exception):
    """Raised when document ingestion fails.

    Source: claude-plugin-mcp/src/ingestion/validation.py (folded in).
    """


def validate_docx_path(file_path: str) -> Path:
    """Validate that a file path points to an existing .docx file.

    Source: claude-plugin-mcp/src/ingestion/validation.py:19-52 (folded in).

    Returns:
        Resolved absolute Path to the validated file.

    Raises:
        IngestionError: If the path is invalid, the file is missing,
            or the extension is not .docx.
    """
    path = Path(file_path).resolve()

    raw_parts = Path(file_path).parts
    if ".." in raw_parts:
        raise IngestionError("Invalid file path")

    if not path.exists():
        raise IngestionError(f"File not found: {path.name}")

    if path.suffix.lower() != ".docx":
        raise IngestionError(f"Not a .docx file: {path.name}")

    return path


def build_state_of_play(file_path: str) -> StateOfPlay:
    """Build the complete negotiation state of play from a .docx document.

    Walks all document parts, extracts every pending tracked change and
    comment as a TrackedChangeEntry with a sequential Chg:N or Com:N ID.
    Also extracts the author summary. Returns a StateOfPlay combining both.
    """
    validated_path = validate_docx_path(file_path)
    document = Document(str(validated_path))

    author_summary = extract_authors_from_document(document)
    comments_lookup = load_comments(document)
    extended_lookup = load_comments_extended(document)

    entries, comment_counter = _walk_document_for_changes(
        document, comments_lookup
    )
    attach_reply_comments(
        entries, comments_lookup, extended_lookup, comment_counter
    )
    return StateOfPlay(authors=author_summary.authors, changes=entries)


def _walk_document_for_changes(
    document: Document, comments_lookup: dict[str, dict]
) -> tuple[list[TrackedChangeEntry], int]:
    """Walk all document parts and collect tracked change entries.

    Iterates paragraphs in document order. For each paragraph, checks
    child elements for w:ins, w:del, and w:r with comment references.
    Returns entries in document order with sequential IDs, plus the
    final comment counter for reply attachment.
    """
    entries: list[TrackedChangeEntry] = []
    change_counter = 0
    comment_counter = 0

    for part in iter_document_parts(document):
        for paragraph in part.paragraphs:
            context = _get_paragraph_context(paragraph)

            for child in iter_effective_children(paragraph._element):
                if child.tag == qn("w:ins"):
                    change_counter, comment_counter = process_insertion(
                        child, context, comments_lookup, entries,
                        change_counter, comment_counter,
                    )
                elif child.tag == qn("w:del"):
                    change_counter += 1
                    entries.append(make_deletion_entry(
                        child, change_counter, context,
                    ))
                elif child.tag == qn("w:r"):
                    comment_counter = process_comment_ref(
                        child, context, comments_lookup, entries,
                        comment_counter,
                    )

    return entries, comment_counter


def _get_paragraph_context(paragraph) -> str:
    """Get the clean accepted-all text of a paragraph for context.

    Uses Adeu's get_visible_runs and get_run_text for the accepted-all
    view, prefixed with any numbering or list marker. Falls back to
    deleted text when the paragraph consists entirely of deletions
    (full-clause deletion), since the accepted-all view would be empty.
    """
    prefix = get_paragraph_prefix(paragraph)
    runs = get_visible_runs(paragraph)
    text = "".join(get_run_text(r) for r in runs)
    context = prefix + text

    if context.strip():
        return context

    deleted_parts: list[str] = []
    for child in iter_effective_children(paragraph._element):
        if child.tag == qn("w:del"):
            deleted_parts.append(extract_del_text(child))
    return "".join(deleted_parts)
