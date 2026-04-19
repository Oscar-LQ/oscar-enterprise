# ADR 017 — `.docx` File Flow via Filesystem Paths (not Graph State)

- **Status:** Accepted
- **Date:** 2026-04-19
- **Scope:** How the Sprint 10D redline-specialist's `.docx` input/output bytes flow through the Deep Agents graph without passing through a text-only `StateBackend`.
- **Supersedes:** none
- **Related:** ADR 009 (Deep Agents chat-model seam), ADR 014 (three-level delegation), Sprint 10A risk R4, Sprint 10C idioms §"Binary handling in Deep Agents"

## Context

The redline-specialist operates on `.docx` files. Adeu reads `BytesIO` on
construction (`RedlineEngine(stream, author=...)`) and emits `BytesIO` on
save (`save_to_stream().getvalue()`). Both are binary.

Deep Agents' `StateBackend` stores files as strings (Sprint 6 surprise 3,
restated in Sprint 10A R4). A binary `.docx` written as a string corrupts
on round-trip through the graph's `files` channel.

Two options surveyed in Sprint 10C's idioms guide (`adeu-idioms.md`
§"Binary handling in Deep Agents"):

1. **Keep bytes out of graph state.** Pass filesystem paths through the
   graph as strings; tool implementations read and write the filesystem
   directly. The graph's message/state channels never see the bytes.
2. **Base64-encode through state.** Encode bytes before putting in state;
   decode before handing to Adeu. Pays a 33% size tax, adds encode/decode
   surface area, fights the state backend's text assumption.

## Decision

**Filesystem paths flow through the graph. Binary bytes do not.** The
redline-specialist's tools are constructed by a factory that closes over
an `input_path` and an `output_path`:

```python
def make_redline_tools(input_path: Path, output_path: Path) -> list[BaseTool]:
    # tools read input_path (first call) / output_path (subsequent calls),
    # apply one Adeu edit, and write back to output_path.
    ...
```

The factory is invoked by the experiment script with paths from
filesystem constants, and the resulting tools are attached to the
`SubAgent` spec. The LLM never sees or manipulates paths — the tool
signatures only expose edit arguments (target_text, new_text, comment,
etc.). The output path is mentioned in the specialist's system prompt as
the location where the final `.docx` will be saved, so the specialist
can report it in its final message.

Rejected:

- **Base64 through state.** Adds two failure modes (encode/decode
  corruption, size inflation) with no benefit at Sprint 10D's scope
  (one-shot, one doc).
- **Pass the path as a tool argument on every call.** Expands the tool
  signature, opens the door to the LLM passing a wrong path (typo,
  hallucinated location). The path is infrastructure; the edit params
  are content.
- **Module-level path constants.** Works for one experiment but couples
  the specialist definition to one invocation. The factory pattern
  keeps the specialist callable on different input/output pairs in
  future sprints.

## Consequences

- **Pro:** Tool signatures stay minimal — edit params only. LLM
  reasoning stays focused on the edit content, not the mechanics.
- **Pro:** Binary `.docx` bytes never touch the graph's text channels.
  No encoding assumptions to violate.
- **Pro:** The factory pattern scales to multi-document workflows
  (e.g., read one NDA, write to a different path) without changing the
  tool-call shape the LLM sees.
- **Con:** The specialist cannot dynamically choose a different input
  path at runtime — paths are bound at agent-graph build time. For
  Sprint 10D (one transformation on one NDA) this is desired. When a
  later sprint needs per-invocation path selection, it will need to
  rebuild the agent graph per call (as Sprint 9 already does with
  `build_agents()`), or introduce a runtime config mechanism. Not a
  Sprint 10D concern.
- **Con:** Tool-layer code must handle filesystem errors (missing
  input, unwritable output directory) with appropriate surfaced
  messages. The specialist can't recover from these — they're
  operational failures, not content failures.
