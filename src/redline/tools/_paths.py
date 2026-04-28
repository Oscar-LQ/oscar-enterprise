"""Default fixture paths for the M3 redline tool.

These exist because M3 runs the redline pipeline against a hardcoded
fixture — Slack file upload (M4) replaces them with attachment-derived
paths. Kept in a small constants module so `runtime/main.py` and the
test suite both have one source of truth, satisfying CLAUDE.md's
"no magic strings" rule.
"""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parents[3]

DEFAULT_NDA_INPUT = REPO_ROOT / "src/redline/experiments/sprint-10P/nda-input-minimal.docx"
DEFAULT_NDA_ORIGINAL = REPO_ROOT / "src/redline/experiments/sprint-10P/nda-original.docx"
DEFAULT_NDA_OUTPUT = REPO_ROOT / "src/redline/experiments/sprint-10P/nda-output-oscar.docx"
