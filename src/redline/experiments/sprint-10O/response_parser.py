"""Sprint 10O — response parser for the planner-executor pipeline.

Three top-level entry points:

- `parse_plan_response(content)` — for GPT-5.5 planner output. Looks
  for `{"plan": [...], "cross_clause_notes": [...]}`. Markdown-fence
  wrapping (commonly emitted by GPT-5.5 family) is stripped at the
  cleanup stage; this is expected behaviour, not a parser failure.

- `parse_single_edit_response(content)` — for MiniMax executor output.
  Looks for a bare `{"target_text": ..., "new_text": ..., "comment": ...}`
  object (no array wrapper since one executor call produces one edit).

- `parse_ai_response(content)` — kept verbatim from 10N for backwards
  compatibility; not used by 10O. Looks for `{"changes": [...]}` with
  fallback to `{"edits": [...]}`.

All three reuse the four-layer JSON-recovery cascade ported from
Vibe's ai-bundle.js:414-466 — direct, trailing-comma-fix,
truncation-repair, regex-rescue.
"""
from __future__ import annotations

import json
import re
from typing import Any


# --- top-level entry -----------------------------------------------------


def parse_ai_response(content: str) -> dict[str, Any]:
    """Parse an AI response into `{edits, summary, reasoning, parse_method, raw_content}`.

    Mirrors ai-bundle.js:414-466. Returns a dict with:
        edits       -- list of {target_text, new_text, comment, rule,
                       edit_type} dicts (validated)
        summary     -- str
        reasoning   -- object or string or None
        parse_method -- "direct" | "trailing-comma-fix" |
                       "truncation-repair" | "regex-rescue"
        raw_content -- the verbatim `content` argument (for artefact capture)
    """
    cleaned = content.strip()

    # ai-bundle.js:418-419 — strip ```json fences
    code_block_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)(?:\n?```|$)", cleaned)
    if code_block_match:
        cleaned = code_block_match.group(1).strip()

    # ai-bundle.js:421-422 — take the first {...} block
    json_match = re.search(r"\{[\s\S]*\}", cleaned)
    if json_match:
        cleaned = json_match.group(0)

    # ai-bundle.js:424 — strip control characters
    cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", cleaned)

    # Layer 1 — direct parse
    parsed = try_parse_json(cleaned)
    if parsed is not None:
        result = validate_edits(parsed)
        result["parse_method"] = "direct"
        result["raw_content"] = content
        _log_parse_result("direct", result)
        return result

    # Layer 2 — trailing-comma fix
    fixed_commas = re.sub(r",\s*([}\]])", r"\1", cleaned)
    parsed2 = try_parse_json(fixed_commas)
    if parsed2 is not None:
        result = validate_edits(parsed2)
        result["parse_method"] = "trailing-comma-fix"
        result["raw_content"] = content
        _log_parse_result("trailing-comma-fix", result)
        return result

    # Layer 3 — truncation repair
    repaired = repair_truncated_json(fixed_commas)
    if repaired is not None:
        parsed3 = try_parse_json(repaired)
        if parsed3 is not None:
            result = validate_edits(parsed3)
            result["parse_method"] = "truncation-repair"
            result["raw_content"] = content
            _log_parse_result("truncation-repair", result)
            return result

    # Layer 4 — regex rescue
    rescued = rescue_edits(cleaned)
    if rescued:
        result = {
            "edits": rescued,
            "summary": f"Recovered {len(rescued)} edits from malformed response",
            "reasoning": None,
            "parse_method": "regex-rescue",
            "raw_content": content,
        }
        _log_parse_result("regex-rescue", result)
        return result

    preview = content[:200] + "…" if len(content) > 200 else content
    raise ValueError(
        "Failed to parse AI response. Try a different model or simplify the "
        "playbook.\n\nAI returned: " + preview
    )


def _log_parse_result(method: str, result: dict[str, Any]) -> None:
    # ai-bundle.js logs via console.log; we print (structlog-silenced at
    # caller) to keep Vibe's telemetry pattern visible.
    print(
        f"[VL-DEBUG] AI response parsed | parseMethod={method} | "
        f"editCount={len(result.get('edits', []))}"
    )


# --- helpers -------------------------------------------------------------


def try_parse_json(text: str) -> Any | None:
    """ai-bundle.js:468-470 — JSON.parse or null."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def validate_edits(parsed: Any) -> dict[str, Any]:
    """ai-bundle.js:472-531 verbatim port.

    Filters `parsed.edits` to keep only entries with string `target_text`
    and `new_text`. Trims `target_text`. Defaults `edit_type` to
    "MISALIGNMENT", other metadata to "". Extracts `reasoning` from
    primary key or four alt-key names.
    """
    edits_raw = None
    source_key = None
    if isinstance(parsed, dict):
        if isinstance(parsed.get("changes"), list):
            edits_raw = parsed["changes"]
            source_key = "changes"
        elif isinstance(parsed.get("edits"), list):
            edits_raw = parsed["edits"]
            source_key = "edits"
            print("[VL-DEBUG] Top-level key is 'edits' — LLM defaulted to Vibe-style schema")
    if not isinstance(edits_raw, list):
        return {
            "edits": [],
            "summary": "Invalid response format - no changes/edits array",
            "reasoning": None,
            "source_key": None,
        }

    valid_edits: list[dict[str, Any]] = []
    for edit in edits_raw:
        if not isinstance(edit, dict):
            continue
        t = edit.get("target_text")
        n = edit.get("new_text")
        if not isinstance(t, str) or not isinstance(n, str):
            continue
        valid_edits.append(
            {
                "rule": edit.get("rule") or "",
                "edit_type": edit.get("edit_type") or "MISALIGNMENT",
                "target_text": t.strip(),
                "new_text": n,
                "comment": edit.get("comment") or "",
            }
        )

    result: dict[str, Any] = {
        "edits": valid_edits,
        "summary": parsed.get("summary") or f"Found {len(valid_edits)} suggested changes",
        "reasoning": None,
        "source_key": source_key,
    }

    # ai-bundle.js:487-526 — reasoning extraction with four alt-key names
    reasoning = parsed.get("reasoning")
    if not reasoning and parsed.get("analysis"):
        reasoning = {
            "analysis": parsed["analysis"],
            "document_summary": parsed.get("document_summary") or "",
            "playbook_rules_found": parsed.get("playbook_rules_found"),
        }
        print("[VL-DEBUG] AI placed analysis at top level — restructured into reasoning object")

    if reasoning is not None:
        if isinstance(reasoning, dict):
            # ai-bundle.js:497-503 — alt-key names
            if not reasoning.get("analysis") and isinstance(reasoning.get("rules"), list):
                reasoning["analysis"] = reasoning["rules"]
            elif not reasoning.get("analysis") and isinstance(reasoning.get("assessments"), list):
                reasoning["analysis"] = reasoning["assessments"]
            elif not reasoning.get("analysis") and isinstance(reasoning.get("entries"), list):
                reasoning["analysis"] = reasoning["entries"]

            if isinstance(reasoning.get("analysis"), list):
                result["reasoning"] = reasoning
                statuses = [a.get("status") for a in reasoning["analysis"] if isinstance(a, dict)]
                status_counts: dict[str, int] = {}
                for s in statuses:
                    status_counts[s] = status_counts.get(s, 0) + 1
                print(
                    f"[VL-DEBUG] AI reasoning (structured) | "
                    f"document_summary={(reasoning.get('document_summary') or '')[:200]!r} | "
                    f"topics={len(reasoning['analysis'])} | statuses={status_counts}"
                )
            else:
                result["reasoning"] = json.dumps(reasoning)
                print(
                    "[VL-DEBUG] AI reasoning is object but has no analysis array, keys: "
                    + str(list(reasoning.keys()))
                )
        elif isinstance(reasoning, str):
            result["reasoning"] = reasoning
            print(f"[VL-DEBUG] AI reasoning (string): {reasoning[:500]}")
        else:
            result["reasoning"] = json.dumps(reasoning)
            print(f"[VL-DEBUG] AI reasoning (other): {type(reasoning).__name__}")
    else:
        print("[VL-DEBUG] AI response missing reasoning field — model may have skipped structured analysis")

    gap_count = sum(1 for e in valid_edits if e["edit_type"] == "GAP")
    misalign_count = sum(1 for e in valid_edits if e["edit_type"] == "MISALIGNMENT")
    print(
        f"[VL-DEBUG] Edit types | GAP={gap_count} | MISALIGNMENT={misalign_count} | "
        f"total={len(valid_edits)}"
    )
    return result


def repair_truncated_json(text: str) -> str | None:
    """ai-bundle.js:533-552 verbatim port.

    Removes an incomplete trailing key or object, then balances open
    brackets by appending matching closers.
    """
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


# ai-bundle.js:556 — the full rescue regex for `{rule?, edit_type?, target_text, new_text, comment?}`
_RESCUE_PATTERN = re.compile(
    r'\{\s*'
    r'(?:"rule"\s*:\s*"(?:[^"\\]|\\.)*"\s*,\s*)?'
    r'(?:"edit_type"\s*:\s*"(?:[^"\\]|\\.)*"\s*,\s*)?'
    r'"target_text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*'
    r'"new_text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*'
    r'(?:,\s*"comment"\s*:\s*"((?:[^"\\]|\\.)*)")?'
    r'\s*\}'
)


def rescue_edits(text: str) -> list[dict[str, Any]]:
    """ai-bundle.js:554-570 verbatim port.

    Extract edits by regex against a possibly-malformed response body.
    Uses JSON.parse on individual string literals to decode escape
    sequences (matches JS JSON.parse('"' + capture + '"')).
    """
    edits: list[dict[str, Any]] = []
    for m in _RESCUE_PATTERN.finditer(text):
        try:
            target = json.loads('"' + m.group(1) + '"').strip()
            new_text = json.loads('"' + m.group(2) + '"')
            comment = json.loads('"' + m.group(3) + '"') if m.group(3) else ""
            edits.append(
                {
                    "rule": "",
                    "edit_type": "MISALIGNMENT",
                    "target_text": target,
                    "new_text": new_text,
                    "comment": comment,
                }
            )
        except (json.JSONDecodeError, ValueError):
            # ai-bundle.js:565 — skip malformed edit
            continue
    return edits


# --- 10O additions: plan + single-edit parsers ---------------------------


def _clean_for_json(content: str) -> str:
    """Strip markdown fences, take first {...} block, strip control chars.

    Same cleanup as parse_ai_response. GPT-5.5 family commonly wraps
    JSON output in ```json ... ``` fences — the fence-strip handles it.
    """
    cleaned = content.strip()
    code_block_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)(?:\n?```|$)", cleaned)
    if code_block_match:
        cleaned = code_block_match.group(1).strip()
    json_match = re.search(r"\{[\s\S]*\}", cleaned)
    if json_match:
        cleaned = json_match.group(0)
    cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", cleaned)
    return cleaned


