"""Sprint 10J — three-stage deterministic edit decomposition pipeline.

Stage 1 (draft): single MiniMax ``chat_model.invoke`` call. Given §9's
verbatim text and the transformation instruction naming the five LCIA
elements, the model returns a JSON object with ``current_text`` (echoed)
and ``replacement_text`` (drafted). No tools, no agent loop.

Stage 2 (diff): pure Python. Word-level diff of prompted current vs.
drafted replacement via diff-match-patch with Unicode token encoding.
Block-grouping into narrow ``ModifyText`` edits. Uniqueness widening
against the full document's clean-view plain text.

Stage 3 (apply): direct ``RedlineEngine.process_batch``. No @tool
wrappers, no make_redline_tools factory — the edits are already narrow
and discrete by construction.

Each stage's output is a verifiable artefact; failures are diagnosable
by which artefact was produced last.
"""
from __future__ import annotations

import io
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from adeu import ModifyText, RedlineEngine, extract_text_from_stream
from diff_match_patch import diff_match_patch
from langchain_core.messages import HumanMessage, SystemMessage

from llm.chat_model import get_chat_model

# ---------------------------------------------------------------------------
# Constants — pinned for single-attempt discipline
# ---------------------------------------------------------------------------

# Verbatim §9 text — byte-identical to build_input.py CLAUSES[8][1].
# Stage 2 uses this as ground truth regardless of the model's echo.
CURRENT_CLAUSE_9 = (
    "This Agreement and any dispute or claim arising out of or "
    "in connection with it or its subject matter or formation "
    "(including non-contractual disputes or claims) shall be "
    "governed by and construed in accordance with the laws of "
    "England and Wales. The parties submit to the exclusive "
    "jurisdiction of the courts of England and Wales for the "
    "resolution of all disputes arising out of or in connection "
    "with this Agreement."
)

SYSTEM_PROMPT = """\
You are a legal drafter. Your task is to draft a replacement clause.

You will be given the verbatim text of Clause 9 of an NDA governed by the laws
of England and Wales. The client wants the dispute-resolution mechanism
changed from court litigation to binding LCIA arbitration with these five
elements named explicitly:

  (1) the seat of arbitration shall be London;
  (2) the arbitration shall be conducted under the LCIA Rules;
  (3) the tribunal shall consist of a sole arbitrator;
  (4) the language of the arbitration shall be English;
  (5) the award shall be final and binding on the parties.

The governing-law sentence (first sentence of the clause) must remain in
force; only the dispute-resolution mechanism changes.

Output a single JSON object, nothing else:

  {"current_text": "<the Clause 9 text you were given, echoed verbatim>",
   "replacement_text": "<your drafted replacement Clause 9 text>"}

Return only the JSON. No prose before or after. No markdown fences.\
"""

# Stage 2 hyperparameters (decided at plan time; not iterated).
SHORT_EQUAL_GAP_TOKENS = 2          # EQUAL ops shorter than this absorb into adjacent block.
MAX_UNIQUENESS_WIDEN_TOKENS = 8     # Max ±tokens of equal-context to add per side before erroring.
PURE_INSERT_ANCHOR_TOKENS = 5       # Trailing tokens of preceding EQUAL op used as prefix-match anchor.

AUTHOR = "Oscar"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Edit:
    """Intermediate edit representation — one per block-group in the diff.

    ``kind`` names the block shape (modify / pure_delete / pure_insert);
    ``target_text`` and ``new_text`` are Adeu-ready; ``anchor_tokens`` is
    diagnostic (how many trailing EQUAL tokens formed the anchor for a
    pure-insert, or 0 otherwise). ``left_context`` / ``right_context``
    record how much equal-context widening was used for uniqueness
    (both start at 0; widening bumps them up).
    """

    kind: Literal["modify", "pure_delete", "pure_insert"]
    target_text: str
    new_text: str
    anchor_tokens: int = 0
    left_context: int = 0
    right_context: int = 0

    def to_adeu(self) -> ModifyText:
        return ModifyText(target_text=self.target_text, new_text=self.new_text)

    def to_jsonl(self) -> dict:
        return {
            "kind": self.kind,
            "target_text": self.target_text,
            "new_text": self.new_text,
            "anchor_tokens": self.anchor_tokens,
            "left_context_widen": self.left_context,
            "right_context_widen": self.right_context,
            "target_words": len(self.target_text.split()),
            "new_text_words": len(self.new_text.split()),
        }


