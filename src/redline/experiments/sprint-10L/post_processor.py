"""Sprint 10L post-processor — port of CPM's document-vs-new diff mechanism.

Takes 10K's LLM-emitted edit list `[{target_text, new_text, comment}]` and
narrows each edit via the same mechanism Claude-Plugin-MCP uses internally:

    1. Find target_text in the on-disk document (three-layer matcher).
    2. Extract runs_plain_text from the matched runs.
    3. Compute diff_words(runs_plain_text, new_text).
    4. Group diff ops into modify blocks bounded by long EQUAL runs.
    5. Emit one narrower ModifyText per block, anchored for unique match.

The ported code (``diff_words``, ``find_match_three_layer``,
``PlainTextIndex``, and the small helpers they need) is copied VERBATIM from
CPM where copied, with minimal adaptation: ``from adeu import DocumentEdit``
replaced with ``from adeu import ModifyText`` per the Adeu 0.7.x → 1.1.0
rename (Sprint 10K Finding A). CPM source locations are cited at each copied
block.

Sprint 10L does NOT port CPM's OOXML construction or DOM surgery (those
couple to Adeu-private ``engine._create_track_change_tag`` and
``mapper._build_map()``). Instead, narrowed blocks are applied via Adeu's
public ``RedlineEngine.process_batch`` — the substrate adaptation documented
in the approved plan.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from adeu import ModifyText
from adeu.redline.engine import RedlineEngine
from adeu.redline.mapper import DocumentMapper
from diff_match_patch import diff_match_patch


# ---------------------------------------------------------------------------
# Ported verbatim from claude-plugin-mcp/src/pipeline/word_diff.py
# ---------------------------------------------------------------------------

def diff_words(
    old_text: str,
    new_text: str,
) -> list[tuple[int, str]]:
    """Produce word-level diff segments between old_text and new_text.

    Uses token encoding: each word or whitespace chunk maps to a unique
    Unicode character (starting at U+0100). diff_match_patch operates on
    the encoded strings, then results are decoded back to word-level text.

    Returns a list of (op, text) tuples where:
        op = -1: DELETE (text present in old, absent in new)
        op =  0: EQUAL  (text unchanged)
        op =  1: INSERT (text absent in old, present in new)
    """
    token_regex = re.compile(r"\S+|\s+")
    old_tokens = token_regex.findall(old_text) if old_text else []
    new_tokens = token_regex.findall(new_text) if new_text else []

    if not old_tokens and not new_tokens:
        return []

    encoded_old, encoded_new, char_to_token = _encode_tokens(
        old_tokens, new_tokens,
    )

    dmp = diff_match_patch()
    diffs = dmp.diff_main(encoded_old, encoded_new)
    dmp.diff_cleanupSemantic(diffs)

    return _decode_diffs(diffs, char_to_token)


def verify_reconstruction(
    diffs: list[tuple[int, str]],
    expected_new_text: str,
) -> bool:
    """Check whether INSERT + EQUAL segments reassemble to expected text."""
    reconstructed = "".join(text for op, text in diffs if op >= 0)
    return reconstructed == expected_new_text


def _encode_tokens(
    old_tokens: list[str],
    new_tokens: list[str],
) -> tuple[str, str, dict[str, str]]:
    """Map word/whitespace tokens to unique Unicode characters."""
    token_to_char: dict[str, str] = {}
    char_to_token: dict[str, str] = {}
    next_code = 0x100

    def encode(tokens: list[str]) -> str:
        nonlocal next_code
        chars: list[str] = []
        for token in tokens:
            if token not in token_to_char:
                char = chr(next_code)
                token_to_char[token] = char
                char_to_token[char] = token
                next_code += 1
            chars.append(token_to_char[token])
        return "".join(chars)

    return encode(old_tokens), encode(new_tokens), char_to_token


def _decode_diffs(
    diffs: list[tuple[int, str]],
    char_to_token: dict[str, str],
) -> list[tuple[int, str]]:
    """Decode encoded diff output back to word-level text segments."""
    result: list[tuple[int, str]] = []
    for op, encoded_text in diffs:
        decoded = "".join(char_to_token[c] for c in encoded_text)
        if decoded:
            result.append((op, decoded))
    return result


# ---------------------------------------------------------------------------
# Ported from claude-plugin-mcp/src/pipeline/plain_text_index.py
# (Adapted: no Adeu imports needed; reads only mapper.spans public attribute)
# ---------------------------------------------------------------------------

class PlainTextIndex:
    """Formatting-marker-aware position mapping for resilient matching.

    Iterates mapper.spans, keeping only spans where span.run is not None.
    Builds a position map from plain-text indices to mapper full_text
    indices. CPM uses this as the third fallback layer after
    DocumentMapper.find_match_index (exact → smart-quote → fuzzy regex) and
    the clean-view mapper.
    """

    __slots__ = ("plain_text", "_plain_to_full")

    def __init__(self, mapper) -> None:
        plain_chars: list[str] = []
        pos_map: list[int] = []

        for span in mapper.spans:
            if span.run is None:
                continue
            for i, ch in enumerate(span.text):
                plain_chars.append(ch)
                pos_map.append(span.start + i)

        self.plain_text = "".join(plain_chars)
        self._plain_to_full = pos_map

    def find_match(self, target_text: str) -> tuple[int, int]:
        """Search plain_text for target_text with three fallback strategies."""
        idx = self._search(target_text)
        if idx == -1:
            return -1, 0
        return self._map_range(idx, len(target_text))

    def _search(self, target_text: str) -> int:
        idx = self.plain_text.find(target_text)
        if idx != -1:
            return idx
        normalized_plain = _normalize_quotes(self.plain_text)
        normalized_target = _normalize_quotes(target_text)
        idx = normalized_plain.find(normalized_target)
        if idx != -1:
            return idx
        return _fuzzy_regex_search(self.plain_text, target_text)

    def _map_range(
        self, plain_start: int, plain_len: int,
    ) -> tuple[int, int]:
        if not self._plain_to_full:
            return -1, 0
        full_start = self._plain_to_full[plain_start]
        end_idx = min(
            plain_start + plain_len - 1,
            len(self._plain_to_full) - 1,
        )
        full_end = self._plain_to_full[end_idx] + 1
        return full_start, full_end - full_start


def _normalize_quotes(text: str) -> str:
    return (
        text.replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )


def _fuzzy_regex_search(text: str, target_text: str) -> int:
    try:
        pattern = _make_fuzzy_regex(target_text)
        match = re.search(pattern, text)
        return match.start() if match else -1
    except re.error:
        return -1


def _make_fuzzy_regex(target_text: str) -> str:
    target_text = _normalize_quotes(target_text)
    parts: list[str] = []
    token_pattern = re.compile(r"(_+)|(\s+)|(['\"])")
    last = 0
    for match in token_pattern.finditer(target_text):
        literal = target_text[last : match.start()]
        if literal:
            parts.append(re.escape(literal))
        group_under, group_space, group_quote = match.groups()
        if group_under:
            parts.append(r"_+")
        elif group_space:
            parts.append(r"\s+")
        elif group_quote:
            parts.append(
                r"[‘’']" if group_quote == "'"
                else r"[“”\"]",
            )
        last = match.end()
    tail = target_text[last:]
    if tail:
        parts.append(re.escape(tail))
    return "".join(parts)


# ---------------------------------------------------------------------------
# Ported from claude-plugin-mcp/src/pipeline/surgical_helpers.py:40-69
# (Unchanged — depends only on engine.mapper / engine.clean_mapper / engine.doc,
#  all public Adeu 1.1.0 attributes.)
# ---------------------------------------------------------------------------

def find_match_three_layer(
    engine,
    target_text: str,
) -> tuple[object, int, int]:
    """Try full mapper, clean mapper, then PlainTextIndex to find target.

    Returns (active_mapper, start_idx, match_len). If no match found,
    returns (None, -1, 0).
    """
    mapper = engine.mapper
    start_idx, match_len = mapper.find_match_index(target_text)
    if start_idx != -1:
        return mapper, start_idx, match_len

    if not engine.clean_mapper:
        engine.clean_mapper = DocumentMapper(engine.doc, clean_view=True)
    start_idx, match_len = engine.clean_mapper.find_match_index(target_text)
    if start_idx != -1:
        return engine.clean_mapper, start_idx, match_len

    pti = PlainTextIndex(engine.mapper)
    start_idx, match_len = pti.find_match(target_text)
    if start_idx != -1:
        return engine.mapper, start_idx, match_len

    return None, -1, 0


# ---------------------------------------------------------------------------
# 10L-original: block grouping + anchor widening + top-level orchestration.
# ---------------------------------------------------------------------------

@dataclass
class NarrowedEdit:
    """One narrower edit produced by the post-processor.

    Carries both the Adeu-bound ModifyText and the pre-anchoring raw target /
    new / block op trace — the latter are kept for transcript inspection.
    """
    target_text: str
    new_text: str
    comment: str | None
    raw_target: str
    raw_new: str
    op_trace: list[tuple[int, str]]
    anchor_tokens_prepended: int
    anchor_tokens_appended: int

    def to_modify_text(self) -> ModifyText:
        return ModifyText(
            target_text=self.target_text,
            new_text=self.new_text,
            comment=self.comment,
        )


def _tokenize(text: str) -> list[str]:
    """Split text into \\S+|\\s+ tokens (matching diff_words's tokeniser)."""
    return re.findall(r"\S+|\s+", text)


def _count_content_tokens(text: str) -> int:
    """Count non-whitespace tokens (per \\S+|\\s+ tokenisation)."""
    return sum(1 for t in _tokenize(text) if not t.isspace())


def _group_into_blocks_with_context(
    diffs: list[tuple[int, str]],
    short_equal_threshold_tokens: int,
) -> list[tuple[list[tuple[int, str]], list[str], list[str]]]:
    """Walk diffs; emit (block_ops, eq_before_tokens, eq_after_tokens) triples.

    A block is the run of diff ops between two long-EQUAL separators (or
    between a long-EQUAL and a document boundary). EQUAL ops with
    < short_equal_threshold_tokens content tokens are absorbed into the
    block as unchanged interior text. Blocks with no DELETE/INSERT op are
    dropped.

    eq_before_tokens and eq_after_tokens are the tokens of the long-EQUAL
    separators bounding the block — available for anchor-widening.
    """
    long_eq_indices: list[int] = []
    for i, (op, text) in enumerate(diffs):
        if op == 0 and _count_content_tokens(text) >= short_equal_threshold_tokens:
            long_eq_indices.append(i)

    boundaries = [-1] + long_eq_indices + [len(diffs)]

    results: list[tuple[list[tuple[int, str]], list[str], list[str]]] = []
    for b_idx in range(len(boundaries) - 1):
        start = boundaries[b_idx] + 1
        end = boundaries[b_idx + 1]
        block_ops = [(op, text) for op, text in diffs[start:end]]

        if not any(op != 0 for op, _ in block_ops):
            continue

        eq_before_tokens = (
            _tokenize(diffs[boundaries[b_idx]][1])
            if boundaries[b_idx] >= 0 else []
        )
        eq_after_tokens = (
            _tokenize(diffs[boundaries[b_idx + 1]][1])
            if boundaries[b_idx + 1] < len(diffs) else []
        )

        results.append((block_ops, eq_before_tokens, eq_after_tokens))

    return results


def _anchor_block(
    block_ops: list[tuple[int, str]],
    eq_before_tokens: list[str],
    eq_after_tokens: list[str],
    mapper_full_text: str,
    max_widening_tokens: int = 10,
) -> tuple[str, str, int, int]:
    """Build a uniquely-matchable (target_text, new_text) pair for a block.

    Widens with preceding / following EQUAL tokens until the target is
    unique in mapper_full_text. Returns
        (narrowed_target, narrowed_new, prepended_count, appended_count).
    """
    raw_target = "".join(text for op, text in block_ops if op != 1)
    raw_new = "".join(text for op, text in block_ops if op != -1)

    eq_before = list(eq_before_tokens)
    eq_after = list(eq_after_tokens)

    # Pure-insertion case: target is empty or whitespace-only.
    if not raw_target.strip():
        anchor_suffix = ""
        prepended = 0
        while eq_before and prepended < max_widening_tokens:
            token = eq_before.pop()
            anchor_suffix = token + anchor_suffix
            prepended += 1
            if anchor_suffix.strip() and mapper_full_text.count(anchor_suffix) == 1:
                return anchor_suffix, anchor_suffix + raw_new, prepended, 0
        raise RuntimeError(
            "pure insertion: could not find a unique preceding anchor "
            f"within {max_widening_tokens} tokens",
        )

    narrowed_target = raw_target
    narrowed_new = raw_new
    prepended = 0
    appended = 0

    while prepended + appended < max_widening_tokens:
        count = mapper_full_text.count(narrowed_target)
        if count == 1:
            return narrowed_target, narrowed_new, prepended, appended
        if eq_before:
            token = eq_before.pop()
            narrowed_target = token + narrowed_target
            narrowed_new = token + narrowed_new
            prepended += 1
            continue
        if eq_after:
            token = eq_after.pop(0)
            narrowed_target = narrowed_target + token
            narrowed_new = narrowed_new + token
            appended += 1
            continue
        break

    final_count = mapper_full_text.count(narrowed_target)
    if final_count != 1:
        raise RuntimeError(
            f"could not uniquely anchor block target within "
            f"{max_widening_tokens} tokens: target={narrowed_target!r} "
            f"has {final_count} matches in document",
        )
    return narrowed_target, narrowed_new, prepended, appended


def narrow_edits(
    parsed_edits: list[dict],
    nda_bytes: bytes,
    *,
    short_equal_threshold_tokens: int = 2,
    max_widening_tokens: int = 10,
) -> list[NarrowedEdit]:
    """Top-level: apply CPM's find + diff mechanism to each parsed edit.

    Returns a list of NarrowedEdit records. The caller converts each to
    ModifyText and applies via RedlineEngine.process_batch.

    Mechanism (per the approved plan):
        1. find_match_three_layer(engine, edit.target_text) locates the
           target in the on-disk document.
        2. runs_plain_text is extracted from the matched runs.
        3. diff_words(runs_plain_text, edit.new_text) produces word-level
           diff segments.
        4. Segments are grouped into blocks at long-EQUAL boundaries.
        5. Each block is anchored for unique match and emitted as a
           narrowed edit.
    """
    engine = RedlineEngine(io.BytesIO(nda_bytes))
    narrowed: list[NarrowedEdit] = []

    for edit in parsed_edits:
        target_text = edit["target_text"]
        new_text = edit.get("new_text") or ""
        comment = edit.get("comment")

        mapper, start_idx, match_len = find_match_three_layer(engine, target_text)
        if start_idx == -1:
            raise RuntimeError(
                "find_match_three_layer could not locate target_text: "
                f"{target_text[:80]!r}"
            )

        target_runs = mapper.find_target_runs_by_index(start_idx, match_len)
        runs_plain_text = "".join(run.text or "" for run in target_runs)

        diffs = diff_words(runs_plain_text, new_text)
        if not verify_reconstruction(diffs, new_text):
            raise RuntimeError(
                "verify_reconstruction failed — INSERT+EQUAL segments do "
                "not reassemble to new_text; likely encoding collision"
            )

        blocks = _group_into_blocks_with_context(
            diffs, short_equal_threshold_tokens,
        )

        for i, (block_ops, eq_before, eq_after) in enumerate(blocks):
            raw_target = "".join(text for op, text in block_ops if op != 1)
            raw_new = "".join(text for op, text in block_ops if op != -1)

            narrowed_target, narrowed_new, prepended, appended = _anchor_block(
                block_ops, eq_before, eq_after,
                mapper_full_text=mapper.full_text,
                max_widening_tokens=max_widening_tokens,
            )

            narrowed.append(NarrowedEdit(
                target_text=narrowed_target,
                new_text=narrowed_new,
                comment=comment if i == 0 else None,
                raw_target=raw_target,
                raw_new=raw_new,
                op_trace=list(block_ops),
                anchor_tokens_prepended=prepended,
                anchor_tokens_appended=appended,
            ))

    return narrowed