def _four_layer_parse(cleaned: str) -> tuple[Any | None, str]:
    """Run the four-layer JSON parse fallback. Returns (parsed, method).

    method is one of: 'direct', 'trailing-comma-fix', 'truncation-repair',
    or 'failed' (parsed is None when failed). 'regex-rescue' is not
    used here because it's edit-shape-specific (handled in callers
    that know the edit shape).
    """
    parsed = try_parse_json(cleaned)
    if parsed is not None:
        return parsed, "direct"
    fixed = re.sub(r",\s*([}\]])", r"\1", cleaned)
    parsed = try_parse_json(fixed)
    if parsed is not None:
        return parsed, "trailing-comma-fix"
    repaired = repair_truncated_json(fixed)
    if repaired is not None:
        parsed = try_parse_json(repaired)
        if parsed is not None:
            return parsed, "truncation-repair"
    return None, "failed"


def parse_plan_response(content: str) -> dict[str, Any]:
    """Parse the planner's response into `{plan, cross_clause_notes, parse_method, raw_content}`.

    `plan` is a list of instruction dicts. Each instruction is
    validated to have at least the required string fields (id, clause,
    instruction); missing optional fields are defaulted. Instructions
    that fail validation are skipped with a warning print.
    """
    cleaned = _clean_for_json(content)
    parsed, method = _four_layer_parse(cleaned)

    if parsed is None:
        preview = content[:300] + "…" if len(content) > 300 else content
        raise ValueError(
            "Planner response failed all four parse layers.\n\nPlanner returned:\n" + preview
        )

    if not isinstance(parsed, dict):
        raise ValueError(
            f"Planner response is not a JSON object (got {type(parsed).__name__})"
        )

    plan_raw = parsed.get("plan")
    if not isinstance(plan_raw, list):
        raise ValueError(
            f"Planner response missing or invalid `plan` array (got {type(plan_raw).__name__})"
        )

    cross_notes = parsed.get("cross_clause_notes") or []
    if not isinstance(cross_notes, list):
        cross_notes = []

    valid_plan: list[dict[str, Any]] = []
    for i, item in enumerate(plan_raw):
        if not isinstance(item, dict):
            print(f"[10O-PLAN] skipping plan[{i}]: not a dict ({type(item).__name__})")
            continue
        pid = item.get("id")
        clause = item.get("clause")
        instruction = item.get("instruction")
        if not isinstance(pid, str) or not pid.strip():
            print(f"[10O-PLAN] skipping plan[{i}]: missing/empty id")
            continue
        if not isinstance(instruction, str) or not instruction.strip():
            print(f"[10O-PLAN] skipping plan[{i}] (id={pid}): missing/empty instruction")
            continue
        valid_plan.append({
            "id": pid.strip(),
            "clause": str(clause) if clause is not None else "",
            "position": item.get("position", "") or "",
            "instruction": instruction.strip(),
            "preserve": item.get("preserve") or [],
            "comment_for_partner": item.get("comment_for_partner", "") or "",
            "depends_on": item.get("depends_on") or [],
        })

    print(
        f"[10O-PLAN] parse_method={method} | instructions={len(valid_plan)}"
        f" (raw={len(plan_raw)}) | cross_clause_notes={len(cross_notes)}"
    )

    return {
        "plan": valid_plan,
        "cross_clause_notes": cross_notes,
        "parse_method": method,
        "raw_content": content,
    }


