"""MiniMax provider for Oscar's LLM dependency-injection seam.

Targets MiniMax's OpenAI-compatible endpoint at
``POST https://api.minimax.io/v1/chat/completions`` rather than the native
``/v1/text/chatcompletion_v2``. The OpenAI-compatible route does not require
a ``GroupId`` query parameter, so the DI contract stays model + api_key only.

Public surface:
    MiniMaxClient(*, model, api_key)  -> object with .complete(prompt) -> str

Sovereignty note (PROJECT.md § LLM Policy): MiniMax is a Shanghai-based
provider. Calls to api.minimax.io route to MiniMax infrastructure. Clients
with PRC-exposure concerns must pick a different provider at DI time.
"""
from __future__ import annotations

import httpx

_HOST = "https://api.minimax.io"
_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
_DEFAULT_TIMEOUT_S = 60.0


class MiniMaxClient:
    """Thin wrapper over MiniMax's OpenAI-compatible chat completions endpoint."""

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
                f"Unexpected MiniMax response shape: {data!r}"
            ) from err
