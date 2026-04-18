"""OpenRouter provider for Oscar's LLM dependency-injection seam.

Targets OpenRouter's OpenAI-compatible endpoint at
``POST https://openrouter.ai/api/v1/chat/completions``. Same wire shape as the
MiniMax plug (see ``minimax.py``) — only the host and model identifier change.

Public surface:
    OpenRouterClient(*, model, api_key)  -> object with .complete(prompt) -> str

Sovereignty note (PROJECT.md § LLM Policy): OpenRouter is a US-operated broker
that fronts many upstream providers. Model choice at DI time decides which
upstream actually serves the request; clients with data-residency constraints
must pick a model whose upstream they accept.
"""
from __future__ import annotations

import httpx

_HOST = "https://openrouter.ai"
_CHAT_COMPLETIONS_PATH = "/api/v1/chat/completions"
_DEFAULT_TIMEOUT_S = 60.0


class OpenRouterClient:
    """Thin wrapper over OpenRouter's OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        host: str = _HOST,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._url = host + _CHAT_COMPLETIONS_PATH
        self._timeout_s = timeout_s

    def complete(self, prompt: str) -> str:
        """Send ``prompt`` as a single user message; return the assistant reply."""
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        response = httpx.post(
            self._url,
            json=payload,
            headers=headers,
            timeout=self._timeout_s,
        )
        response.raise_for_status()
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as err:
            raise RuntimeError(
                f"Unexpected OpenRouter response shape: {data!r}"
            ) from err