@dataclass
class DraftResult:
    """Stage 1 output + echo-integrity report."""

    raw_response: str
    parsed_current_text: str
    parsed_replacement_text: str
    normalised_replacement_text: str
    echo_matches_prompt: bool
    echo_diff_note: str = ""

    def to_json(self) -> dict:
        return {
            "raw_response": self.raw_response,
            "parsed_current_text": self.parsed_current_text,
            "parsed_replacement_text": self.parsed_replacement_text,
            "normalised_replacement_text": self.normalised_replacement_text,
            "echo_matches_prompt": self.echo_matches_prompt,
            "echo_diff_note": self.echo_diff_note,
            "prompt_current_text": CURRENT_CLAUSE_9,
        }


# ---------------------------------------------------------------------------
# Stage 1 — Draft
# ---------------------------------------------------------------------------


def stage1_draft() -> DraftResult:
    """Single MiniMax invocation; parse JSON; normalise replacement_text."""

    chat_model = get_chat_model(env_prefix="OSCAR_LLM_REDLINE_EXECUTOR")
    response = chat_model.invoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=CURRENT_CLAUSE_9),
        ]
    )
    raw = response.content if isinstance(response.content, str) else str(response.content)

    parsed = _parse_draft_json(raw)
    current_text = parsed["current_text"]
    replacement_text = parsed["replacement_text"]

    echo_matches = current_text == CURRENT_CLAUSE_9
    echo_diff_note = "" if echo_matches else _describe_echo_diff(CURRENT_CLAUSE_9, current_text)

    normalised = _normalise_text(replacement_text)

    return DraftResult(
        raw_response=raw,
        parsed_current_text=current_text,
        parsed_replacement_text=replacement_text,
        normalised_replacement_text=normalised,
        echo_matches_prompt=echo_matches,
        echo_diff_note=echo_diff_note,
    )


def _parse_draft_json(raw: str) -> dict:
    """Parse the model's JSON. Strip ```json fences once if needed, else error."""
    stripped = raw.strip()
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        # Single recovery attempt: strip ```json fences (or plain ```).
        unwrapped = _strip_markdown_fences(stripped)
        if unwrapped == stripped:
            raise RuntimeError(
                "Stage 1 JSON parse failed (no markdown fences to strip): "
                f"{stripped[:200]!r}..."
            )
        try:
            obj = json.loads(unwrapped)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Stage 1 JSON parse failed after stripping markdown fences: "
                f"{exc}; unwrapped starts with {unwrapped[:200]!r}"
            ) from exc

    if not isinstance(obj, dict):
        raise RuntimeError(f"Stage 1 output is not a JSON object: {type(obj).__name__}")
    for key in ("current_text", "replacement_text"):
        if key not in obj or not isinstance(obj[key], str):
            raise RuntimeError(
                f"Stage 1 JSON missing/invalid required field {key!r}; "
                f"got keys {list(obj.keys())}"
            )
    return obj


