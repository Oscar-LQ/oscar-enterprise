"""Source ``OSCAR_*`` secrets from the host-bind-mounted env file.

Per ADR 025: secrets land in ``/etc/oscar/oscar.env`` on the host
(root-owned, mode 0600). The host launcher bind-mounts the file
read-only into the sandbox at the same path. The runtime entry point
calls ``load_host_secrets()`` once at startup; downstream callers use
``os.environ.get(...)`` (or the Pydantic-settings ``BaseSettings``
classes in the channel ``config.py`` modules) to read the values.

Sprint 3's in-sandbox ``.env`` pattern (loaded via ``python-dotenv``)
remains usable for developer-local non-secret configuration; the
host-bind-mounted file is the only carrier for production secrets.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

DEFAULT_OSCAR_ENV_PATH = Path("/etc/oscar/oscar.env")

_logger = logging.getLogger(__name__)


def load_host_secrets(
    *,
    path: Path = DEFAULT_OSCAR_ENV_PATH,
    override: bool = False,
) -> int:
    """Read ``KEY=VALUE`` lines from ``path`` and populate ``os.environ``.

    Args:
        path: File to read. Default ``/etc/oscar/oscar.env`` (ADR 025).
        override: If True, overwrite existing env vars with values from
            the file. Default False so developer-local pre-set
            ``OSCAR_*`` vars (e.g. via direnv or shell export) win over
            the host file — useful for testing against a non-prod token
            without touching the host secrets store.

    Returns:
        Count of non-blank, non-comment, ``KEY=VALUE``-shaped lines read
        from the file (whether or not they replaced an existing env var
        — the count reflects file shape, not mutation).

    Raises:
        FileNotFoundError: if ``path`` does not exist. Per ADR 025, the
            host owns this file and bind-mounts it read-only into the
            sandbox; absence indicates the host launcher did not
            establish the bind-mount, or the host file was never created
            by main-VPS Claude Code.
        PermissionError: if the file cannot be read (e.g. mode-0600 on
            host but the bind-mount squashed UIDs unexpectedly).
    """
    if not path.exists():
        raise FileNotFoundError(
            f"oscar config: {path} not found. Per ADR 025 the host "
            f"launcher bind-mounts this file read-only into the sandbox; "
            f"check (a) the launcher's bind-mount config and (b) that "
            f"main-VPS Claude Code has created the host-side file."
        )

    loaded = 0
    skipped = 0
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            _logger.warning(
                "oscar config: skipping malformed line in %s (no '='): %r",
                path,
                raw_line,
            )
            skipped += 1
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            _logger.warning(
                "oscar config: skipping malformed line in %s (empty key): %r",
                path,
                raw_line,
            )
            skipped += 1
            continue
        value = _unquote(value.strip())
        if override or key not in os.environ:
            os.environ[key] = value
        loaded += 1
    if skipped:
        _logger.warning(
            "oscar config: %d malformed line(s) skipped in %s", skipped, path
        )
    return loaded


def _unquote(value: str) -> str:
    """Strip a single matching pair of single or double quotes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value
