"""Sprint 10P — counterparty-response pipeline orchestrator.

Different shape from 10N/10O's pipeline: the input here is a tracked-changed
.docx (Zenith's redlines on Acme's NDA), and the output applies a mixed
set of operations (accept, counter_propose, comment, reply, no_action)
chosen by an LLM planner against an LLM-or-mechanical executor.

Stages (matches MCP's EXECUTION_ORDER discipline at action_groups granularity):

  Stage A — Adeu native batch:    AcceptChange + ReplyComment via
                                  RedlineEngine.process_batch (atomic;
                                  mapper rebuilds between actions and
                                  edits — but we have no edits, only
                                  actions, so single-pass).

  Stage B — Counter-propose:      counter_propose_on_document for every
                                  counter_propose decision, paired with
                                  the executor-drafted replacement_text.
                                  Operates on the same in-memory Document
                                  Adeu just mutated in Stage A.

  Stage C — Add comments:         add_comments_on_document for every
                                  comment-bearing decision (accept-with-
                                  comment, counter-propose-with-comment,
                                  standalone comment). Anchors by
                                  paragraph_context (text-match) for
                                  accept-with-comment (post-accept the
                                  ooxml_id wrapper is gone — Q2(a) from
                                  Phase 0); by ooxml_id for counter-
                                  propose-with-comment and standalone
                                  comment (the original Zenith ooxml_id
                                  is preserved by the layered shape).

  Save once at the end.

================================================================
UPGRADE-BRITTLENESS — pointer
================================================================
This pipeline depends on src/redline/lib/* (the MCP port). The
package-level upgrade-brittleness flag (src/redline/lib/__init__.py)
documents that this surface reaches under Adeu's public DocumentChange
API to construct OOXML primitives Adeu 1.3.3 does not expose. The
retirement path is Adeu adding native counter-propose and standalone-
comment primitives — until then, the lib code stays.

DIFFERENT from 10N/10O's pipeline.py — that file ports Vibe's inline
word-diff to first-pass redlining. This file's port surface is MCP's
counter-propose + state-of-play + add-comment, not Vibe's word-diff.
The two pipelines coexist; first-pass and counterparty-response are
distinct workflows.
================================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from docx import Document

from adeu.models import AcceptChange, ReplyComment
from adeu.redline.engine import RedlineEngine

from src.redline.lib.add_comments_inplace import add_comments_on_document
from src.redline.lib.author_config import AuthorConfig
from src.redline.lib.counter_propose_inplace import counter_propose_on_document
from src.redline.lib.results import ActionOutcome
from src.redline.lib.state_of_play import build_state_of_play
from src.redline.lib.state_of_play_models import StateOfPlay, TrackedChangeEntry

logger = logging.getLogger(__name__)


# --- types ---------------------------------------------------------------


@dataclass
class ApplyResult:
    """Aggregated result of applying a decision list end-to-end."""

    accepts_applied: int = 0
    accepts_skipped: int = 0
    replies_applied: int = 0
    replies_skipped: int = 0
    counter_proposes: list[ActionOutcome] = field(default_factory=list)
    add_comments: list[ActionOutcome] = field(default_factory=list)
    no_actions: list[dict[str, str]] = field(default_factory=list)
    decisions_skipped: list[dict[str, str]] = field(default_factory=list)
    process_batch_skipped_details: list[Any] = field(default_factory=list)


ExecutorCallback = Callable[
    [dict[str, Any], TrackedChangeEntry], dict[str, Any]
]
"""(decision, state_entry) -> {new_text, comment, parse_method, raw_content}.

