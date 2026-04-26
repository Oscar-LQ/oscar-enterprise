# Sprint 10P Phase 2.2 — cut-down trim methodology

The full Zenith fixture (`nda-input-full.docx`, 39,873 bytes — copy
of 10P-prep's `nda-output.docx` fetched via `git show
sprint-10P-prep-zenith-firstpass:...`) contains 18 pending tracked
changes (12 `w:ins` + 6 `w:del`). Phase 2's brief asks for a 3-change
cut-down that exercises three planner decision types: accept,
counter_propose, and no_action.

`build_input.py` produces `nda-input-minimal.docx` by surgically
removing 15 of the 18 tracked changes via lxml. The remaining 3 are:

| Original Chg:N | ooxml_id | type | clause | changed_text (truncated) | Decision type tested |
|---|---|---|---|---|---|
| Chg:1  | 6  | deletion  | §1 (Confidential Information) | `whether or not marked or described as confidential.` | **accept** with planner-drafted comment via `paragraph_context` anchor (Q2(a) from Phase 0) |
| Chg:7  | 10 | insertion | §3 (permitted disclosure)     | `and its Affiliates, and to its contractors and subcontractors engaged in connection with the Purpose, where "Affiliates" means entities controlling, controlled by or under common control with a Party ` | **counter_propose** routed through `counter_propose_on_document` (surgical-or-wholesale per shared-token analysis) |
| Chg:15 | 14 | insertion | §6 (return / destruction)     | ` Without limiting the foregoing, the Receiving Party is not required to delete Confidential Information from automatic electronic backup or archival systems where deletion is not reasonably practicable, provided that any such information is not restored or accessed except as required for legal, regulatory, compliance, or business continuity purposes and remains subject to the terms of this Agreement.` | **no_action** with planner-drafted reasoning note |

After the trim, `build_state_of_play` renumbers the 3 remaining changes
sequentially in document order:

- new Chg:1 (was Chg:1, ooxml=6)  — §1 deletion
- new Chg:2 (was Chg:7, ooxml=10) — §3 affiliates+contractors insertion
- new Chg:3 (was Chg:15, ooxml=14) — §6 backup exception insertion

All three retain `author = "Zenith Counsel"` in the raw OOXML.

---

## Why lxml surgery (not Adeu RejectChange)

Adeu's `RejectChange` sweeps paired tracked changes that share a
revision_id (engine.py `apply_review_actions` resolved_history
mechanism — Sprint 10C finding). Most pairs in the Zenith fixture are
discardable as a unit (one reject removes both halves), but the §1
narrowing pair is special:

- ooxml_id=6 (deletion of "whether or not marked or described as
  confidential.") — KEEP
- ooxml_id=7 (insertion of "that is identified as confidential or
  that ought reasonably to be understood...") — DISCARD

Because they share a revision_id, `RejectChange(target_id="7")` would
sweep ooxml_id=6 too — destroying our keeper. Surgical lxml removal
operates element-by-element and bypasses the pair-sweep, removing
only the elements named.

`build_input.py` adapts the body of Adeu's `_reject_change` (the
non-pair-sweep half): for unwanted `w:ins`, remove the wrapper
entirely (insertion discarded); for unwanted `w:del`, unwrap and
promote `w:delText` → `w:t` (deletion reverted, text restored).

---

## Discarded changes (15)

| Original Chg:N | ooxml | type | clause | reason discarded |
|---|---|---|---|---|
| Chg:2  | 7  | insertion | §1 | reasonable-understanding qualifier — paired with Chg:1 deletion; we keep only the deletion to test a single accept decision |
| Chg:3  | 8  | deletion  | §1 | "evaluation" narrowing |
| Chg:4  | 9  | insertion | §1 | "evaluation, negotiation and performance" |
| Chg:5  | 15 | deletion  | §2 | "Party" trim |
| Chg:6  | 16 | insertion | §2 | except-as-permitted carve-out |
| Chg:8  | 11 | deletion  | §3 | "Representatives." trim |
| Chg:9  | 12 | insertion | §3 | "Representatives, subject to the limitations on liability set out in Clause 7." |
| Chg:10 | 1  | insertion | §4 | "court order, " |
| Chg:11 | 2  | deletion  | §4 | jurisdiction shift |
| Chg:12 | 3  | insertion | §4 | "any competent governmental or regulatory authority," |
| Chg:13 | 4  | deletion  | §4 | "so." trim |
| Chg:14 | 5  | insertion | §4 | "so; or (e) is independently developed..." |
| Chg:16 | 13 | insertion | §7 | mandatory-law liability cap reframing |
| Chg:17 | 17 | insertion | §8A | "8A. No Warranty or Obligation to Proceed" heading |
| Chg:18 | 18 | insertion | §8A | clause body |

---

## Substantive note (mechanical test only)

Discarding Chg:2 (the §1 reasonable-understanding qualifier insertion)
breaks Zenith's logical §1 narrowing — accepting Chg:1 alone removes
the original "whether or not marked or described as confidential."
qualifier with no replacement, leaving the "Confidential Information"
definition truncated. This is acceptable for Phase 2's mechanical
verification (does the accept-with-comment composite work?) but does
not represent a substantively coherent counterparty-response test.
Phase 3 expands to the full 18-change fixture where the §1 pair is
restored and exercised end-to-end.
