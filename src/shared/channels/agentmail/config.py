"""Pydantic-settings boundary for OSCAR_AGENTMAIL_* env vars."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentMailChannelSettings(BaseSettings):
    """AgentMail channel configuration sourced from process environment.

    Phase 2 cross-cutting work wires the runtime to source env vars from
    ``/etc/oscar/oscar.env`` (host-side, read-only bind-mounted into the
    sandbox per ADR 025). This class reads from process environment,
    which is what the loader populates.

    The API key is workspace-scoped (one key per workspace, not per
    inbox); the inbox id selects which inbox the WebSocket subscription
    is filtered to.
    """

    model_config = SettingsConfigDict(
        env_prefix="OSCAR_AGENTMAIL_",
        extra="ignore",
        case_sensitive=False,
    )

    api_key: str
    inbox_id: str
