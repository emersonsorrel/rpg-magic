"""Any server speaking the OpenAI chat-completions API.

That covers OpenRouter, LM Studio, llama.cpp's server, vLLM and friends — which
is why this is the shared implementation rather than three near-copies. Design
doc 4.1 wants one interface with a hosted and a local implementation; the honest
version of that is one implementation pointed at different base URLs.

The Ollama API is genuinely different (see local.py) and keeps its own provider.
"""

from __future__ import annotations

import json
import os
import time

import httpx2

from .provider import Completion, LLMError, coerce_json, verify_against_schema


class OpenAICompatibleProvider:
    def __init__(self, model: str, *, base_url: str, api_key: str | None = None,
                 api_key_env: str | None = None, timeout: float = 90.0,
                 extra_headers: dict | None = None, label: str | None = None,
                 requires_key: bool = False):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.extra_headers = extra_headers or {}
        self.requires_key = requires_key
        self._api_key = api_key or (os.environ.get(api_key_env) if api_key_env else None)
        self.name = label or f"{self.base_url}:{model}"

    @property
    def configured(self) -> bool:
        return bool(self._api_key) if self.requires_key else True

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def models(self) -> list[str]:
        """What the server is offering. Used by the probe, not by authoring."""
        async with httpx2.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{self.base_url}/models", headers=self._headers())
        response.raise_for_status()
        return [entry["id"] for entry in response.json().get("data", [])]

    async def complete(self, *, system: str, user: str, schema: dict, max_tokens: int) -> Completion:
        if self.requires_key and not self._api_key:
            raise LLMError(f"{self.name}: no API key configured")

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.get("title", "response"),
                    "strict": True,
                    "schema": schema,
                },
            },
        }

        started = time.monotonic()
        try:
            async with httpx2.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
                )
        except Exception as exc:
            raise LLMError(f"{self.name}: request failed: {exc}") from exc
        elapsed = time.monotonic() - started

        if response.status_code != 200:
            raise LLMError(f"{self.name}: HTTP {response.status_code}: {response.text[:400]}")

        body = response.json()
        if "error" in body:
            raise LLMError(f"{self.name}: {json.dumps(body['error'])[:400]}")

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"{self.name}: unexpected response shape: {json.dumps(body)[:300]}") from exc

        usage = body.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        reasoning = details.get("reasoning_tokens", 0) or 0

        if not (content or "").strip():
            # A reasoning model that thinks up to its ceiling returns HTTP 200
            # with an empty string. Saying so beats "response was not JSON".
            if reasoning and reasoning >= max_tokens * 0.9:
                raise LLMError(
                    f"{self.name}: spent its whole {max_tokens}-token budget reasoning "
                    f"({reasoning} tokens) and never answered. Raise max_tokens for this "
                    f"role, or use a model that does not think before replying."
                )
            raise LLMError(f"{self.name}: returned an empty response")

        data = coerce_json(content, self.name)
        verify_against_schema(data, schema, self.name)

        return Completion(
            data=data,
            model=body.get("model", self.model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            reasoning_tokens=reasoning,
            cost=float(usage.get("cost", 0.0) or 0.0),
            raw=content,
            seconds=elapsed,
        )
