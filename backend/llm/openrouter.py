"""OpenRouter: HTTP, model name from config, API key from env (design doc 4.1).

Thin over the shared OpenAI-compatible client — the only differences are the
base URL, a required key, and OpenRouter's attribution headers.
"""

from __future__ import annotations

from .openai_compatible import OpenAICompatibleProvider

ENDPOINT = "https://openrouter.ai/api/v1"


class OpenRouterProvider(OpenAICompatibleProvider):
    def __init__(self, model: str, *, api_key: str | None = None, timeout: float = 90.0,
                 referer: str = "https://github.com/emersonsorrel/rpg-magic"):
        super().__init__(
            model,
            base_url=ENDPOINT,
            api_key=api_key,
            api_key_env="OPENROUTER_API_KEY",
            timeout=timeout,
            requires_key=True,
            label=f"openrouter:{model}",
            extra_headers={"HTTP-Referer": referer, "X-Title": "rpg-magic"},
        )
