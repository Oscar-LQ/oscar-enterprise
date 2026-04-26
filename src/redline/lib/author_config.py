"""Client author configuration for tracked change attribution.

Centralizes the author identity used when applying counter-propose,
add-comment, and other operations. Replaces the bare client_author
string with a rich config that includes date override, initials,
and timestamp generation.

Source: claude-plugin-mcp/src/models/author_config.py (verbatim,
import path adapted for the lazy timestamp reference).
See src/redline/lib/__init__.py for the package-level upgrade warning.

Usage:
    from src.redline.lib.author_config import AuthorConfig

    config = AuthorConfig(name="Acme Counsel")
    config.initials   # "AC"
    config.timestamp  # "2026-04-26T..." (current UTC)
"""

from datetime import date

from pydantic import BaseModel, computed_field


class AuthorConfig(BaseModel):
    """Client author configuration for tracked change attribution."""

    name: str
    date_override: date | None = None
    initials_override: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def initials(self) -> str:
        """Return author initials (override or auto-generated from name)."""
        if self.initials_override:
            return self.initials_override
        return "".join(word[0].upper() for word in self.name.split() if word)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def timestamp(self) -> str:
        """Return ISO 8601 UTC timestamp for tracked change w:date attributes."""
        # Lazy import: avoid cycle if timestamp.py ever imports from this module
        from src.redline.lib.timestamp import generate_timestamp

        return generate_timestamp(self.date_override)
