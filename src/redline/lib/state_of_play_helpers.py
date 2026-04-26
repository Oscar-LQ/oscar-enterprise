"""Helper functions for state-of-play change entry creation.

Element-level processing functions that convert individual OOXML
elements (w:ins, w:del, w:r with commentReference) into
TrackedChangeEntry objects. Used by state_of_play.py's document walker.

Source:
- process_insertion, _collect_insertion_text, make_deletion_entry,
  process_comment_ref:
  claude-plugin-mcp/src/ingestion/state_of_play_helpers.py
- extract_run_text, extract_del_text:
  claude-plugin-mcp/src/ingestion/annotated_helpers.py:117-158
  (folded in — only those two helpers used by state_of_play)
See src/redline/lib/__init__.py for the package-level upgrade warning.
"""

from docx.oxml.ns import qn

from src.redline.lib.sdt_unwrapper import iter_effective_children
from src.redline.lib.state_of_play_models import TrackedChangeEntry


def process_insertion(
    ins_element,
    context: str,
    comments_lookup: dict[str, dict],
    entries: list[TrackedChangeEntry],
    change_counter: int,
    comment_counter: int,
) -> tuple[int, int]:
    """Process a w:ins element, creating entries for insertion and nested dels.

    Only creates an insertion entry if the w:ins has actual inserted text
    (not just a wrapper around nested w:del elements). Always processes
    nested w:del children as separate deletion entries. Also checks for
    comment references inside inserted runs.

    Args:
        ins_element: An lxml element with tag w:ins.
        context: The clean paragraph text for paragraph_context.
        comments_lookup: Comment ID to metadata dict.
        entries: Mutable list to append new entries to.
        change_counter: Current Chg:N counter value.
        comment_counter: Current Com:N counter value.

    Returns:
        Tuple of (updated change_counter, updated comment_counter).
    """
    author = (ins_element.get(qn("w:author")) or "").strip()
    date = ins_element.get(qn("w:date")) or ""
    ooxml_id = ins_element.get(qn("w:id")) or ""

    inserted_text = _collect_insertion_text(ins_element)

    if inserted_text:
        change_counter += 1
        entries.append(TrackedChangeEntry(
            change_id=f"Chg:{change_counter}",
            change_type="insertion",
            author=author,
            date=date,
            paragraph_context=context,
            changed_text=inserted_text,
            ooxml_id=ooxml_id,
        ))

    for nested in iter_effective_children(ins_element):
        if nested.tag == qn("w:del"):
            change_counter += 1
            entries.append(make_deletion_entry(
                nested, change_counter, context,
            ))
        elif nested.tag == qn("w:r"):
            comment_counter = process_comment_ref(
                nested, context, comments_lookup, entries,
                comment_counter,
            )

    return change_counter, comment_counter


def _collect_insertion_text(ins_element) -> str:
    """Collect text from w:r children of a w:ins element.

    Extracts text from runs inside the insertion, excluding nested
    w:del elements and comment reference runs.
    """
    text_parts: list[str] = []
    for child in iter_effective_children(ins_element):
        if child.tag == qn("w:r"):
            comment_ref = child.find(qn("w:commentReference"))
            if comment_ref is None:
                text_parts.append(extract_run_text(child))
    return "".join(text_parts)


def make_deletion_entry(
    del_element, change_counter: int, context: str
) -> TrackedChangeEntry:
    """Create a TrackedChangeEntry for a deletion element."""
    author = (del_element.get(qn("w:author")) or "").strip()
    date = del_element.get(qn("w:date")) or ""
    ooxml_id = del_element.get(qn("w:id")) or ""
    deleted_text = extract_del_text(del_element)

    return TrackedChangeEntry(
        change_id=f"Chg:{change_counter}",
        change_type="deletion",
        author=author,
        date=date,
        paragraph_context=context,
        changed_text=deleted_text,
        ooxml_id=ooxml_id,
    )


def process_comment_ref(
    run_element,
    context: str,
    comments_lookup: dict[str, dict],
    entries: list[TrackedChangeEntry],
    comment_counter: int,
) -> int:
    """Check a w:r element for a comment reference and create an entry.

    If the run contains a w:commentReference, looks up the comment in
    the comments lookup and creates a Com:N entry.
    """
    comment_ref = run_element.find(qn("w:commentReference"))
    if comment_ref is None:
        return comment_counter

    comment_id = comment_ref.get(qn("w:id"))
    if not comment_id or comment_id not in comments_lookup:
        return comment_counter

    comment_data = comments_lookup[comment_id]
    comment_counter += 1

    entries.append(TrackedChangeEntry(
        change_id=f"Com:{comment_counter}",
        change_type="comment",
        author=(comment_data.get("author") or "").strip(),
        date=comment_data.get("date") or "",
        paragraph_context=context,
        changed_text=comment_data.get("text") or "",
        ooxml_id=comment_id,
    ))

    return comment_counter


def extract_run_text(run_element) -> str:
    """Extract text from a w:r element's w:t children.

    Handles w:t, w:tab (as space), and w:br (as newline), matching
    the behavior of Adeu's get_run_text but working with raw lxml
    elements instead of python-docx Run objects.
    """
    text_parts: list[str] = []
    for child in run_element:
        if child.tag == qn("w:t"):
            text_parts.append(child.text or "")
        elif child.tag == qn("w:tab"):
            text_parts.append(" ")
        elif child.tag in (qn("w:br"), qn("w:cr")):
            text_parts.append("\n")
    return "".join(text_parts)


def extract_del_text(del_element) -> str:
    """Extract deleted text from a w:del element's w:delText children.

    Walks runs inside a w:del element and reads w:delText elements.
    Does NOT use w:t -- deleted text uses w:delText in OOXML.
    """
    text_parts: list[str] = []
    for run in del_element.findall(qn("w:r")):
        for del_text_element in run.findall(qn("w:delText")):
            if del_text_element.text:
                text_parts.append(del_text_element.text)
    return "".join(text_parts)
