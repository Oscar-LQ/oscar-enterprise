"""Shared timestamp generation for tracked change attribution.

Single source of truth for ISO 8601 UTC timestamps used by
counter-propose and comment-attaching operations.

Source: claude-plugin-mcp/src/negotiation/timestamp.py (verbatim).
See src/redline/lib/__init__.py for the package-level upgrade
warning.
"""

import datetime
from datetime import date


def generate_timestamp(date_override: date | None = None) -> str:
    """Generate an ISO 8601 UTC timestamp for tracked change attribution.

    Args:
        date_override: If provided, returns midnight UTC on this date.
            If None, returns the current UTC time truncated to seconds.

    Returns:
        ISO 8601 string ending in 'Z' (e.g. '2026-02-15T00:00:00Z').
    """
    if date_override is not None:
        combined = datetime.datetime.combine(
            date_override,
            datetime.time.min,
            tzinfo=datetime.timezone.utc,
        )
        return combined.isoformat().replace("+00:00", "Z")

    now = datetime.datetime.now(datetime.timezone.utc)
    return now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
