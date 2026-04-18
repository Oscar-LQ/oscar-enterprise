"""BaseChatModel-shaped seam for Deep Agents.

Parallel to the string-in/string-out seam exposed by :mod:`llm.__init__`.
Where that seam returns a ``Callable[[str], str]`` for minimal LLM round-trips
(ADR 008), this seam returns a LangChain :class:`BaseChatModel` — the shape
Deep Agents requires for tool-calling work (ADR 009).

Contract:
    get_chat_model() -> BaseChatModel

Both seams read the same three env vars (``OSCAR_LLM_PROVIDER``,
``OSCAR_LLM_MODEL``, ``OSCAR_LLM_API_KEY``), so configuration parity holds:
swapping providers in either seam is an env-var change, not a code change.

Adding a provider: register a factory in ``_FACTORIES`` below. The factory
receives ``model`` and ``api_key`` as keyword arguments and must return a
``BaseChatModel``. As of Sprint 6 only OpenRouter is wired here; MiniMax will
follow once a sprint needs tool calling against a non-OpenRouter provider.
"""
from __future__ import annotations

import os
from typing import Callable

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

_ChatModelFactory = Callable[..., BaseChatModel]


def _openrouter_factory(*, model: str, api_key: str) -> BaseChatModel:
    return init_chat_model(f"openrouter:{model}", api_key=api_key)


_FACTORIES: dict[str, _ChatModelFactory] = {
    "openrouter": _openrouter_factory,
}


def get_chat_model() -> BaseChatModel:
    """Return a Deep-Agents-compatible chat model from environment variables.

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
            f"Unsupported OSCAR_LLM_PROVIDER for chat-model seam: {provider!r}. "
            f"Supported: {supported}. Add a branch in src/llm/chat_model.py "
            f"to support another."
        ) from None

    return factory(model=model, api_key=api_key)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(
            f"{name} is not set. See .env.example for the expected shape."
        )
    return value
