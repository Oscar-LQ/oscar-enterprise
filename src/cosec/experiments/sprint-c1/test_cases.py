"""Three CoSec drafting test cases for Sprint C1 — verbatim from the brief.

tc1 — board written resolution (accounts approval, no dividend).
tc2 — shareholder written resolution (auditor re-appointment; s.288 + s.485).
tc3 — board minutes (director appointment; quorum per articles).

One attempt per case, no retries. Single-attempt discipline matches the
redline track's brief's-rule-of-one-shot.
"""
from __future__ import annotations

from typing import TypedDict


class TestCase(TypedDict):
    id: str
    request: str


TEST_CASES: list[TestCase] = [
    {
        "id": "tc1-accounts-approval",
        "request": (
            "Draft a board written resolution for Acme Trading Ltd "
            "(company number 09876543) approving the annual accounts "
            "for the year ended 31 December 2025. Profit for the year: "
            "£1,420,000. Directors: Sarah Smith, David Jones, Priya "
            "Patel. No dividend to be declared this year."
        ),
    },
    {
        "id": "tc2-auditor-reappointment",
        "request": (
            "Draft a shareholder written resolution for Meridian "
            "Systems Ltd (company number 11223344) re-appointing Crowe "
            "UK LLP as auditor for the year ending 31 March 2026. The "
            "shareholders are: James Holdings Ltd (80%) and Trevor "
            "James (20%)."
        ),
    },
    {
        "id": "tc3-director-appointment-minutes",
        "request": (
            "Draft board minutes for Northfield Properties Ltd, board "
            "meeting held 15 April 2026. Present: Michael Chen (chair), "
            "Rebecca Hill. Resolved to appoint Thomas Okafor as a "
            "director with effect from 15 April 2026. Quorum "
            "requirement per articles: two directors."
        ),
    },
]
