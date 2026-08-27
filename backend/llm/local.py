"""Local provider: Ollama or any llama.cpp server speaking the Ollama API.

Same signature as OpenRouter, so the role mapping in llm.yaml is the only thing
that decides which one answers a given call.
"""

from __future__ import annotations

import json
import os

import httpx2

from .provider import Completion, LLMError, coerce_json, verify_against_schema

DEFAULT_HOST = "http://127.0.0.1:11434"


class LocalProvider:
    def __init__(self, model: str, *, host: str | None = None, timeout: float = 180.0):
        self.name = f"local:{model}"
        self.model = model
        self.host = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).rstrip("/")
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return True  # availability is only knowable by asking; see reachable()

    async def reachable(self) -> bool:
        try:
            async with httpx2.AsyncClient(timeout=2.0) as client:
                return (await client.get(f"{self.host}/api/tags")).status_code == 200
        except Exception:
            return False

    async def complete(self, *, system: str, user: str, schema: dict, max_tokens: int) -> Completion:
        payload = {
            "model": self.model,
            "stream": False,
            "format": schema,  # Ollama takes a JSON Schema directly
            "options": {"num_predict": max_tokens, "temperature": 0.8},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            async with httpx2.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.host}/api/chat", json=payload)
        except Exception as exc:
            raise LLMError(f"{self.name}: request to {self.host} failed: {exc}") from exc

        if response.status_code != 200:
            raise LLMError(f"{self.name}: HTTP {response.status_code}: {response.text[:400]}")

        body = response.json()
        content = (body.get("message") or {}).get("content", "")
        data = coerce_json(content, self.name)
        verify_against_schema(data, schema, self.name)

        return Completion(
            data=data,
            model=self.model,
            prompt_tokens=body.get("prompt_eval_count", 0),
            completion_tokens=body.get("eval_count", 0),
            raw=content,
        )
