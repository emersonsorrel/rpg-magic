"""Generate the deliberately-broken zone packages the validator must reject.

Each mutation takes the known-good fixtures/zone_town_01.json and breaks exactly
one thing, in the shape a sloppy LLM authoring response actually breaks it. The
manifest records which error codes each file must produce, so a regression that
silently stops catching one of these fails the suite.

    python fixtures/broken/build_broken.py
"""

import copy
import json
import pathlib

HERE = pathlib.Path(__file__).parent
GOOD = HERE.parent / "zone_town_01.json"

MUTATIONS = {}


def mutation(filename, *codes, note):
    def register(fn):
        MUTATIONS[filename] = (fn, list(codes), note)
        return fn
    return register


def _entity(pkg, entity_id):
    return next(e for e in pkg["entities"] if e["id"] == entity_id)


@mutation("01_unknown_op.json", "unknown_op",
          note="Model invents a command outside the closed vocabulary.")
def unknown_op(pkg):
    chest = _entity(pkg, "chest_town_01a")
    chest["script"][0] = {"op": "SUMMON_DRAGON", "sfx_tag": "chest_open"}


@mutation("02_dangling_item.json", "unknown_item", "obligation_unfulfilled",
          note="Item id typo. Also breaks the obligation that depends on it.")
def dangling_item(pkg):
    chest = _entity(pkg, "chest_town_01a")
    chest["script"][1]["item_id"] = "ember_siggil"


@mutation("03_undeclared_flag.json", "unknown_flag",
          note="SET_FLAG on a flag that is neither in the ledger nor declared by the zone.")
def undeclared_flag(pkg):
    pkg["declares_flags"].remove("mayor_warned_us")


@mutation("04_nesting_too_deep.json", "nesting_too_deep",
          note="Fourth level of script nesting; the cap is 3.")
def nesting_too_deep(pkg):
    mayor = _entity(pkg, "npc_mayor_helle")
    option = mayor["script"][0]["else"][2]["options"][0]
    option["script"] = [
        {"op": "IF_FLAG", "flag": "met_mayor", "then": option["script"]}
    ]


@mutation("05_warp_undeclared_exit.json", "warp_target_undeclared", "unknown_zone",
          note="Warp to a zone the ledger never connected to this one.")
def warp_undeclared_exit(pkg):
    pkg["warps"][0]["to_zone"] = "zone_swamp_09"


@mutation("06_obligation_unfulfilled.json", "obligation_unfulfilled",
          note="The Fire Key problem. Zone is pinned to place the Ember Sigil and does not.")
def obligation_unfulfilled(pkg):
    chest = _entity(pkg, "chest_town_01a")
    chest["script"] = [c for c in chest["script"] if c.get("item_id") != "ember_sigil"]


@mutation("07_layer_size_mismatch.json", "layer_size_mismatch",
          note="Collision layer one tile short of width*height.")
def layer_size_mismatch(pkg):
    pkg["layers"]["collision"].pop()


@mutation("08_entity_in_wall.json", "entity_on_blocked_tile",
          note="NPC placed on a collision tile; unreachable forever.")
def entity_in_wall(pkg):
    dorn = _entity(pkg, "npc_smith_dorn")
    dorn["x"], dorn["y"] = 0, 10  # treeline


@mutation("09_text_too_long.json", "text_too_long", "schema",
          note="Dialogue past the 180-char box cap.")
def text_too_long(pkg):
    dorn = _entity(pkg, "npc_smith_dorn")
    dorn["script"][0]["text"] = (
        "Forge is cold, and it has been cold nine days now, and I will tell you "
        "the whole of it whether you asked or not, because nobody else in this "
        "town will say a word about what came up out of that water with the men "
        "who did not come up with it."
    )


@mutation("10_entity_unreachable.json", "entity_unreachable",
          note="Chest walled in. Schema-clean, id-clean, and still a softlock.")
def entity_unreachable(pkg):
    width = pkg["width"]
    for x, y in ((16, 12), (18, 12), (17, 11), (17, 13)):
        pkg["layers"]["collision"][y * width + x] = 1


@mutation("11_tile_out_of_range.json", "tile_out_of_range",
          note="Decor index past the end of the tileset.")
def tile_out_of_range(pkg):
    pkg["layers"]["decor"][0] = 999


def main():
    good = json.loads(GOOD.read_text())
    manifest = {}
    for filename, (mutate, codes, note) in MUTATIONS.items():
        pkg = copy.deepcopy(good)
        mutate(pkg)
        (HERE / filename).write_text(json.dumps(pkg, indent=2, ensure_ascii=False) + "\n")
        manifest[filename] = {"expect_error_codes": codes, "note": note}
    (HERE / "expected.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {len(manifest)} broken fixtures + expected.json")


if __name__ == "__main__":
    main()
