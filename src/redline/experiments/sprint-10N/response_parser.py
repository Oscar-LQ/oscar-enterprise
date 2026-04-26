"""Sprint 10N — response parser adapted from 10M's verbatim port of Vibe.

Single behavioural change vs 10M: the data contract in 10N's user
message uses `{"changes": [...]}` as the top-level key (per the
sprint brief's data contract note), where 10M's Vibe port used
`{"edits": [...]}`. This parser looks for `changes` first, then
falls back to `edits` for any LLM that ignores the data contract
and follows training defaults. Everything else is unchanged from
10M.

Four-layer fallback structure preserved:
  1. direct       — JSON.parse after markdown fence + control-char strip
  2. trailing-comma-fix — remove trailing commas before `}` / `]`
  3. truncation-repair  — close open brackets at the end
  4. regex-rescue — pattern-extract individual edit objects
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
