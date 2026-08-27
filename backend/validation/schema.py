"""JSON Schema pass.

The schemas in /schemas are the contract between three parties -- backend, client
and model -- so they live in exactly one place and both sides build validators
from them. This module is the Python side.
"""

from __future__ import annotations

import functools
import hashlib
import json
import pathlib

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from .errors import Code, Report

SCHEMA_DIR = pathlib.Path(__file__).resolve().parents[2] / "schemas"

SCHEMA_FILES = {
    "event_command": "event_command.schema.json",
    "zone_package": "zone_package.schema.json",
    "ledger": "ledger.schema.json",
}


@functools.lru_cache(maxsize=1)
def _registry() -> Registry:
    resources = []
    for filename in SCHEMA_FILES.values():
        doc = json.loads((SCHEMA_DIR / filename).read_text())
        resource = Resource.from_contents(doc, default_specification=DRAFT202012)
        # Register under the canonical $id and under the bare filename, so both
        # absolute and relative $refs resolve.
        resources.append((doc["$id"], resource))
        resources.append((filename, resource))
    return Registry().with_resources(resources)


@functools.lru_cache(maxsize=8)
def validator_for(name: str) -> Draft202012Validator:
    doc = json.loads((SCHEMA_DIR / SCHEMA_FILES[name]).read_text())
    return Draft202012Validator(doc, registry=_registry())


def _path_of(error) -> str:
    parts = ["$"]
    for token in error.absolute_path:
        parts.append(f"[{token}]" if isinstance(token, int) else f".{token}")
    return "".join(parts)


def check_schema(doc, name: str, report: Report) -> bool:
    """Run the structural pass. Returns True when the document is schema-clean.

    Deepest errors first: with if/then branches the useful message is almost
    always the innermost one, not the top-level "does not match".
    """
    errors = sorted(
        validator_for(name).iter_errors(doc),
        key=lambda e: (-len(e.absolute_path), str(e.absolute_path)),
    )
    for error in errors[:25]:
        report.error(Code.SCHEMA, _path_of(error), error.message)
    if len(errors) > 25:
        report.error(Code.SCHEMA, "$", f"...and {len(errors) - 25} further schema errors")
    return not errors


@functools.lru_cache(maxsize=1)
def schema_hash() -> str:
    """Fingerprint of the shared schemas.

    The client's validator is generated from these files and committed, so a
    browser can end up holding a stale copy of it and rejecting perfectly good
    documents. Handing the client this hash lets it ask for its own build by
    content, which a cache cannot get wrong. Must match schemaHash() in
    client/tools/build-validator.js.
    """
    digest = hashlib.sha256()
    for filename in ("event_command.schema.json", "zone_package.schema.json", "ledger.schema.json"):
        digest.update((SCHEMA_DIR / filename).read_bytes())
    return digest.hexdigest()[:16]
