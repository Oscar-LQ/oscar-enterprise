"""Sprint 10P — response parser for the counterparty-response pipeline.

Two top-level entry points:

- `parse_decisions_response(content)` — for GPT-5.5 planner output. Looks
  for `{"decisions": [...], "cross_clause_notes": [...]}`. Markdown-fence
  wrapping (commonly emitted by GPT-5.5 family) is stripped at the
  cleanup stage.

- `parse_single_edit_response(content)` — for MiniMax executor output.
  Looks for a bare `{"new_text": ..., "comment": ...}` object (no array
  wrapper since one executor call produces one counter-proposal).

Both reuse the four-layer JSON-recovery cascade ported from
Vibe's ai-bundle.js:414-466 — direct, trailing-comma-fix,
truncation-repair, regex-rescue.

Adapted from sprint-10O/response_parser.py — the JSON cleanup and
four-layer fallback are unchanged; the schema validation is new.
"""
from __future__ import annotations

import json
import re
from typing import Any


# --- shared cleanup / parse helpers --------------------------------------


def try_parse_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _clean_for_json(content: str) -> str:
    """Strip markdown fences, take first {...} block, strip control chars."""
    cleaned = content.strip()
    code_block_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)(?:\n?```|$)", cleaned)
    if code_block_match:
        cleaned = code_block_match.group(1).strip()
    json_match = re.search(r"\{[\s\S]*\}", cleaned)
    if json_match:
        cleaned = json_match.group(0)
    cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", cleaned)
    return cleaned


def _repair_truncated_json(text: str) -> str | None:
    repaired = re.sub(r',\s*"[^"]*":\s*"[^"]*$', "", text)
    if repaired == text:
        repaired = re.sub(r",\s*\{[^}]*$", "", text)

    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in repaired:
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_string:
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append(ch)
        if ch in "}]":
            if stack:
                stack.pop()

    if not stack:
        return None
    closers = "".join("}" if c == "{" else "]" for c in reversed(stack))
    return repaired + closers


def _four_layer_parse(cleaned: str) -> tuple[Any | None, str]:
    """Run the four-layer JSON parse fallback. Returns (parsed, method).

    Layers:
      1. direct
      2. trailing-comma-fix
      3. truncation-repair
      4. regex-rescue (caller-specific; not run here)
    """
    parsed = try_parse_json(cleaned)
    if parsed is not None:
        return parsed, "direct"
    fixed = re.sub(r",\s*([}\]])", r"\1", cleaned)
    parsed = try_parse_json(fixed)
    if parsed is not None:
        return parsed, "trailing-comma-fix"
    repaired = _repair_truncated_json(fixed)
    if repaired is not None:
        parsed = try_parse_json(repaired)
        if parsed is not None:
            return parsed, "truncation-repair"
    return None, "failed"


# --- planner output: decisions list --------------------------------------


_VALID_ACTIONS = {"accept", "counter_propose", "comment", "reply", "no_action"}


def parse_decisions_response(content: str) -> dict[str, Any]:
    """Parse the planner's response into `{decisions, cross_clause_notes, parse_method, raw_content}`.

    `decisions` is a list of NegotiationDecision dicts. Each is validated to
    have at least `change_id` (or `comment_id` for reply / `anchor_change_id`
    for standalone comment) and `action`. Decisions that fail validation
    are skipped with a warning print.

    Layer-4 regex-rescue is not used for decisions — the schema is
    heterogeneous (different fields per action) and the regex would be
    fragile; layers 1-3 cover GPT-5.5's typical output shapes.
    """
    cleaned = _clean_for_json(content)
    parsed, method = _four_layer_parse(cleaned)

    if parsed is None:
        preview = content[:300] + "…" if len(content) > 300 else content
        raise ValueError(
            "Planner response failed all four parse layers.\n\n"
            "Planner returned:\n" + preview
        )

    if not isinstance(parsed, dict):
        raise ValueError(
            f"Planner response is not a JSON object (got {type(parsed).__name__})"
        )

    decisions_raw = parsed.get("decisions")
    if not isinstance(decisions_raw, list):
        raise ValueError(
            f"Planner response missing or invalid `decisions` array "
            f"(got {type(decisions_raw).__name__})"
        )

    cross_notes = parsed.get("cross_clause_notes") or []
    if not isinstance(cross_notes, list):
        cross_notes = []

    valid_decisions: list[dict[str, Any]] = []
    for i, item in enumerate(decisions_raw):
        if not isinstance(item, dict):
            print(f"[10P-PLAN] skipping decisions[{i}]: not a dict ({type(item).__name__})")
            continue

        action = item.get("action")
        if action not in _VALID_ACTIONS:
            print(
                f"[10P-PLAN] skipping decisions[{i}]: invalid action "
                f"{action!r} (valid: {sorted(_VALID_ACTIONS)})"
            )
            continue

        # Per-action shape validation. Missing required fields → skip with print.
        normalised = {"action": action}

        if action == "accept":
            cid = item.get("change_id")
            comment_text = item.get("comment_text")
            if not isinstance(cid, str) or not cid.strip():
                print(f"[10P-PLAN] skipping decisions[{i}] action=accept: missing change_id")
                continue
            if not isinstance(comment_text, str) or not comment_text.strip():
                # Rule 4: accept always carries a comment. Empty → flag and skip.
                print(
                    f"[10P-PLAN] skipping decisions[{i}] action=accept change_id={cid}: "
                    f"missing/empty comment_text (rule 4 requires accept-with-comment)"
                )
                continue
            normalised["change_id"] = cid.strip()
            normalised["comment_text"] = comment_text.strip()

        elif action == "counter_propose":
            cid = item.get("change_id")
            position = item.get("position", "") or ""
            instruction = item.get("instruction", "") or ""
            preserve = item.get("preserve") or []
            comment_text = item.get("comment_text", "") or ""
            if not isinstance(cid, str) or not cid.strip():
                print(f"[10P-PLAN] skipping decisions[{i}] action=counter_propose: missing change_id")
                continue
            if not isinstance(instruction, str) or not instruction.strip():
                print(
                    f"[10P-PLAN] skipping decisions[{i}] action=counter_propose change_id={cid}: "
                    f"missing/empty instruction"
                )
                continue
            if not isinstance(preserve, list):
                preserve = []
            normalised["change_id"] = cid.strip()
            normalised["position"] = str(position).strip()
            normalised["instruction"] = instruction.strip()
            normalised["preserve"] = [str(p) for p in preserve if isinstance(p, (str, int, float))]
            normalised["comment_text"] = str(comment_text).strip()

        elif action == "comment":
            anchor = item.get("anchor_change_id") or item.get("change_id")
            comment_text = item.get("comment_text")
            if not isinstance(anchor, str) or not anchor.strip():
                print(f"[10P-PLAN] skipping decisions[{i}] action=comment: missing anchor_change_id")
                continue
            if not isinstance(comment_text, str) or not comment_text.strip():
                print(
                    f"[10P-PLAN] skipping decisions[{i}] action=comment anchor={anchor}: "
                    f"missing/empty comment_text"
                )
                continue
            normalised["anchor_change_id"] = anchor.strip()
            normalised["comment_text"] = comment_text.strip()

        elif action == "reply":
            cid = item.get("comment_id") or item.get("change_id")
            reply_text = item.get("reply_text") or item.get("text")
            if not isinstance(cid, str) or not cid.strip():
                print(f"[10P-PLAN] skipping decisions[{i}] action=reply: missing comment_id")
                continue
            if not isinstance(reply_text, str) or not reply_text.strip():
                print(
                    f"[10P-PLAN] skipping decisions[{i}] action=reply comment_id={cid}: "
                    f"missing/empty reply_text"
                )
                continue
            normalised["comment_id"] = cid.strip()
            normalised["reply_text"] = reply_text.strip()

        elif action == "no_action":
            cid = item.get("change_id")
            reasoning = item.get("reasoning", "") or ""
            if not isinstance(cid, str) or not cid.strip():
                print(f"[10P-PLAN] skipping decisions[{i}] action=no_action: missing change_id")
                continue
            normalised["change_id"] = cid.strip()
            normalised["reasoning"] = str(reasoning).strip()

        valid_decisions.append(normalised)

    print(
        f"[10P-PLAN] parse_method={method} | decisions={len(valid_decisions)}"
        f" (raw={len(decisions_raw)}) | cross_clause_notes={len(cross_notes)}"
    )

    return {
        "decisions": valid_decisions,
        "cross_clause_notes": cross_notes,
        "parse_method": method,
        "raw_content": content,
    }


# --- executor output: single edit dict -----------------------------------


def parse_single_edit_response(content: str) -> dict[str, Any]:
    """Parse one executor response into `{new_text, comment, parse_method}`.

    Bare-object schema: `{"new_text": str, "comment": str}`. If the executor
    wrapped its single edit in `{"changes": [...]}` or `{"edits": [...]}`
    or `{"new_text": ..., ...}` we unwrap defensively.
    """
    cleaned = _clean_for_json(content)
    parsed, method = _four_layer_parse(cleaned)

    if parsed is None:
        preview = content[:300] + "…" if len(content) > 300 else content
        raise ValueError(
            "Executor response failed all four parse layers.\n\n"
            "Executor returned:\n" + preview
        )

    if not isinstance(parsed, dict):
        raise ValueError(
            f"Executor response is not a JSON object (got {type(parsed).__name__})"
        )

    # Defensive unwrap: occasionally the executor wraps a single edit in
    # `{"changes": [...]}` or `{"edits": [...]}` despite the schema.
    if isinstance(parsed.get("changes"), list) and parsed["changes"]:
        parsed = parsed["changes"][0]
    elif isinstance(parsed.get("edits"), list) and parsed["edits"]:
        parsed = parsed["edits"][0]

    new = parsed.get("new_text", "")
    comment = parsed.get("comment", "") or ""

    if not isinstance(new, str):
        new = str(new)
    if not isinstance(comment, str):
        comment = str(comment)

    return {
        "new_text": new,
        "comment": comment,
        "parse_method": method,
        "raw_content": content,
    }
