"""BaseChatModel-shaped seam for Deep Agents.

Parallel to the string-in/string-out seam exposed by :mod:`llm.__init__`.
Where that seam returns a ``Callable[[str], str]`` for minimal LLM round-trips
(ADR 008), this seam returns a LangChain :class:`BaseChatModel` — the shape
Deep Agents requires for tool-calling work (ADR 009).

Entry points
------------

``build_chat_model(*, provider, model, api_key)``
    Pure DI form. Caller supplies provider, model, and key explicitly. Returns
    a ready-to-use :class:`BaseChatModel`. Use this when an agent's model is
    decided by code (e.g. passed in via config object) rather than by env.

``get_chat_model(env_prefix="OSCAR_LLM")``
    Env-var convenience over ``build_chat_model``. Reads
    ``{env_prefix}_PROVIDER``, ``{env_prefix}_MODEL``, ``{env_prefix}_API_KEY``.
    The default prefix is ``OSCAR_LLM`` for backward compatibility with the
    Sprint 6 single-agent experiment. Multi-agent callers pass a per-role
    prefix (e.g. ``OSCAR_LLM_GENERAL_COUNSEL``) so each agent's provider,
    model, and key come from its own env-var slot — the concrete shape of the
    per-agent DI decision recorded in ADR 010.

Provider support
----------------

* ``openrouter`` — uses ``langchain-openrouter`` via ``init_chat_model``;
  Deep Agents' OpenRouter profile auto-injects attribution headers (ADR 009).
* ``minimax`` — uses ``langchain-openai`` 's ``ChatOpenAI`` pointed at
  ``https://api.minimax.io/v1`` via the ``base_url`` kwarg. MiniMax has no
  dedicated LangChain integration package; the OpenAI-compatible route is
  the documented carry-forward from Sprint 5. ``reasoning_split=True`` is
  passed via ``extra_body`` so MiniMax returns the chain-of-thought in a
  separate ``reasoning_details`` field rather than inlined in
  ``message.content`` inside ``<think>...</think>`` tags (ADR 012).

Adding a provider: register a factory in ``_FACTORIES`` below. The factory
receives ``model`` and ``api_key`` as keyword arguments and must return a
``BaseChatModel``.
"""
from __future__ import annotations

import os
from typing import Callable

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

_ChatModelFactory = Callable[..., BaseChatModel]

_MINIMAX_BASE_URL = "https://api.minimax.io/v1"


def _openrouter_factory(*, model: str, api_key: str) -> BaseChatModel:
    return init_chat_model(f"openrouter:{model}", api_key=api_key)


def _minimax_factory(*, model: str, api_key: str) -> BaseChatModel:
    return init_chat_model(
        f"openai:{model}",
        base_url=_MINIMAX_BASE_URL,
        api_key=api_key,
        extra_body={"reasoning_split": True},
    )


_FACTORIES: dict[str, _ChatModelFactory] = {
    "openrouter": _openrouter_factory,
    "minimax": _minimax_factory,
}


def build_chat_model(*, provider: str, model: str, api_key: str) -> BaseChatModel:
    """Construct a Deep-Agents-compatible chat model from explicit parameters.

    Pure DI form — no environment access. Callers responsible for sourcing
    provider, model, and key (env, config file, test fixture, whatever).

    Raises:
        ValueError: if ``provider`` is not registered in ``_FACTORIES``.
    """
    try:
        factory = _FACTORIES[provider]
    except KeyError:
        supported = sorted(_FACTORIES)
        raise ValueError(
            f"Unsupported chat-model provider: {provider!r}. "
            f"Supported: {supported}. Add a branch in src/llm/chat_model.py "
            f"to support another."
        ) from None
    return factory(model=model, api_key=api_key)


def get_chat_model(*, env_prefix: str = "OSCAR_LLM") -> BaseChatModel:
    """Return a Deep-Agents-compatible chat model from environment variables.

    Reads ``{env_prefix}_PROVIDER``, ``{env_prefix}_MODEL``, and
    ``{env_prefix}_API_KEY``. Env vars are read at call time so tests (and
    future in-process reconfiguration) can override without a module reload.
    """
    return build_chat_model(
        provider=_require_env(f"{env_prefix}_PROVIDER"),
        model=_require_env(f"{env_prefix}_MODEL"),
        api_key=_require_env(f"{env_prefix}_API_KEY"),
    )


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(
            f"{name} is not set. See .env.example for the expected shape."
        )
    return value
