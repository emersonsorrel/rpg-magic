"""Role -> provider mapping (design doc 4.1).

Call sites ask for a role ("zone_author") and never learn which model answered.
That is what makes the local/hosted split a config change rather than a code
change.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

import yaml

from .local import LocalProvider
from .openrouter import OpenRouterProvider
from .provider import LLMProvider

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "llm.yaml"
ENV_PATH = ROOT / ".env"


def load_env(path: pathlib.Path = ENV_PATH) -> None:
    """Read a local .env into the process, without clobbering real env vars.

    Deliberately tiny: the only secret this project has is an API key, and it
    must never be committed -- see .gitignore.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class RoleConfig:
    provider: str
    model: str
    max_tokens: int = 2000


def load_config(path: pathlib.Path | None = None) -> dict:
    raw = yaml.safe_load((path or CONFIG_PATH).read_text()) or {}
    return raw.get("llm", {})


def role_config(role: str, config: dict | None = None) -> RoleConfig:
    config = config if config is not None else load_config()
    entry = config.get(role)
    if not entry:
        raise KeyError(f"no llm role '{role}' in llm.yaml")
    return RoleConfig(
        provider=entry["provider"],
        model=entry["model"],
        max_tokens=int(entry.get("max_tokens", 2000)),
    )


def build_provider(role: str, config: dict | None = None) -> LLMProvider:
    load_env()
    spec = role_config(role, config)
    if spec.provider == "openrouter":
        return OpenRouterProvider(spec.model)
    if spec.provider == "local":
        return LocalProvider(spec.model)
    raise ValueError(f"unknown provider '{spec.provider}' for role '{role}'")


def authoring_enabled(config: dict | None = None) -> bool:
    """Whether to attempt LLM authoring at all.

    With no key and no local server the engine still runs -- it just commits the
    M2 placeholder zones. Content quality degrades; nothing breaks.
    """
    load_env()
    # Hard off switch for tests and CI. Design doc 10: mock the provider
    # everywhere except a small, manually-run live suite -- so the default for
    # an automated run must be "do not call anyone".
    if os.environ.get("RPG_MAGIC_NO_LLM"):
        return False
    config = config if config is not None else load_config()
    if not config.get("enabled", True):
        return False
    try:
        spec = role_config("zone_author", config)
    except KeyError:
        return False
    if spec.provider == "openrouter":
        return bool(os.environ.get("OPENROUTER_API_KEY"))
    return True
