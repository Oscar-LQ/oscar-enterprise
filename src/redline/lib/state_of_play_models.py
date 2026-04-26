"""State-of-play data models — TrackedChangeEntry, StateOfPlay, AuthorInfo.

Pydantic models for the structured representation of a tracked-changed
.docx document. State-of-play extraction (state_of_play.py) produces
these; the planner LLM consumes them; the dispatcher resolves change_id
references against them.

Source:
- TrackedChangeEntry, StateOfPlay: claude-plugin-mcp/src/models/change.py
- AuthorInfo, AuthorSummary: claude-plugin-mcp/src/models/party.py
(Merged into one file because both surfaces are small and tightly coupled.)
See src/redline/lib/__init__.py for the package-level upgrade warning.
"""

from typing import Literal

from pydantic import BaseModel, computed_field


class AuthorInfo(BaseModel):
    """Summary of a single unique author found in tracked changes.

    Captures the author's name, change counts by type, and the date
    range of their activity. The total_changes computed property
    returns the sum of all change types.
    """

    name: str
    insertion_count: int = 0
    deletion_count: int = 0
    comment_count: int = 0
    earliest_date: str = ""
    latest_date: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_changes(self) -> int:
        """Sum of insertion, deletion, and comment counts."""
        return self.insertion_count + self.deletion_count + self.comment_count


class AuthorSummary(BaseModel):
    """All authors found in the document with their change statistics.

    Provides a structured list of authors sorted by total changes
    (descending) and a to_prompt() method that formats this data
    for the LLM to read during role assignment or context-setting.
    """

    authors: list[AuthorInfo]

    def to_prompt(self) -> str:
        """Format the author list as a human-readable string."""
        lines = ["Authors found in document:"]
        for author in self.authors:
            lines.append(
                f"  - {author.name}: {author.total_changes} changes "
                f"({author.insertion_count} ins, "
                f"{author.deletion_count} del, "
                f"{author.comment_count} comments), "
                f"active {author.earliest_date} to {author.latest_date}"
            )
        return "\n".join(lines)


class TrackedChangeEntry(BaseModel):
    """A single pending tracked change in the document.

    Each entry represents one insertion, deletion, or comment that
    has not yet been accepted. The change_id uses the convention
    Chg:N for tracked changes and Com:N for comments. The party_role
    field defaults to 'unknown' and is populated by the LLM after
    role assignment.
    """

    change_id: str
    change_type: Literal["insertion", "deletion", "comment"]
    author: str
    date: str
    party_role: str = "unknown"
    paragraph_context: str
    changed_text: str
    ooxml_id: str = ""
    replies: list["TrackedChangeEntry"] = []


class StateOfPlay(BaseModel):
    """Complete negotiation state of a document.

    Combines the author summary with a flat list of all pending
    tracked changes. The pending_count property returns the total
    number of unresolved changes.
    """

    authors: list[AuthorInfo]
    changes: list[TrackedChangeEntry]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pending_count(self) -> int:
        """Number of pending tracked changes in the document."""
        return len(self.changes)
