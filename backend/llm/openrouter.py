"""OpenRouter provider: HTTP, model from config, API key from env."""

from __future__ import annotations

import json
import os
import re

import httpx2

from .provider import Completion, LLMError, coerce_json, verify_against_schema

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider:
    def __init__(self, model: str, *, api_key: str | None = None, timeout: float = 90.0,
                 referer: str = "https://github.com/emersonsorrel/rpg-magic"):
        self.name = f"openrouter:{model}"
        self.model = model
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.timeout = timeout
        self.referer = referer

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def complete(self, *, system: str, user: str, schema: dict, max_tokens: int) -> Completion:
        if not self._api_key:
            raise LLMError("OPENROUTER_API_KEY is not set")

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema.get("title", "response"), "strict": True, "schema": schema},
            },
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            # OpenRouter attribution headers; harmless if the app is private.
            "HTTP-Referer": self.referer,
            "X-Title": "rpg-magic",
        }

        try:
            async with httpx2.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(ENDPOINT, json=payload, headers=headers)
        except Exception as exc:  # network, DNS, timeout
            raise LLMError(f"{self.name}: request failed: {exc}") from exc

        if response.status_code != 200:
            raise LLMError(f"{self.name}: HTTP {response.status_code}: {response.text[:400]}")

        body = response.json()
        if "error" in body:
            raise LLMError(f"{self.name}: {json.dumps(body['error'])[:400]}")

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"{self.name}: unexpected response shape: {json.dumps(body)[:300]}") from exc

        data = coerce_json(content, self.name)
        # Some models accept a json_schema request, return HTTP 200, and quietly
        # ignore the schema -- Anthropic models via OpenRouter do this on deeply
        # nested schemas. A provider that says "JSON matching this schema" has to
        # check, or every downstream caller inherits the lie.
        verify_against_schema(data, schema, self.name)

        usage = body.get("usage") or {}
        return Completion(
            data=data,
            model=body.get("model", self.model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            cost=float(usage.get("cost", 0.0) or 0.0),
            raw=content,
        )
