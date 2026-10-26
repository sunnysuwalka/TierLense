"""Small OpenAI-compatible HTTP client for OpenRouter and Mistral endpoints.

This deliberately uses HTTPX directly instead of adding an OpenAI SDK dependency.
Only the common chat-completions surface used by TierLense is implemented.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx


class CompatibleProviderHTTPError(Exception):
    """HTTP error retaining safe provider metadata for the failover layer."""

    def __init__(self, status_code: int, headers: Any, body: Any) -> None:
        self.status_code = status_code
        self.response = SimpleNamespace(status_code=status_code, headers=headers or {})
        self.body = body
        error = body.get("error", body) if isinstance(body, dict) else {}
        message = error.get("message") if isinstance(error, dict) else None
        super().__init__(str(message or f"Provider returned HTTP {status_code}")[:700])


class _ChatCompletions:
    def __init__(self, client: "OpenAICompatibleHTTPClient") -> None:
        self._client = client

    def create(self, **kwargs: Any) -> dict[str, Any]:
        payload = dict(kwargs)
        # Mistral exposes max_tokens; OpenRouter accepts it across its model API.
        if "max_completion_tokens" in payload:
            limit = payload.pop("max_completion_tokens")
            payload.setdefault("max_tokens", limit)
        try:
            response = self._client._http.post(
                f"{self._client.base_url}/chat/completions",
                headers=self._client.headers,
                json=payload,
            )
        except httpx.HTTPError:
            raise
        if response.is_error:
            try:
                body = response.json()
            except ValueError:
                body = {"error": {"message": response.text[:700]}}
            raise CompatibleProviderHTTPError(response.status_code, response.headers, body)
        try:
            return response.json()
        except ValueError as exc:
            raise ValueError(f"{self._client.provider_name} returned a non-JSON API response") from exc


class OpenAICompatibleHTTPClient:
    """Synchronous client whose surface mirrors chat.completions.create()."""

    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout_seconds)
        self.chat = SimpleNamespace(completions=_ChatCompletions(self))

    def close(self) -> None:
        if self._owns_http:
            self._http.close()
