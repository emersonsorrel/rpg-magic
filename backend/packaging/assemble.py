"""Turn a Layout into a Zone Package (design doc 3.2).

At M2 the slots are filled with placeholders. Proc-gen has decided how many
NPCs a zone supports and where they stand; the authoring pass in M3 replaces
what they say without touching where they are.

Placeholder dialogue is deliberately unmistakable. Content that reads as
authored but is not would make it impossible to tell, later, which zones the
model has actually written.
"""

from __future__ import annotations

import json
import pathlib

from ..procgen.layout import Layout, Slot

REGISTRY_DIR = pathlib.Path(__file__).resolve().parents[1] / "registries"
SCHEMA_VERSION = 1

ROLE_SPRITES = {
    "npc": ["human", "adult", "biome:temperate"],
    "shop": ["human", "adult", "merchant", "biome:temperate"],
    "inn": ["human", "elder", "merchant", "biome:temperate"],
    "chest": ["chest", "wooden"],
    "sign": ["signpost", "prop", "wooden"],
}

ROLE_NAMES = {
    "npc": "Villager",
    "shop": "Shopkeeper",
    "inn": "Innkeeper",
    "sign": "Signpost",
}

MUSIC = {"town": "town_calm", "dungeon": "dungeon_damp", "wilderness": "town_calm", "interior": "town_calm"}


def _slug(zone_id: str) -> str:
    return zone_id.replace("zone_", "", 1)


def _encounter_table(kind: str, tileset: str) -> dict:
    if kind != "dungeon":
        return {"enabled": False, "table": []}
    registry = json.loads((REGISTRY_DIR / "encounters.json").read_text())
    templates = {t["id"]: t for t in registry["templates"]}
    biome = next((tag for tag in _tileset_tags(tileset) if tag.startswith("biome:")), None)

    table = []
    for encounter in registry["encounters"]:
        tags = set()
        for member in encounter["members"]:
            tags.update(templates.get(member["template"], {}).get("tags", []))
        if biome and biome not in tags:
            continue
        table.append({
            "encounter_id": encounter["id"],
            "weight": max(1, 40 - encounter["base_level"] * 4),
            "level": encounter["base_level"],
        })
    return {"enabled": bool(table), "rate": 24, "table": table}


def _tileset_tags(tileset: str) -> list[str]:
    registry = json.loads((REGISTRY_DIR / "tilesets.json").read_text())
    return registry["tilesets"].get(tileset, {}).get("tags", [])


def _placeholder_script(slot: Slot, kind: str) -> list[dict]:
    """Clearly-unauthored content. The slot hint is carried into the text so a
    generated zone is debuggable by walking around in it."""
    if slot.kind == "chest":
        return [
            {"op": "PLAY_SFX", "sfx_tag": "chest_open"},
            {"op": "GIVE_ITEM", "item_id": "potion", "qty": 1},
            {"op": "SHOW_TEXT", "speaker": None,
             "text": f"[placeholder chest — {slot.hint or 'no hint'}]"},
        ]
    speaker = ROLE_NAMES.get(slot.kind, "Villager")
    return [
        {"op": "SHOW_TEXT", "speaker": speaker,
         "text": f"[placeholder {slot.kind} slot — {slot.hint or 'no hint'}. M3 authors this line.]"},
    ]


def _entities(layout: Layout, zone_id: str, kind: str) -> list[dict]:
    slug = _slug(zone_id)
    counters: dict[str, int] = {}
    entities = []

    for slot in layout.slots:
        counters[slot.kind] = counters.get(slot.kind, 0) + 1
        entity_type = {"chest": "chest", "sign": "sign"}.get(slot.kind, "npc")
        entity_id = f"{entity_type}_{slug}_{slot.kind}{counters[slot.kind]:02d}"

        entity = {
            "id": entity_id,
            "type": entity_type,
            "x": slot.x,
            "y": slot.y,
            "sprite_tags": _biome_tags(slot.kind, layout.tileset),
            "trigger": "interact",
            "script": _placeholder_script(slot, kind),
        }
        if entity_type != "chest":
            entity["display_name"] = ROLE_NAMES.get(slot.kind, "Villager")
        else:
            entity["once"] = True
        entities.append(entity)

    return entities


def _biome_tags(role: str, tileset: str) -> list[str]:
    tags = [t for t in ROLE_SPRITES.get(role, ROLE_SPRITES["npc"]) if not t.startswith("biome:")]
    tags.extend(_tileset_tags(tileset))
    return tags[:8]


def _summary(layout: Layout, zone_id: str, kind: str) -> str:
    counts: dict[str, int] = {}
    for slot in layout.slots:
        counts[slot.kind] = counts.get(slot.kind, 0) + 1
    described = ", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "no slots"
    return (
        f"Procedurally generated {kind} ({layout.width}x{layout.height}) with {described}. "
        f"Placeholder content only — the authoring pass has not run on this zone yet."
    )


def assemble(layout: Layout, zone_id: str, kind: str, *, fulfills: list[str] | None = None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "id": zone_id,
        "kind": kind,
        "width": layout.width,
        "height": layout.height,
        "tile_size": 16,
        "tileset": layout.tileset,
        "layers": {
            "ground": list(layout.ground),
            "decor": list(layout.decor),
            "collision": list(layout.collision),
        },
        "entities": _entities(layout, zone_id, kind),
        "warps": list(layout.warps),
        "encounters": _encounter_table(kind, layout.tileset),
        "music_tag": MUSIC.get(kind, "town_calm"),
        "summary": _summary(layout, zone_id, kind),
        "declares_flags": [],
        "fulfills_obligations": list(fulfills or []),
        "proposals": [],
    }
