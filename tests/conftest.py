"""Pytest config: make ``src/`` the package root for tests.

This repo has no ``pyproject.toml`` / ``setup.py``; the convention is that
``src/`` is the package root and modules are imported as ``shared.*``,
``redline.*``, ``cosec.*``. The experiment files in ``src/redline/`` use
``sys.path.insert`` to achieve the same effect; here we do it once for the
whole test tree.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def pytest_configure(config: pytest.Config) -> None:
    """Register custom marks so they don't trigger ``PytestUnknownMarkWarning``."""
    config.addinivalue_line(
        "markers",
        "live: live integration test — gated by --live-integration and "
        "credentials in /etc/oscar/oscar.env (M3+).",
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--live-integration`` flag at session level so the live
    integration tests can opt-in via ``request.config.getoption(...)``."""
    parser.addoption(
        "--live-integration",
        action="store_true",
        default=False,
        help="run live Slack + LLM integration tests (M3+)",
    )
