"""Counterparty-response port — Sprint 10P.

This package ports primitives from claude-plugin-mcp v2.0.0
(claude-contract-negotiator) into Oscar to support the counterparty-
response workflow: read a tracked-changed .docx (state-of-play),
let an LLM decide per-change actions, apply via a mix of Adeu
native primitives (accept / reply) and ported helpers
(counter_propose / add_comment).

Three port surfaces, all from claude-plugin-mcp/src/:
- Counter-propose primitives (negotiation/counter_propose_*.py)
- State-of-play extraction (ingestion/*)
- Comment-attaching primitives (negotiation/add_comment_helpers.py,
  add_comments_inplace.py, comment_ids_helpers.py, reply_helpers.py)

================================================================
UPGRADE-BRITTLENESS WARNING (Sprint 10P)
================================================================

This package reaches under Adeu's public DocumentChange surface to
construct OOXML primitives Adeu 1.3.3 does not expose natively:
  - Counter-propose: layered w:ins/w:del shapes nesting client
    edits inside counterparty markup (no Adeu primitive)
  - Standalone comments anchored to text or tracked changes
    (Adeu's CommentsManager is private surface; AcceptChange.comment
    field is vestigial — Sprint 10C finding, re-verified 10P)

Adeu has been moving at ~one minor release per fortnight (1.0 → 1.3.3
in two months). Each minor or patch release MAY break private-OOXML
expectations without warning — they are not part of the version-
compatibility contract.

This package's retirement path: when Adeu exposes native counter-
propose AND standalone-comment primitives in DocumentChange, the
files in this package delete cleanly.

TODO: file upstream feature requests to Adeu (Dealfluence/
Mikko Korpela):
  1. Native counter-propose primitive in DocumentChange union
     (preserves layered visibility on counterparty-attributed markup)
  2. Native standalone-comment primitive (no edit required; anchors
     to existing tracked change OR to text span)
  3. Native comment-anchor-by-text support (compose with #2)

Don't block 10P or follow-on sprints on the upstream requests.

Reference: docs/redline/research/sprint-10P-port-targets.md
================================================================
"""
