"""Loads the engine-owned registries the validator resolves references against.

These are the "something real" in design doc 4.4 check 3: every item_id, flag,
to_zone and encounter_id must resolve to one of these, or to the ledger.
"""

from __future__ import annotations

import functools
import json
import pathlib
from dataclasses import dataclass

REGISTRY_DIR = pathlib.Path(__file__).resolve().parents[1] / "registries"


@dataclass(frozen=True)
class Registries:
    items: dict[str, dict]
    encounters: dict[str, dict]
    enemy_templates: dict[str, dict]
    tilesets: dict[str, dict]
    sprite_tags: frozenset[str]
    sfx_tags: frozenset[str]
    music_tags: frozenset[str]

    def item_ids(self, ledger: dict | None = None) -> set[str]:
        """Core items plus the outline-defined key items carried on the ledger."""
        ids = set(self.items)
        if ledger:
            for defined in ledger.get("defined_items") or []:
                if isinstance(defined, dict) and "id" in defined:
                    ids.add(defined["id"])
        return ids


def _load(name: str) -> dict:
    return json.loads((REGISTRY_DIR / name).read_text())


@functools.lru_cache(maxsize=1)
def load_registries() -> Registries:
    items = _load("items.json")["items"]
    enc = _load("encounters.json")
    tiles = _load("tilesets.json")["tilesets"]
    tags = _load("tags.json")
    return Registries(
        items={i["id"]: i for i in items},
        encounters={e["id"]: e for e in enc["encounters"]},
        enemy_templates={t["id"]: t for t in enc["templates"]},
        tilesets=tiles,
        sprite_tags=frozenset(tags["sprite"]),
        sfx_tags=frozenset(tags["sfx"]),
        music_tags=frozenset(tags["music"]),
    )
