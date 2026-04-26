"""In-memory add-comment operation for the atomic pipeline.

Adds standalone comments to a pre-loaded Document object without any
file I/O. The caller provides a Document, pre-resolved comment tuples,
and an AuthorConfig. This module does NOT call build_state_of_play(),
Document(path), or .save().

Source: claude-plugin-mcp/src/negotiation/add_comments_inplace.py
(verbatim, imports adapted for redline.lib paths).
See src/redline/lib/__init__.py for the package-level upgrade warning.
"""

from docx.document import Document

from src.redline.lib.add_comment_helpers import (
    CommentError,
    anchor_comment_to_text,
    anchor_comment_to_tracked_change,
    create_standalone_comment,
)
from src.redline.lib.author_config import AuthorConfig
from src.redline.lib.comment_ids_helpers import (
    get_or_create_comments_extensible_part,
    get_or_create_comments_ids_part,
)
from src.redline.lib.reply_helpers import (
    allocate_para_id,
    collect_existing_para_ids,
    get_next_comment_id,
    get_or_create_comments_extended_part,
    get_or_create_comments_part,
)
from src.redline.lib.results import ActionOutcome
from src.redline.lib.timestamp import generate_timestamp


def add_comments_on_document(
    document: Document,
    resolutions: list[tuple[str, str, str | None, str | None]],
    author_config: AuthorConfig,
) -> list[ActionOutcome]:
    """Add standalone comments to an in-memory Document.

    Each resolution is (anchor_id, comment_text, ooxml_id_or_none, error_or_none).
    Pre-failed resolutions (error is set) produce failed ActionOutcome.
    Valid resolutions are anchored to tracked changes or text, with comment
    XML created in comments.xml and commentsExtended.xml.
    """
    comments_part = get_or_create_comments_part(document)
    extended_part = get_or_create_comments_extended_part(document)
    ids_part = get_or_create_comments_ids_part(document)
    extensible_part = get_or_create_comments_extensible_part(document)
    existing_ids = collect_existing_para_ids(document)
    next_id = get_next_comment_id(comments_part)
    timestamp = generate_timestamp(author_config.date_override)
    body = document.element.body
    outcomes: list[ActionOutcome] = []

    for anchor_id, comment_text, ooxml_id, error in resolutions:
        if error is not None:
            outcomes.append(ActionOutcome(
                action_type="add_comment",
                target_id=anchor_id,
                status="failed",
                reason=error,
            ))
            continue

        outcome = _apply_single_comment(
            body, comments_part, extended_part, existing_ids,
            next_id, author_config, timestamp,
            anchor_id, comment_text, ooxml_id,
            ids_part=ids_part,
            extensible_part=extensible_part,
        )
        outcomes.append(outcome)
        next_id += 1

    return outcomes


def _apply_single_comment(
    body: object,
    comments_part: object,
    extended_part: object,
    existing_ids: set[str],
    next_id: int,
    author_config: AuthorConfig,
    timestamp: str,
    anchor_id: str,
    comment_text: str,
    ooxml_id: str | None,
    ids_part: object | None = None,
    extensible_part: object | None = None,
) -> ActionOutcome:
    """Apply a single comment, returning an ActionOutcome."""
    try:
        if ooxml_id is not None:
            anchor_comment_to_tracked_change(body, ooxml_id, next_id)
        else:
            anchor_comment_to_text(body, anchor_id, next_id)

        para_id = allocate_para_id(existing_ids, next_id)
        create_standalone_comment(
            comments_part, extended_part, next_id,
            author_config.name, timestamp, comment_text, para_id,
            initials=author_config.initials,
            ids_part=ids_part,
            extensible_part=extensible_part,
        )

        return ActionOutcome(
            action_type="add_comment",
            target_id=anchor_id,
            status="success",
            new_text=comment_text,
        )
    except CommentError as exc:
        return ActionOutcome(
            action_type="add_comment",
            target_id=anchor_id,
            status="failed",
            reason=str(exc),
        )