_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*?)\n```$", re.DOTALL)


def _strip_markdown_fences(text: str) -> str:
    m = _FENCE_RE.match(text.strip())
    return m.group(1).strip() if m else text


def _normalise_text(text: str) -> str:
    """NFKC + smart-quote/dash/NBSP → ASCII-equivalents.

    Applied to ``replacement_text`` only. Adeu's matcher normalises
    smart-quote variants on ``target_text`` but not on ``new_text``; if
    the model emits U+2019 apostrophes or U+2013 en-dashes, un-normalised
    they would produce OOXML w:ins with inconsistent typography vs the
    surrounding NDA.
    """
    out = unicodedata.normalize("NFKC", text)
    replacements = {
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "“": '"', "”": '"', "„": '"', "‟": '"',
        "–": "-", "—": "-", "−": "-",
        " ": " ",
    }
    for bad, good in replacements.items():
        out = out.replace(bad, good)
    return out


def _describe_echo_diff(expected: str, actual: str) -> str:
    """Short human-readable diff summary for the draft artefact."""
    if len(expected) != len(actual):
        return (
            f"lengths differ: prompt={len(expected)} chars, "
            f"echo={len(actual)} chars"
        )
    # Lengths match but content differs — find first divergence.
    for i, (a, b) in enumerate(zip(expected, actual)):
        if a != b:
            window = 20
            lo, hi = max(0, i - window), min(len(expected), i + window)
            return (
                f"first difference at char {i}: "
                f"prompt={expected[lo:hi]!r} vs echo={actual[lo:hi]!r}"
            )
    return "identical-length but diff function saw no char mismatch (unreachable)"


# ---------------------------------------------------------------------------
# Stage 2 — Word-diff and block-group
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"\S+|\s+")


def stage2_diff(current_text: str, replacement_text: str, input_docx_path: Path) -> list[Edit]:
    """Word-diff + block-group + uniqueness widen + coupling check.

    Raises on reconstruction mismatch, uniqueness failure, or cross-edit
    anchor-substring collision — each a diagnosable Outcome B.
    """

    diffs = _diff_words(current_text, replacement_text)
    if not _verify_reconstruction(diffs, replacement_text):
        raise RuntimeError(
            "Stage 2 reconstruction mismatch — diff output does not "
            "reassemble to replacement_text. Diff correctness failure."
        )

    # Single-pass block grouping with short-EQUAL absorption.
    # Each Edit carries its surrounding long-EQUAL context for later widening.
    edits_with_ctx = _build_edits(diffs, SHORT_EQUAL_GAP_TOKENS)

    # Uniqueness widening against the full document clean-view plain text.
    with open(input_docx_path, "rb") as f:
        doc_plain_text = extract_text_from_stream(
            io.BytesIO(f.read()), filename=input_docx_path.name, clean_view=True
        )

    edits: list[Edit] = []
    for edit, pre_eq, post_eq in edits_with_ctx:
        _widen_edit_for_uniqueness(edit, pre_eq, post_eq, doc_plain_text)
        edits.append(edit)

    _check_cross_edit_coupling(edits)

    return edits


def _diff_words(old: str, new: str) -> list[tuple[int, str]]:
    """Word-level diff via Unicode token encoding + diff_cleanupSemanticLossless.

    Mirrors Claude-Plugin-MCP's approach but reimplemented here — deliberately
    avoids diff_cleanupSemantic (merges adjacent ops across short equal gaps,
    widening blocks) in favour of diff_cleanupSemanticLossless (moves edits
    to better word boundaries without changing content).
    """
    old_tokens = _TOKEN_RE.findall(old)
    new_tokens = _TOKEN_RE.findall(new)

    if not old_tokens and not new_tokens:
        return []

    token_to_char: dict[str, str] = {}
    char_to_token: dict[str, str] = {}
    next_code = 0x100

    def encode(tokens: list[str]) -> str:
        nonlocal next_code
        chars: list[str] = []
        for tok in tokens:
            if tok not in token_to_char:
                ch = chr(next_code)
                token_to_char[tok] = ch
                char_to_token[ch] = tok
                next_code += 1
            chars.append(token_to_char[tok])
        return "".join(chars)

    encoded_old = encode(old_tokens)
    encoded_new = encode(new_tokens)

    dmp = diff_match_patch()
    raw = dmp.diff_main(encoded_old, encoded_new)
    dmp.diff_cleanupSemanticLossless(raw)

    decoded: list[tuple[int, str]] = []
    for op, encoded_text in raw:
        text = "".join(char_to_token[c] for c in encoded_text)
        if text:
            decoded.append((op, text))
    return decoded


def _verify_reconstruction(diffs: list[tuple[int, str]], expected_new: str) -> bool:
    """EQUAL + INSERT segments must reassemble to the expected new text."""
    return "".join(t for op, t in diffs if op >= 0) == expected_new


def _count_content_tokens(text: str) -> int:
    """Number of non-whitespace tokens in text (whitespace-only doesn't count)."""
    return sum(1 for t in _TOKEN_RE.findall(text) if not t.isspace())


def _build_edits(
    diffs: list[tuple[int, str]], short_equal_gap_tokens: int
) -> list[tuple[Edit, str, str]]:
    """Walk diffs once; emit (Edit, preceding_long_equal, following_long_equal).

    A block is a maximal run of non-EQUAL ops, possibly bridged by short
    EQUAL ops (< ``short_equal_gap_tokens`` content tokens). A long EQUAL
    terminates the current block and provides context for the next.
    Within a block, ``target_text`` is DEL+EQ concatenated (what exists in
    the old document); ``new_text`` is INS+EQ concatenated (what exists in
    the new document). EQ text shared by both sides is not duplicated — it
    appears once on each side, matching the physical layout.

    Trailing short EQUAL with no non-EQ op after it acts as a block
    terminator (we don't absorb it; it becomes the following context).
    """
    results: list[tuple[Edit, str, str]] = []
    current_block: list[tuple[int, str]] = []
    preceding_eq = ""

    def has_non_eq_after(idx: int) -> bool:
        for j in range(idx + 1, len(diffs)):
            if diffs[j][0] != 0:
                return True
        return False

    for i, (op, text) in enumerate(diffs):
        if op != 0:
            current_block.append((op, text))
            continue

        # op == 0 — equal span.
        if not current_block:
            # No active block — this is context before the next block.
            preceding_eq = text
            continue

        content_tokens = _count_content_tokens(text)
        is_short = content_tokens < short_equal_gap_tokens

        if is_short and has_non_eq_after(i):
            # Short equal flanked by further non-eq ops: absorb into block.
            current_block.append((op, text))
            continue

        # Terminate current block.
        edit = _block_ops_to_edit(current_block, preceding_eq, text)
        if edit is not None:
            results.append((edit, preceding_eq, text))
        current_block = []
        preceding_eq = text

    # Trailing block (diff ends without a terminal equal).
    if current_block:
        edit = _block_ops_to_edit(current_block, preceding_eq, "")
        if edit is not None:
            results.append((edit, preceding_eq, ""))

    return results


def _block_ops_to_edit(
    block_ops: list[tuple[int, str]],
    preceding_equal_text: str,
    following_equal_text: str,
) -> Edit | None:
    """Classify a block (list of ops) and build the corresponding Edit.

    ``target_text`` = concatenation of DEL + EQ texts in block order (the
    block's projection onto the old document).
    ``new_text`` = concatenation of INS + EQ texts in block order (the
    block's projection onto the new document).
    """
    target_text = "".join(text for op, text in block_ops if op != 1)
    new_text = "".join(text for op, text in block_ops if op != -1)

    has_del = any(op == -1 for op, _ in block_ops)
    has_ins = any(op == 1 for op, _ in block_ops)

    if not has_del and not has_ins:
        return None

    if has_del and has_ins:
        return Edit(kind="modify", target_text=target_text, new_text=new_text)
    if has_del:
        return Edit(kind="pure_delete", target_text=target_text, new_text="")

    # Pure insert — target_text is only EQ content (should be empty if the
    # block is pure INS + no absorbed EQ). Need a real anchor from surrounding
    # context. Prefer preceding; fall back to following.
    anchor, tokens = _tail_anchor(preceding_equal_text, PURE_INSERT_ANCHOR_TOKENS)
    if anchor:
        return Edit(
            kind="pure_insert",
            target_text=anchor,
            new_text=anchor + new_text,
            anchor_tokens=tokens,
        )
    anchor, tokens = _head_anchor(following_equal_text, PURE_INSERT_ANCHOR_TOKENS)
    if anchor:
        return Edit(
            kind="pure_insert",
            target_text=anchor,
            new_text=new_text + anchor,
            anchor_tokens=tokens,
        )
    raise RuntimeError(
        "Stage 2: pure-insert block has no preceding or following EQUAL op "
        "with tokens to anchor on. This shape should not arise when diffing "
        "two non-empty versions of the same clause."
    )


def _tail_anchor(equal_text: str, max_content_tokens: int) -> tuple[str, int]:
    """Return a suffix of equal_text containing up to max_content_tokens content tokens, ending on a non-whitespace token."""
    tokens = _TOKEN_RE.findall(equal_text)
    # Walk backwards, collecting until we've got max_content_tokens content tokens.
    acc: list[str] = []
    content_count = 0
    for tok in reversed(tokens):
        if acc and content_count >= max_content_tokens and not tok.isspace():
            break
        acc.insert(0, tok)
        if not tok.isspace():
            content_count += 1
    # Trim trailing whitespace so the anchor ends on a non-whitespace token.
    while acc and acc[-1].isspace():
        acc.pop()
    return "".join(acc), content_count


def _head_anchor(equal_text: str, max_content_tokens: int) -> tuple[str, int]:
    """Return a prefix of equal_text containing up to max_content_tokens content tokens, starting on a non-whitespace token."""
    tokens = _TOKEN_RE.findall(equal_text)
    acc: list[str] = []
    content_count = 0
    for tok in tokens:
        if acc and content_count >= max_content_tokens and not tok.isspace():
            break
        acc.append(tok)
        if not tok.isspace():
            content_count += 1
    # Trim leading whitespace so the anchor starts on a non-whitespace token.
    while acc and acc[0].isspace():
        acc.pop(0)
    return "".join(acc), content_count


def _widen_edit_for_uniqueness(
    edit: Edit,
    preceding_equal: str,
    following_equal: str,
    doc_plain_text: str,
) -> None:
    """Extend target_text with adjacent EQUAL context until unique in doc plain text.

    Mutates ``edit`` in place. Walks outward by one content token at a
    time, alternating left and right. Errors if still non-unique after
    MAX_UNIQUENESS_WIDEN_TOKENS tokens each side.
    """
    # Pure-insert: anchor must already be unique; widening changes the
    # inserted content's location, so if non-unique we error out.
    if edit.kind == "pure_insert":
        occ = _count_occurrences(doc_plain_text, edit.target_text)
        if occ != 1:
            raise RuntimeError(
                f"Stage 2 uniqueness failure (pure_insert): anchor "
                f"{edit.target_text!r} occurs {occ}× in document plain text. "
                "See plan §Stage 2 for rationale."
            )
        return

    occ = _count_occurrences(doc_plain_text, edit.target_text)
    if occ == 1:
        return

    # Available widening tokens: trailing tokens of the preceding equal, and
    # leading tokens of the following equal.
    left_tokens = list(reversed(_TOKEN_RE.findall(preceding_equal)))
    right_tokens = _TOKEN_RE.findall(following_equal)

    left_used_idx = 0
    right_used_idx = 0
    left_content = 0
    right_content = 0

    prefix = ""
    suffix = ""

    def current_target() -> str:
        return prefix + edit.target_text + suffix

    def _take_left_one_content() -> bool:
        """Take tokens from the end of preceding_equal until one content token is consumed."""
        nonlocal prefix, left_used_idx, left_content
        if left_content >= MAX_UNIQUENESS_WIDEN_TOKENS:
            return False
        took_content = False
        while left_used_idx < len(left_tokens):
            tok = left_tokens[left_used_idx]
            prefix = tok + prefix
            left_used_idx += 1
            if not tok.isspace():
                left_content += 1
                took_content = True
                break
        return took_content

    def _take_right_one_content() -> bool:
        nonlocal suffix, right_used_idx, right_content
        if right_content >= MAX_UNIQUENESS_WIDEN_TOKENS:
            return False
        took_content = False
        while right_used_idx < len(right_tokens):
            tok = right_tokens[right_used_idx]
            suffix = suffix + tok
            right_used_idx += 1
            if not tok.isspace():
                right_content += 1
                took_content = True
                break
        return took_content

    while _count_occurrences(doc_plain_text, current_target()) != 1:
        widened = False
        if _take_left_one_content():
            widened = True
        if _count_occurrences(doc_plain_text, current_target()) == 1:
            break
        if _take_right_one_content():
            widened = True
        if not widened:
            break

    final_occ = _count_occurrences(doc_plain_text, current_target())
    if final_occ != 1:
        raise RuntimeError(
            f"Stage 2 uniqueness failure: target {edit.target_text!r} "
            f"(after widening left={left_content}, right={right_content} "
            f"content tokens) still occurs {final_occ}× in document plain text. "
            f"Max widening ±{MAX_UNIQUENESS_WIDEN_TOKENS} tokens."
        )

    edit.target_text = prefix + edit.target_text + suffix
    edit.new_text = prefix + edit.new_text + suffix
    edit.left_context = left_content
    edit.right_context = right_content


def _count_occurrences(haystack: str, needle: str) -> int:
    if not needle:
        return 0
    count = 0
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            return count
        count += 1
        start = idx + 1


def _check_cross_edit_coupling(edits: list[Edit]) -> None:
    """Error if a pure-insert anchor is a substring of another edit's target_text.

    Would collide under Adeu's ``occupied_ranges`` overlap check and cause
    silent-skip on the later edit. The coupling violates the sub-agent
    discrete-applicability property claimed in the plan.
    """
    for i, e1 in enumerate(edits):
        if e1.kind != "pure_insert":
            continue
        for j, e2 in enumerate(edits):
            if i == j or e2.kind == "pure_insert":
                continue
            if e1.target_text and e1.target_text in e2.target_text:
                raise RuntimeError(
                    f"Stage 2 cross-edit coupling: pure_insert anchor "
                    f"{e1.target_text!r} is a substring of edit {j}'s target "
                    f"{e2.target_text!r}. See plan §2g for rationale."
                )


# ---------------------------------------------------------------------------
# Stage 3 — Apply
# ---------------------------------------------------------------------------


@dataclass
class ApplyResult:
    validation_errors: list[str] = field(default_factory=list)
    process_result: dict = field(default_factory=dict)
    output_bytes: bytes = b""


def stage3_apply(edits: list[Edit], input_docx_path: Path) -> ApplyResult:
    """validate_edits then process_batch. Returns both so the caller can log them."""
    with open(input_docx_path, "rb") as f:
        docx_bytes = f.read()

    engine = RedlineEngine(io.BytesIO(docx_bytes), author=AUTHOR)
    adeu_edits = [e.to_adeu() for e in edits]
    errors = engine.validate_edits(adeu_edits)
    if errors:
        return ApplyResult(validation_errors=errors, process_result={}, output_bytes=b"")

    # Fresh engine — validate_edits may have mutated internal state that
    # makes process_batch's mapper stale. Reinitialise to be safe.
    engine = RedlineEngine(io.BytesIO(docx_bytes), author=AUTHOR)
    result = engine.process_batch(adeu_edits)
    output_bytes = engine.save_to_stream().getvalue()

    return ApplyResult(
        validation_errors=[],
        process_result=result,
        output_bytes=output_bytes,
    )
