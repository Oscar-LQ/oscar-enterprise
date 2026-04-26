"""Author extraction from tracked change metadata in .docx documents.

Walks OOXML elements (w:ins, w:del, w:comment) to discover all unique
authors and their change statistics. Returns an AuthorSummary that
the LLM can use to assign party roles during negotiation.

Source: claude-plugin-mcp/src/ingestion/author_extractor.py (verbatim,
imports adapted to redline.lib paths).
See src/redline/lib/__init__.py for the package-level upgrade warning.
"""

from collections import defaultdict

from docx import Document
from docx.oxml.ns import qn

from adeu.utils.docx import iter_document_parts

from src.redline.lib.comment_loader import load_comments
from src.redline.lib.sdt_unwrapper import iter_effective_children
from src.redline.lib.state_of_play_models import AuthorInfo, AuthorSummary


def extract_authors_from_document(document: Document) -> AuthorSummary:
    """Extract all unique authors from an already-opened Document.

    Walks all document parts for tracked change elements, loads comments,
    and builds an AuthorSummary with per-author insertion, deletion, and
    comment counts plus date ranges. Used by build_state_of_play (which
    shares the Document).
    """
    author_stats = _collect_tracked_change_stats(document)
    _collect_comment_stats(document, author_stats)

    authors = _build_author_list(author_stats)
    return AuthorSummary(authors=authors)


def _collect_tracked_change_stats(
    document: Document,
) -> dict[str, dict]:
    """Walk all document parts and count tracked changes per author."""
    author_stats: dict[str, dict] = defaultdict(
        lambda: {"insertions": 0, "deletions": 0, "comments": 0, "dates": []}
    )

    for part in iter_document_parts(document):
        for paragraph in part.paragraphs:
            for child in iter_effective_children(paragraph._element):
                if child.tag == qn("w:ins"):
                    _record_insertion(child, author_stats)
                elif child.tag == qn("w:del"):
                    _record_deletion(child, author_stats)

    return author_stats


def _record_insertion(
    ins_element, author_stats: dict[str, dict]
) -> None:
    """Record an insertion element and any nested deletions."""
    author = (ins_element.get(qn("w:author")) or "").strip()
    date = ins_element.get(qn("w:date")) or ""

    if author:
        author_stats[author]["insertions"] += 1
        if date:
            author_stats[author]["dates"].append(date)

    for nested in iter_effective_children(ins_element):
        if nested.tag == qn("w:del"):
            _record_deletion(nested, author_stats)


def _record_deletion(
    del_element, author_stats: dict[str, dict]
) -> None:
    """Record a deletion element (top-level or nested)."""
    author = (del_element.get(qn("w:author")) or "").strip()
    date = del_element.get(qn("w:date")) or ""

    if author:
        author_stats[author]["deletions"] += 1
        if date:
            author_stats[author]["dates"].append(date)


def _collect_comment_stats(
    document: Document, author_stats: dict[str, dict]
) -> None:
    """Load comments and add comment counts to author stats."""
    comments = load_comments(document)
    for comment_data in comments.values():
        author = (comment_data.get("author") or "").strip()
        date = comment_data.get("date") or ""
        if author:
            author_stats[author]["comments"] += 1
            if date:
                author_stats[author]["dates"].append(date)


def _build_author_list(
    author_stats: dict[str, dict],
) -> list[AuthorInfo]:
    """Convert raw stats dictionaries into sorted AuthorInfo objects."""
    authors: list[AuthorInfo] = []

    for name, stats in author_stats.items():
        dates = sorted(stats["dates"])
        earliest = dates[0] if dates else ""
        latest = dates[-1] if dates else ""

        authors.append(
            AuthorInfo(
                name=name,
                insertion_count=stats["insertions"],
                deletion_count=stats["deletions"],
                comment_count=stats["comments"],
                earliest_date=earliest,
                latest_date=latest,
            )
        )

    authors.sort(key=lambda a: a.total_changes, reverse=True)
    return authors