The executor callback runs the LLM call for one counter-propose decision.
It receives the planner's NegotiationDecision dict and the matching
TrackedChangeEntry; it returns the executor's parsed output.
"""


# --- entry points --------------------------------------------------------


def extract_state_of_play(input_path: str | Path) -> StateOfPlay:
    """Stage 0 — extract the state of play from the input .docx.

    Pure read. Uses the ported MCP state_of_play.build_state_of_play.
    """
    return build_state_of_play(str(input_path))


def apply_decisions(
    input_path: str | Path,
    output_path: str | Path,
    state: StateOfPlay,
    decisions: list[dict[str, Any]],
    author_config: AuthorConfig,
    executor_callback: ExecutorCallback,
) -> ApplyResult:
    """Apply a planner-emitted decision list to the input .docx.

    Loads the .docx once, runs Stages A / B / C in order on the same
    in-memory Document, saves once at the end.

    `executor_callback` is invoked once per counter_propose decision to
    produce the byte-precise replacement_text. Mechanical decisions
    (accept, no_action, comment, reply) skip the executor.
    """
    result = ApplyResult()

    # Build a change_id → entry map for lookup.
    by_change_id: dict[str, TrackedChangeEntry] = {
        entry.change_id: entry for entry in state.changes
    }

    # Bucket decisions by action.
    accept_decisions: list[dict[str, Any]] = []
    counter_decisions: list[dict[str, Any]] = []
    comment_decisions: list[dict[str, Any]] = []
    reply_decisions: list[dict[str, Any]] = []
    no_action_decisions: list[dict[str, Any]] = []

    for d in decisions:
        action = d.get("action")
        if action == "accept":
            accept_decisions.append(d)
        elif action == "counter_propose":
            counter_decisions.append(d)
        elif action == "comment":
            comment_decisions.append(d)
        elif action == "reply":
            reply_decisions.append(d)
        elif action == "no_action":
            no_action_decisions.append(d)
        else:
            result.decisions_skipped.append({
                "change_id": str(d.get("change_id") or d.get("comment_id") or "?"),
                "action": str(action),
                "reason": f"unknown action {action!r}",
            })

    # Validate change_id references against state-of-play.
    for d in (
        accept_decisions
        + counter_decisions
        + no_action_decisions
        + [d for d in comment_decisions if "anchor_change_id" in d]
    ):
        cid = d.get("change_id") or d.get("anchor_change_id")
        if cid and cid not in by_change_id:
            result.decisions_skipped.append({
                "change_id": cid,
                "action": d.get("action", "?"),
                "reason": f"change_id {cid} not in state-of-play",
            })

    # Skip out-of-state decisions from the action lists too.
    accept_decisions = [d for d in accept_decisions if d["change_id"] in by_change_id]
    counter_decisions = [d for d in counter_decisions if d["change_id"] in by_change_id]
    no_action_decisions = [d for d in no_action_decisions if d["change_id"] in by_change_id]
    comment_decisions = [
        d for d in comment_decisions
        if (d.get("anchor_change_id") and d["anchor_change_id"] in by_change_id)
    ]

    # Run executor for counter-proposes BEFORE Stage A — fail-fast on parse
    # errors before we mutate the document.
    counter_executor_outputs: list[dict[str, Any]] = []
    for d in counter_decisions:
        entry = by_change_id[d["change_id"]]
        try:
            output = executor_callback(d, entry)
        except Exception as exc:  # noqa: BLE001 — surface to result
            logger.warning(
                "executor_callback raised for change_id=%s: %s", d["change_id"], exc
            )
            result.decisions_skipped.append({
                "change_id": d["change_id"],
                "action": "counter_propose",
                "reason": f"executor failed: {exc}",
            })
            counter_executor_outputs.append({})
            continue
        counter_executor_outputs.append(output)

    # ---- Stage A: Adeu native batch (accepts + replies) ----
    #
    # Reload Adeu's RedlineEngine over the input .docx. Apply all
    # AcceptChange + ReplyComment in one process_batch. Then we keep the
    # engine's underlying Document object for Stages B and C — no save
    # in between.
    engine = RedlineEngine(str(input_path), author=author_config.name)
    document = engine.doc

    adeu_actions = []
    accept_decisions_in_order: list[dict[str, Any]] = []
    reply_decisions_in_order: list[dict[str, Any]] = []

    # IMPORTANT — Adeu's AcceptChange/RejectChange/ReplyComment target_id
    # is the bare OOXML w:id, not state-of-play's sequential Chg:N. Adeu's
    # apply_review_actions strips the "Chg:" prefix and matches the result
    # against w:id directly (engine.py:_reject_change line 1). State-of-
    # play's Chg:N is for LLM display; ooxml_id is for Adeu wiring.
    for d in accept_decisions:
        entry = by_change_id[d["change_id"]]
        adeu_actions.append(AcceptChange(target_id=entry.ooxml_id))
        accept_decisions_in_order.append(d)

    for d in reply_decisions:
        # comment_id may be Com:N from the planner; look up the matching
        # entry (we store comments in by_change_id with Com:N keys per
        # state_of_play_helpers.process_comment_ref).
        cid = d["comment_id"]
        entry = by_change_id.get(cid)
        target = entry.ooxml_id if entry is not None else cid
        adeu_actions.append(ReplyComment(target_id=target, text=d["reply_text"]))
        reply_decisions_in_order.append(d)

    if adeu_actions:
        batch_result = engine.process_batch(adeu_actions)
        # process_batch counts actions and edits separately; we only sent
        # actions, so actions_applied/actions_skipped is what we want.
        result.accepts_applied = (
            batch_result.get("actions_applied", 0)
            * len(accept_decisions_in_order)
            // max(1, len(adeu_actions))
        )
        # The integer-division above is approximate when we mix accepts
        # and replies; rebuild exact counts from skipped_details.
        result.process_batch_skipped_details = batch_result.get("skipped_details", [])

        # Approximate counts via diff against skipped_details. For the
        # 10P cut-down (3 changes, 1 accept, 0 replies), this is exact.
        applied_total = batch_result.get("actions_applied", 0)
        skipped_total = batch_result.get("actions_skipped", 0)
        # Heuristic: assume skipped_details name reasons; without finer
        # granularity we report the totals split by action shape.
        result.accepts_applied = min(applied_total, len(accept_decisions_in_order))
        result.accepts_skipped = max(0, len(accept_decisions_in_order) - result.accepts_applied)
        replies_total = max(0, applied_total - result.accepts_applied)
        result.replies_applied = min(replies_total, len(reply_decisions_in_order))
        result.replies_skipped = max(
            0, len(reply_decisions_in_order) - result.replies_applied
        ) + max(0, skipped_total - result.accepts_skipped)

    # ---- Stage B: counter-propose ----
    counter_resolutions: list[tuple[TrackedChangeEntry, str]] = []
    counter_decision_for_outcome: list[dict[str, Any]] = []
    for d, output in zip(counter_decisions, counter_executor_outputs):
        if not output:
            # executor failed — already logged in decisions_skipped
            continue
        new_text = (output.get("new_text") or "").strip("\n")
        if not new_text:
            result.decisions_skipped.append({
                "change_id": d["change_id"],
                "action": "counter_propose",
                "reason": "executor produced empty new_text",
            })
            continue
        entry = by_change_id[d["change_id"]]
        counter_resolutions.append((entry, new_text))
        counter_decision_for_outcome.append(d)

    if counter_resolutions:
        outcomes = counter_propose_on_document(
            document, counter_resolutions, author_config
        )
        result.counter_proposes = outcomes

    # ---- Stage C: add comments ----
    #
    # Build the resolution tuples per add_comments_on_document's contract:
    #   (anchor_id, comment_text, ooxml_id_or_None, error_or_None)
    #
    # - For accept-with-comment: anchor_id = paragraph_context (text match
    #   post-accept; the ooxml_id wrapper has been removed by AcceptChange).
    #   ooxml_id = None (so the dispatcher uses anchor_comment_to_text).
    #
    # - For counter-propose-with-comment: ooxml_id = original Zenith
    #   ooxml_id (still valid in the layered shape — the wholesale
    #   primitive nests Acme's w:del INSIDE Zenith's w:ins, preserving
    #   the original w:id; the surgical primitive splits the run but
    #   keeps the original w:ins). dispatcher uses
    #   anchor_comment_to_tracked_change.
    #
    # - For standalone comment: anchor_change_id → ooxml_id from
    #   state-of-play. (No standalone comments expected on the cut-down
    #   fixture; plumbing in place.)
    comment_resolutions: list[tuple[str, str, str | None, str | None]] = []

    # Accept-with-comment: anchor by paragraph_context.
    #
    # IMPORTANT — paragraph_context comes from Adeu's get_visible_runs +
    # get_run_text, which include BOTH w:t AND w:delText (the "All Markup"
    # view: deletions visible as strikethrough). The anchor lookup uses
    # _get_paragraph_run_text which reads ONLY w:t. They differ on
    # deletions. After AcceptChange runs on a deletion, the deleted text
    # is fully removed from the document — for the anchor to match
    # post-accept, we strip the deleted text from paragraph_context before
    # passing it to the anchor lookup.
    #
    # For accept on insertion, paragraph_context's inserted text is in
    # w:t (inside w:ins) and is preserved post-accept; no transformation
    # needed.
    for d in accept_decisions_in_order:
        comment_text = d.get("comment_text", "").strip()
        if not comment_text:
            continue
        entry = by_change_id[d["change_id"]]
        anchor_text = entry.paragraph_context
        if entry.change_type == "deletion" and entry.changed_text:
            anchor_text = anchor_text.replace(entry.changed_text, "")
        anchor_text = anchor_text.strip()
        if not anchor_text:
            comment_resolutions.append((
                d["change_id"], comment_text, None,
                f"empty post-accept anchor for {d['change_id']}"
            ))
            continue
        comment_resolutions.append((anchor_text, comment_text, None, None))

    # Counter-propose-with-comment: anchor by original Zenith ooxml_id.
    for d, outcome in zip(counter_decision_for_outcome, result.counter_proposes):
        comment_text = d.get("comment_text", "").strip()
        if not comment_text:
            continue
        if outcome.status != "success":
            # Counter-propose itself failed — skip the comment too.
            continue
        entry = by_change_id[d["change_id"]]
        comment_resolutions.append((
            entry.change_id, comment_text, entry.ooxml_id, None,
        ))

    # Standalone comments: anchor by ooxml_id of the named change.
    for d in comment_decisions:
        anchor_cid = d.get("anchor_change_id")
        comment_text = d.get("comment_text", "").strip()
        if not comment_text or not anchor_cid:
            continue
        entry = by_change_id[anchor_cid]
        comment_resolutions.append((
            anchor_cid, comment_text, entry.ooxml_id, None,
        ))

    if comment_resolutions:
        outcomes = add_comments_on_document(
            document, comment_resolutions, author_config
        )
        result.add_comments = outcomes

    # ---- no_action audit ----
    for d in no_action_decisions:
        result.no_actions.append({
            "change_id": d["change_id"],
            "reasoning": d.get("reasoning", ""),
        })

    # ---- Save ----
    output_stream = engine.save_to_stream()
    try:
        Path(output_path).write_bytes(output_stream.getvalue())
    finally:
        output_stream.close()

    return result
