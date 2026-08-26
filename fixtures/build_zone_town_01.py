"""Expand the hand-drawn ASCII map into fixtures/zone_town_01.json.

The map and the entity scripts below are the hand-authored parts; this file only
mechanically flattens them into layer arrays. Re-run after editing either:

    python fixtures/build_zone_town_01.py
"""

import json
import pathlib

HERE = pathlib.Path(__file__).parent

# char -> (ground, decor, collision)
TILES = {
    ".": (1, 0, 0),
    ",": (2, 0, 0),
    "*": (1, 22, 0),
    "=": (4, 0, 0),
    "~": (3, 0, 1),
    "T": (1, 16, 1),
    "#": (1, 17, 1),
    "+": (1, 18, 1),
    "o": (1, 19, 1),
    "f": (1, 20, 1),
}

ENTITIES = [
    {
        "id": "npc_mayor_helle",
        "type": "npc",
        "x": 7,
        "y": 4,
        "sprite_tags": ["human", "elder", "authority", "biome:temperate"],
        "display_name": "Mayor Helle",
        "trigger": "interact",
        "script": [
            {
                "op": "IF_FLAG",
                "flag": "met_mayor",
                "then": [
                    {
                        "op": "SHOW_TEXT",
                        "speaker": "Mayor Helle",
                        "text": "Still here? The road north is open. I'd sooner you stayed and helped with the sandbags, but I know better than to ask twice.",
                    }
                ],
                "else": [
                    {
                        "op": "SHOW_TEXT",
                        "speaker": "Mayor Helle",
                        "text": "You'll be the ones from the guild, then. Callow Ford thanks you for coming, though I wish it were a happier errand.",
                    },
                    {
                        "op": "SHOW_TEXT",
                        "speaker": "Mayor Helle",
                        "text": "The mine flooded nine days ago. Since then the river runs warm, and nobody who walks up that road walks back down it.",
                    },
                    {
                        "op": "SHOW_CHOICE",
                        "speaker": "Mayor Helle",
                        "prompt": "Will you go up and look?",
                        "options": [
                            {
                                "label": "We'll go.",
                                "script": [
                                    {
                                        "op": "SHOW_TEXT",
                                        "speaker": "Mayor Helle",
                                        "text": "Then take what Dorn left in the chest by the south fence. He has not opened it in nine days and he will not open it now.",
                                    },
                                    {"op": "SET_FLAG", "flag": "mayor_warned_us", "value": True},
                                ],
                            },
                            {
                                "label": "Not yet.",
                                "script": [
                                    {
                                        "op": "SHOW_TEXT",
                                        "speaker": "Mayor Helle",
                                        "text": "No shame in that. Ask around first. Dorn at the south forge has more of the story than I do.",
                                    }
                                ],
                            },
                        ],
                    },
                    {"op": "SET_FLAG", "flag": "met_mayor", "value": True},
                ],
            }
        ],
    },
    {
        "id": "npc_smith_dorn",
        "type": "npc",
        "x": 13,
        "y": 10,
        "sprite_tags": ["human", "adult", "smith", "biome:temperate"],
        "display_name": "Dorn",
        "trigger": "interact",
        "script": [
            {
                "op": "SHOW_TEXT",
                "speaker": "Dorn",
                "text": "Forge is cold. You cannot keep coal lit when the air itself has gone wet, and it has been wet since the mine went under.",
            },
            {
                "op": "IF_FLAG",
                "flag": "has_ember_sigil",
                "then": [
                    {
                        "op": "SHOW_TEXT",
                        "speaker": "Dorn",
                        "text": "So you found it. That was my grandfather's. It was warm the day they cut the first shaft and it is warm now. Take it up there.",
                    }
                ],
                "else": [
                    {
                        "op": "SHOW_TEXT",
                        "speaker": "Dorn",
                        "text": "There is a chest by the south fence. Last thing my family kept out of that mine. It is yours if it gets the deep door open.",
                    }
                ],
            },
        ],
    },
    {
        "id": "chest_town_01a",
        "type": "chest",
        "x": 17,
        "y": 12,
        "sprite_tags": ["chest", "wooden"],
        "trigger": "interact",
        "once": True,
        "script": [
            {"op": "PLAY_SFX", "sfx_tag": "chest_open"},
            {"op": "GIVE_ITEM", "item_id": "ember_sigil", "qty": 1},
            {"op": "GIVE_ITEM", "item_id": "potion", "qty": 2},
            {
                "op": "SHOW_TEXT",
                "speaker": None,
                "text": "A warm sigil, faintly glowing, wrapped around two stoppered vials.",
            },
            {"op": "SET_FLAG", "flag": "has_ember_sigil", "value": True},
        ],
    },
]

WARPS = [
    {"x": 10, "y": 0, "to_zone": "zone_mine_b1", "to_x": 10, "to_y": 28}
]


def build():
    lines = [
        line
        for line in (HERE / "zone_town_01.map.txt").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    height = len(lines)
    width = len(lines[0])
    assert all(len(line) == width for line in lines), "ragged map"

    ground, decor, collision = [], [], []
    for row in lines:
        for ch in row:
            g, d, c = TILES[ch]
            ground.append(g)
            decor.append(d)
            collision.append(c)

    return {
        "schema_version": 1,
        "id": "zone_town_01",
        "kind": "town",
        "width": width,
        "height": height,
        "tile_size": 16,
        "tileset": "overworld_temperate",
        "layers": {"ground": ground, "decor": decor, "collision": collision},
        "entities": ENTITIES,
        "warps": WARPS,
        "encounters": {"enabled": False, "table": []},
        "music_tag": "town_calm",
        "summary": (
            "Callow Ford, a river town of nine houses, cut off to the south by "
            "high water. Nine days ago the mine upriver flooded and the river "
            "began to run warm. Mayor Helle wants it looked at; the smith Dorn "
            "wants it left alone."
        ),
        "declares_flags": ["has_ember_sigil", "mayor_warned_us"],
        "fulfills_obligations": ["obl_ember_sigil"],
        "proposals": [
            {
                "kind": "sidequest",
                "name": "The sandbag line",
                "summary": "Helle mentions sandbagging the south bank. There is no open slot for a fetch quest in this zone, so this stays flavour text with no mechanical effect.",
            }
        ],
    }


def main():
    out = HERE / "zone_town_01.json"
    out.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
