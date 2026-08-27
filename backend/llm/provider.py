"""One interface, two implementations (design doc 4.1).

    class LLMProvider(Protocol):
        async def complete(self, *, system, user, schema, max_tokens) -> dict

Config maps *roles* to providers, not calls to models: the outline call happens
once and defines the whole game, so it is worth spending on; zone authoring
happens dozens of times with narrow context and is a candidate for local
inference. Call sites ask for a role and never know which model answered.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from jsonschema import Draft202012Validator


class LLMError(Exception):
    """Any failure to get usable JSON out of a provider. Callers are expected to
    catch this and degrade -- design doc 4.4: a failed call must degrade to a
    boring zone, never to a crash."""


@dataclass
class Completion:
    """What a provider returns. `data` is the parsed JSON object; the rest is
    for logging and cost accounting."""

    data: dict
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # Local reasoning models spend most of their budget here and none of it on
    # the answer, which is worth being able to see.
    reasoning_tokens: int = 0
    cost: float = 0.0
    raw: str = ""
    seconds: float = 0.0


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def complete(
        self, *, system: str, user: str, schema: dict, max_tokens: int
    ) -> Completion: ...


@dataclass
class RecordingProvider:
    """Test double. Returns queued responses and records what it was asked.

    Design doc 10: "mock the provider in all tests except a small,
    manually-run live suite."
    """

    name: str = "recording"
    responses: list = field(default_factory=list)
    calls: list = field(default_factory=list)

    async def complete(self, *, system: str, user: str, schema: dict, max_tokens: int) -> Completion:
        self.calls.append({"system": system, "user": user, "schema": schema, "max_tokens": max_tokens})
        if not self.responses:
            raise LLMError("RecordingProvider ran out of queued responses")
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return Completion(data=nxt, model="recording")


# --- trusting providers only as far as they can be thrown --------------------

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def coerce_json(content: str, who: str) -> dict:
    """Parse a model response into a dict, tolerating a markdown fence.

    Fences appear whenever a model falls back to plain prose generation, which
    is precisely when the schema was not applied -- so this makes the response
    readable, not trustworthy. verify_against_schema is what decides.
    """
    if not isinstance(content, str) or not content.strip():
        raise LLMError(f"{who}: empty response")
    text = content.strip()
    match = _FENCE.match(text)
    if match:
        text = match.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"{who}: response was not JSON: {text[:300]}") from exc
    if not isinstance(data, dict):
        raise LLMError(f"{who}: response was {type(data).__name__}, expected an object")
    return data


def verify_against_schema(data: dict, schema: dict, who: str) -> None:
    """Check the response really matches what was asked for.

    Not every model honours `response_format` even when it advertises support;
    some return HTTP 200 with entirely the wrong shape. Catching that here turns
    a silent content bug into an LLMError, which the authoring layer already
    knows how to repair or fall back from.
    """
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if not errors:
        return
    first = errors[0]
    path = "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in first.absolute_path)
    raise LLMError(
        f"{who}: response ignored the schema ({len(errors)} problem(s)); "
        f"first at {path}: {first.message[:200]}"
    )
