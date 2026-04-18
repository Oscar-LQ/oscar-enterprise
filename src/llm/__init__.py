"""Oscar's LLM dependency-injection seam.

PROJECT.md § LLM Policy: runtime LLM is model-agnostic by design. Provider,
model, and key are injected at startup via environment variables — not
hardcoded in agent code. This module is the seam.

Contract:
    get_llm_client() -> Callable[[str], str]

The returned callable takes a user prompt and returns the model's completion.
Provider-native structures (chat messages, tool calls, streaming, etc.) are
intentionally NOT exposed here — Sprint 3's scope is a minimal string-in/
string-out integration test. Richer surface can land when a use-case needs it.

Adding a provider: register a factory in ``_FACTORIES`` below. The factory
receives ``model`` and ``api_key`` as keyword arguments and must return a
``Callable[[str], str]``.
"""
from __future__ import annotations

import os
from typing import Callable

LLMClient = Callable[[str], str]
_ProviderFactory = Callable[..., LLMClient]


def _minimax_factory(*, model: str, api_key: str) -> LLMClient:
    from .minimax import MiniMaxClient

    return MiniMaxClient(model=model, api_key=api_key).complete


_FACTORIES: dict[str, _ProviderFactory] = {
    "minimax": _minimax_factory,
}


def get_llm_client() -> LLMClient:
    """Return an LLM client configured from environment variables.

    Reads OSCAR_LLM_PROVIDER, OSCAR_LLM_MODEL, OSCAR_LLM_API_KEY. Env vars
    are read at call time so tests (and future in-process reconfiguration)
    can override without a module reload.
    """
    provider = _require_env("OSCAR_LLM_PROVIDER")
    model = _require_env("OSCAR_LLM_MODEL")
    api_key = _require_env("OSCAR_LLM_API_KEY")

    try:
        factory = _FACTORIES[provider]
    except KeyError:
        supported = sorted(_FACTORIES)
        raise ValueError(
            f"Unsupported OSCAR_LLM_PROVIDER: {provider!r}. "
            f"Supported: {supported}. "
            f"Add a branch in src/llm/__init__.py to support another."
        ) from None

    return factory(model=model, api_key=api_key)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(
            f"{name} is not set. See .env.example for the expected shape."
        )
    return value
