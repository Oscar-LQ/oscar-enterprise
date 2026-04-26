"""ActionOutcome record for counter-propose and add-comment operations.

Captures per-action result (success / skipped / failed) with optional
before/after text diffs. Used by counter_propose_inplace and
add_comments_inplace as their per-call return shape.

Adeu native primitives (AcceptChange / ReplyComment via process_batch)
return their own dict shape from process_batch — Oscar's dispatcher
in Phase 2 keeps both surfaces side-by-side rather than wrapping them
into a uniform type (Q1 in port-targets §7).

Source: claude-plugin-mcp/src/pipeline/results.py:17-37 (ActionOutcome
only; StylerReport / PipelineResult / PipelineValidationError omitted —
not used in 10P scope).
See src/redline/lib/__init__.py for the package-level upgrade warning.
"""

from typing import Literal

from pydantic import BaseModel


class ActionOutcome(BaseModel):
    """Result of executing a single negotiation action.

    Attributes:
        action_type: Type of action executed (e.g. "counter_propose").
        target_id: ID of the change targeted (e.g. "Chg:1").
        status: Whether the action succeeded, was skipped, or failed.
        reason: Explanation for skipped/failed status. Empty for success.
        original_text: Text before the action was applied. Empty if N/A.
        new_text: Text after the action was applied. Empty if N/A.
        method: How the action was applied ("surgical", "wholesale").
            Empty for non-counter-propose actions or when not applicable.
    """

    action_type: str
    target_id: str
    status: Literal["success", "skipped", "failed"]
    reason: str = ""
    original_text: str = ""
    new_text: str = ""
    method: str = ""