def parse_single_edit_response(content: str) -> dict[str, Any]:
    """Parse one executor response into `{target_text, new_text, comment, parse_method}`.

    Bare object schema: `{"target_text": str, "new_text": str, "comment": str}`.
    Empty / missing fields are tolerated (defaulted to empty string)
    so the apply step can decide what to do.
    """
    cleaned = _clean_for_json(content)
    parsed, method = _four_layer_parse(cleaned)

    if parsed is None:
        preview = content[:300] + "…" if len(content) > 300 else content
        raise ValueError(
            "Executor response failed all four parse layers.\n\nExecutor returned:\n" + preview
        )

    if not isinstance(parsed, dict):
        raise ValueError(
            f"Executor response is not a JSON object (got {type(parsed).__name__})"
        )

    # If the executor wrapped a single edit in {"changes": [...]} or {"edits": [...]},
    # unwrap it (defensive; happens occasionally with structured-output trained models).
    if isinstance(parsed.get("changes"), list) and parsed["changes"]:
        parsed = parsed["changes"][0]
    elif isinstance(parsed.get("edits"), list) and parsed["edits"]:
        parsed = parsed["edits"][0]

    target = parsed.get("target_text", "")
    new = parsed.get("new_text", "")
    comment = parsed.get("comment", "") or ""

    if not isinstance(target, str):
        target = str(target)
    if not isinstance(new, str):
        new = str(new)
    if not isinstance(comment, str):
        comment = str(comment)

    return {
        "target_text": target.strip(),
        "new_text": new,
        "comment": comment,
        "parse_method": method,
        "raw_content": content,
    }
