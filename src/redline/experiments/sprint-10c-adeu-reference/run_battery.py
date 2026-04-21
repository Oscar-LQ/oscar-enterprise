"""Sprint 10C — Adeu reference test battery, full run.

Executes every themed test module in this directory and prints one
unified report. Import side-effects (structlog routing, logging
capture) happen via ``harness`` before any Adeu code is imported.

Usage:
    /sandbox/.venv/bin/python run_battery.py
"""

from __future__ import annotations

import importlib
import sys


SUITE_MODULES = [
    "test_modify_text",
    "test_review_actions",
    "test_ingest_markup",
    "test_io_authors_quirks",
    "test_comments_and_round_trip",
]


def main() -> int:
    from harness import run_suite, summarise, TestResult

    print("==================== sprint-10c Adeu reference battery ====================")
    all_results: list[TestResult] = []
    for mod_name in SUITE_MODULES:
        mod = importlib.import_module(mod_name)
        tests = getattr(mod, "TESTS")
        print(f"\n== {mod_name} ({len(tests)} tests) ==")
        results = run_suite(mod_name, tests)
        all_results.extend(results)
    return summarise(all_results)


if __name__ == "__main__":
    sys.exit(main())
