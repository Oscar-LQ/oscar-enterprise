"""Pydantic-settings boundary for OSCAR_SLACK_* env vars."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class SlackChannelSettings(BaseSettings):
    """Slack channel configuration sourced from process environment.

    Phase 2 cross-cutting work wires the runtime to source env vars from
    ``/etc/oscar/oscar.env`` (host-side, read-only bind-mounted into the
    sandbox per ADR 025). This class reads from process environment,
    which is what the loader populates.

    Validation runs at instance construction; missing vars raise
    ``ValidationError`` immediately — no silent fallback to placeholder
    tokens.
    """

    model_config = SettingsConfigDict(
        env_prefix="OSCAR_SLACK_",
        extra="ignore",
        case_sensitive=False,
    )

    bot_token: str
    app_token: str
