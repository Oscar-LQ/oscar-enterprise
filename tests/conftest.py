"""Pytest config: make ``src/`` the package root for tests.

This repo has no ``pyproject.toml`` / ``setup.py``; the convention is that
``src/`` is the package root and modules are imported as ``shared.*``,
``redline.*``, ``cosec.*``. The experiment files in ``src/redline/`` use
``sys.path.insert`` to achieve the same effect; here we do it once for the
whole test tree.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
