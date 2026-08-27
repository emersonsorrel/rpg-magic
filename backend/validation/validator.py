"""Semantic and referential validation (design doc 4.4).

The schema pass proves a document is well-shaped. This pass proves it is *true*:
that every id resolves, every entity stands somewhere a player can reach, and
every obligation the ledger pinned on this zone is actually discharged by it.

A Zone Package is always validated against a ledger -- a package has no meaning
without the world state it was authored into.
"""

from __future__ import annotations

from collections import deque

from .errors import Code, Report
from .registries import Registries, load_registries
from .schema import check_schema

# Mirrors the caps written into schemas/event_command.schema.json. Kept here as
# well so the semantic pass can report a precise code instead of a schema blob.
MAX_TEXT = 180
MAX_NESTING_DEPTH = 3

# op -> (required params, optional params). The closed vocabulary of design doc 3.3.
OP_PARAMS: dict[str, tuple[set[str], set[str]]] = {
    "SHOW_TEXT": ({"text"}, {"speaker"}),
    "SHOW_CHOICE": ({"prompt", "options"}, {"speaker"}),
    "SET_FLAG": ({"flag", "value"}, set()),
    "IF_FLAG": ({"flag", "then"}, {"else"}),
    "GIVE_ITEM": ({"item_id", "qty"}, set()),
    "TAKE_ITEM": ({"item_id", "qty"}, set()),
    "START_BATTLE": ({"encounter_id"}, {"on_win", "on_lose"}),
    "WARP": ({"to_zone", "to_x", "to_y"}, set()),
    "MOVE_ENTITY": ({"entity_id", "path"}, set()),
    "PLAY_SFX": ({"sfx_tag"}, set()),
    "WAIT": ({"frames"}, set()),
    "END": (set(), set()),
}


def iter_commands(script, path: str, depth: int = 1):
    """Walk a script depth-first, yielding (command, json path, nesting depth).

    Depth 1 is a top-level entity script; a command inside IF_FLAG.then is depth 2.
    """
    if not isinstance(script, list):
        return
    for index, cmd in enumerate(script):
        if not isinstance(cmd, dict):
            continue
        here = f"{path}[{index}]"
        yield cmd, here, depth
        op = cmd.get("op")
        if op == "IF_FLAG":
            yield from iter_commands(cmd.get("then"), f"{here}.then", depth + 1)
            yield from iter_commands(cmd.get("else"), f"{here}.else", depth + 1)
        elif op == "SHOW_CHOICE":
            options = cmd.get("options")
            if isinstance(options, list):
                for j, option in enumerate(options):
                    if isinstance(option, dict):
                        yield from iter_commands(
                            option.get("script"), f"{here}.options[{j}].script", depth + 1
                        )
        elif op == "START_BATTLE":
            yield from iter_commands(cmd.get("on_win"), f"{here}.on_win", depth + 1)
            yield from iter_commands(cmd.get("on_lose"), f"{here}.on_lose", depth + 1)


def _reachable_targets(ledger: dict, zone_id: str) -> set[str]:
    """Zones this one is allowed to warp to: its compass/stairs exits, plus any
    interior behind one of its doors."""
    zone = (ledger.get("zones") or {}).get(zone_id, {})
    return set((zone.get("exits") or {}).values()) | set(zone.get("interiors") or [])


def _zone_scripts(pkg: dict):
    """Every top-level script in the package, with the json path that reaches it."""
    for i, entity in enumerate(pkg.get("entities") or []):
        if isinstance(entity, dict) and isinstance(entity.get("script"), list):
            yield entity["script"], f"$.entities[{i}].script"


# --------------------------------------------------------------------------
# command-level checks
# --------------------------------------------------------------------------

def _check_commands(pkg: dict, ledger: dict, reg: Registries, report: Report) -> None:
    known_items = reg.item_ids(ledger)
    known_flags = set((ledger.get("flags") or {}).keys()) | set(pkg.get("declares_flags") or [])
    entity_ids = {
        e["id"] for e in (pkg.get("entities") or []) if isinstance(e, dict) and "id" in e
    }
    zone_id = pkg.get("id")
    declared_exits = _reachable_targets(ledger, zone_id)

    for script, base in _zone_scripts(pkg):
        for cmd, path, depth in iter_commands(script, base):
            op = cmd.get("op")

            if op not in OP_PARAMS:
                report.error(
                    Code.UNKNOWN_OP,
                    path,
                    f"'{op}' is not in the event command vocabulary. "
                    f"Allowed: {', '.join(sorted(OP_PARAMS))}.",
                )
                continue

            required, optional = OP_PARAMS[op]
            present = set(cmd) - {"op"}
            for missing in sorted(required - present):
                report.error(Code.MISSING_PARAM, path, f"{op} requires '{missing}'.")
            for extra in sorted(present - required - optional):
                report.error(
                    Code.UNKNOWN_PARAM, path, f"{op} has no parameter '{extra}'."
                )

            if depth > MAX_NESTING_DEPTH:
                report.error(
                    Code.NESTING_TOO_DEEP,
                    path,
                    f"nesting depth {depth} exceeds the cap of {MAX_NESTING_DEPTH}.",
                )

            for key in ("text", "prompt"):
                value = cmd.get(key)
                if isinstance(value, str):
                    if not value.strip():
                        report.error(Code.EMPTY_TEXT, f"{path}.{key}", "empty dialogue.")
                    elif len(value) > MAX_TEXT:
                        report.error(
                            Code.TEXT_TOO_LONG,
                            f"{path}.{key}",
                            f"{len(value)} chars, cap is {MAX_TEXT}.",
                        )

            if op in ("GIVE_ITEM", "TAKE_ITEM"):
                item_id = cmd.get("item_id")
                if isinstance(item_id, str) and item_id not in known_items:
                    report.error(
                        Code.UNKNOWN_ITEM,
                        path,
                        f"'{item_id}' is not in the item registry or ledger.defined_items.",
                    )

            if op in ("SET_FLAG", "IF_FLAG"):
                flag = cmd.get("flag")
                if isinstance(flag, str) and flag not in known_flags:
                    report.error(
                        Code.UNKNOWN_FLAG,
                        path,
                        f"'{flag}' is neither a ledger flag nor in this zone's declares_flags.",
                    )

            if op == "START_BATTLE":
                enc = cmd.get("encounter_id")
                if isinstance(enc, str) and enc not in reg.encounters:
                    report.error(
                        Code.UNKNOWN_ENCOUNTER, path, f"'{enc}' is not a known encounter."
                    )

            if op == "WARP":
                target = cmd.get("to_zone")
                if isinstance(target, str) and target not in declared_exits:
                    report.error(
                        Code.WARP_TARGET_UNDECLARED,
                        path,
                        f"WARP to '{target}', which is not a declared exit of {zone_id}.",
                    )

            if op == "MOVE_ENTITY":
                target = cmd.get("entity_id")
                if isinstance(target, str) and target not in entity_ids:
                    report.error(
                        Code.UNKNOWN_ENTITY, path, f"'{target}' is not an entity in this zone."
                    )

            if op == "PLAY_SFX":
                tag = cmd.get("sfx_tag")
                if isinstance(tag, str) and tag not in reg.sfx_tags:
                    report.warn(
                        Code.UNKNOWN_TAG, path, f"sfx tag '{tag}' is not in the tag vocabulary."
                    )


# --------------------------------------------------------------------------
# map-level checks
# --------------------------------------------------------------------------

def _check_map(pkg: dict, reg: Registries, report: Report) -> list[int] | None:
    width, height = pkg.get("width"), pkg.get("height")
    layers = pkg.get("layers") or {}
    if not isinstance(width, int) or not isinstance(height, int):
        return None

    expected = width * height
    tileset = reg.tilesets.get(pkg.get("tileset"))
    if tileset is None:
        report.error(
            Code.UNKNOWN_TILESET, "$.tileset", f"'{pkg.get('tileset')}' is not a known tileset."
        )
    tile_count = (tileset or {}).get("tile_count", 0)

    for name in ("ground", "decor", "collision"):
        layer = layers.get(name)
        if not isinstance(layer, list):
            continue
        if len(layer) != expected:
            report.error(
                Code.LAYER_SIZE_MISMATCH,
                f"$.layers.{name}",
                f"{len(layer)} tiles, expected width*height = {width}*{height} = {expected}.",
            )
        if tileset and name in ("ground", "decor"):
            for i, tile in enumerate(layer):
                if isinstance(tile, int) and tile >= tile_count:
                    report.error(
                        Code.TILE_OUT_OF_RANGE,
                        f"$.layers.{name}[{i}]",
                        f"tile index {tile} at ({i % width},{i // width}) is outside "
                        f"tileset '{pkg.get('tileset')}' (0..{tile_count - 1}).",
                    )
                    break  # one is enough; the whole layer is suspect

    collision = layers.get("collision")
    if isinstance(collision, list) and len(collision) == expected:
        return collision
    return None


def _reachable(collision: list[int], width: int, height: int, starts: list[tuple[int, int]]):
    """Flood fill over walkable tiles. Entity tiles count as walkable here: an
    entity stands on an open tile and blocks it only at runtime, so if the fill
    reaches its tile the player can at least stand next to it."""
    seen: set[tuple[int, int]] = set()
    queue = deque()
    for start in starts:
        x, y = start
        if 0 <= x < width and 0 <= y < height and not collision[y * width + x]:
            seen.add(start)
            queue.append(start)
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen:
                if not collision[ny * width + nx]:
                    seen.add((nx, ny))
                    queue.append((nx, ny))
    return seen


def _check_placement(pkg: dict, ledger: dict, reg: Registries, collision, report: Report) -> None:
    width, height = pkg.get("width"), pkg.get("height")
    entities = pkg.get("entities") or []
    warps = pkg.get("warps") or []

    def blocked(x: int, y: int) -> bool:
        return bool(collision[y * width + x]) if collision else False

    def in_bounds(x, y) -> bool:
        return isinstance(x, int) and isinstance(y, int) and 0 <= x < width and 0 <= y < height

    seen_ids: set[str] = set()
    for i, entity in enumerate(entities):
        if not isinstance(entity, dict):
            continue
        path = f"$.entities[{i}]"
        eid = entity.get("id")
        if eid in seen_ids:
            report.error(Code.DUPLICATE_ENTITY_ID, path, f"entity id '{eid}' appears twice.")
        seen_ids.add(eid)

        x, y = entity.get("x"), entity.get("y")
        if not in_bounds(x, y):
            report.error(
                Code.ENTITY_OUT_OF_BOUNDS, path, f"({x},{y}) is outside the {width}x{height} map."
            )
        elif blocked(x, y):
            report.error(
                Code.ENTITY_ON_BLOCKED_TILE,
                path,
                f"'{eid}' stands on a collision tile at ({x},{y}); it can never be interacted with.",
            )

        if entity.get("type") in ("npc", "chest", "sign") and not entity.get("script"):
            report.warn(Code.MISSING_SCRIPT, path, f"{entity.get('type')} '{eid}' has no script.")

        for tag in entity.get("sprite_tags") or []:
            if tag not in reg.sprite_tags:
                report.warn(
                    Code.UNKNOWN_TAG,
                    f"{path}.sprite_tags",
                    f"'{tag}' is not in the sprite tag vocabulary; will fall back to a generic sprite.",
                )

    zone_id = pkg.get("id")
    declared_exits = _reachable_targets(ledger, zone_id)
    known_items = reg.item_ids(ledger)

    for i, warp in enumerate(warps):
        if not isinstance(warp, dict):
            continue
        path = f"$.warps[{i}]"
        x, y = warp.get("x"), warp.get("y")
        if not in_bounds(x, y):
            report.error(Code.WARP_OUT_OF_BOUNDS, path, f"warp tile ({x},{y}) is off-map.")
        elif blocked(x, y):
            report.error(
                Code.WARP_ON_BLOCKED_TILE, path, f"warp tile ({x},{y}) is a collision tile."
            )

        target = warp.get("to_zone")
        if isinstance(target, str):
            if target not in (ledger.get("zones") or {}):
                report.error(
                    Code.UNKNOWN_ZONE, path, f"'{target}' does not exist in the ledger."
                )
            if target not in declared_exits:
                report.error(
                    Code.WARP_TARGET_UNDECLARED,
                    path,
                    f"'{target}' is not a declared exit of {zone_id}; "
                    f"declared: {sorted(declared_exits) or 'none'}.",
                )

        locked = warp.get("locked") or {}
        requires = locked.get("requires_item")
        if isinstance(requires, str):
            if requires not in known_items:
                report.error(
                    Code.UNKNOWN_ITEM,
                    f"{path}.locked.requires_item",
                    f"gate requires '{requires}', which is not a known item.",
                )
            else:
                _check_gate_order(ledger, warp, requires, path, report)

    # Reachability: a zone whose chest is walled off is a softlock waiting to happen.
    if collision and isinstance(width, int) and isinstance(height, int):
        starts = [(w["x"], w["y"]) for w in warps if isinstance(w, dict) and in_bounds(w.get("x"), w.get("y"))]
        pos = ledger.get("player_position") or {}
        if pos.get("zone") == zone_id and in_bounds(pos.get("x"), pos.get("y")):
            starts.append((pos["x"], pos["y"]))
        if not starts:
            report.error(
                Code.NO_ENTRY_POINT,
                "$.warps",
                "zone has no warp and is not the player's start; it can never be entered.",
            )
        else:
            reach = _reachable(collision, width, height, starts)
            for i, warp in enumerate(warps):
                if isinstance(warp, dict) and in_bounds(warp.get("x"), warp.get("y")):
                    if (warp["x"], warp["y"]) not in reach:
                        report.error(
                            Code.WARP_UNREACHABLE,
                            f"$.warps[{i}]",
                            f"warp at ({warp['x']},{warp['y']}) is cut off from every entry point.",
                        )
            for i, entity in enumerate(entities):
                if not isinstance(entity, dict):
                    continue
                x, y = entity.get("x"), entity.get("y")
                if in_bounds(x, y) and not blocked(x, y) and (x, y) not in reach:
                    report.error(
                        Code.ENTITY_UNREACHABLE,
                        f"$.entities[{i}]",
                        f"'{entity.get('id')}' at ({x},{y}) is walled off from every entry point.",
                    )


# --------------------------------------------------------------------------
# obligations -- the Fire Key check
# --------------------------------------------------------------------------

def _check_gate_order(ledger: dict, warp: dict, requires: str, path: str, report: Report) -> None:
    """The Fire Key rule, enforced at the door rather than at the key.

    Design doc 4.4: the validator "refuses to let the player reach `required_by`
    before the obligation is `placed`." A locked door is exactly that moment —
    committing one while its key still exists nowhere is how a run becomes
    unwinnable, and it is the single failure this project most wants to rule out.
    """
    obligation = next(
        (o for o in ledger.get("obligations", [])
         if isinstance(o, dict) and o.get("item_id") == requires),
        None,
    )
    if obligation is None:
        report.error(
            Code.GATE_WITHOUT_OBLIGATION,
            f"{path}.locked",
            f"the way to '{warp.get('to_zone')}' is locked behind '{requires}', which no "
            f"obligation is responsible for placing. Nothing guarantees it exists.",
        )
        return

    if obligation.get("status") == "open" or not obligation.get("placed_in"):
        report.error(
            Code.GATE_BEFORE_KEY,
            f"{path}.locked",
            f"this zone locks the way to '{warp.get('to_zone')}' behind "
            f"'{requires}', but {obligation['id']} has not been placed in any "
            f"committed zone yet. Committing this would strand the player.",
        )


def _obligation_satisfied(obligation: dict, pkg: dict) -> bool:
    kind = obligation.get("kind")
    for script, base in _zone_scripts(pkg):
        for cmd, _path, _depth in iter_commands(script, base):
            if kind == "key_item":
                if cmd.get("op") == "GIVE_ITEM" and cmd.get("item_id") == obligation.get("item_id"):
                    return True
            elif kind == "flag":
                if (
                    cmd.get("op") == "SET_FLAG"
                    and cmd.get("flag") == obligation.get("flag")
                    and cmd.get("value") is True
                ):
                    return True
    return False


def _check_obligations(pkg: dict, ledger: dict, report: Report) -> None:
    by_id = {
        o["id"]: o for o in (ledger.get("obligations") or []) if isinstance(o, dict) and "id" in o
    }
    zone_id = pkg.get("id")
    claimed = pkg.get("fulfills_obligations") or []

    for i, oid in enumerate(claimed):
        path = f"$.fulfills_obligations[{i}]"
        obligation = by_id.get(oid)
        if obligation is None:
            report.error(Code.UNKNOWN_OBLIGATION, path, f"'{oid}' is not in the ledger.")
            continue

        if obligation.get("kind") == "party_member":
            report.warn(
                Code.UNSUPPORTED_OBLIGATION_KIND,
                path,
                f"'{oid}' is kind 'party_member'; fulfilment for that kind is not checked yet.",
            )
        elif not _obligation_satisfied(obligation, pkg):
            want = obligation.get("item_id") or obligation.get("flag") or obligation.get("name")
            report.error(
                Code.OBLIGATION_UNFULFILLED,
                path,
                f"zone claims to discharge '{oid}' ({obligation.get('name')}) but nothing in it "
                f"places '{want}'. {obligation.get('required_by')} would be unreachable.",
            )

        placed_in = obligation.get("placed_in")
        if placed_in not in (None, zone_id):
            report.error(
                Code.OBLIGATION_ALREADY_PLACED,
                path,
                f"'{oid}' is already placed in '{placed_in}'; it cannot also be placed here.",
            )

    # And the other direction: the ledger says it lives here, the package forgot
    # to say so. Only meaningful while the zone is being authored -- once it is
    # committed, `placed_in` points at the package already on disk, and
    # re-validating it would flag itself.
    already_committed = ((ledger.get("zones") or {}).get(zone_id) or {}).get("committed") is True
    for oid, obligation in by_id.items():
        if already_committed:
            break
        if obligation.get("placed_in") == zone_id and oid not in claimed:
            report.error(
                Code.OBLIGATION_NOT_CLAIMED,
                "$.fulfills_obligations",
                f"ledger records '{oid}' as placed in {zone_id}, but the package does not claim it.",
            )


def _check_flag_hygiene(pkg: dict, ledger: dict, report: Report) -> None:
    declared = pkg.get("declares_flags") or []
    ledger_flags = set((ledger.get("flags") or {}).keys())
    used = set()
    for script, base in _zone_scripts(pkg):
        for cmd, _path, _depth in iter_commands(script, base):
            if cmd.get("op") in ("SET_FLAG", "IF_FLAG") and isinstance(cmd.get("flag"), str):
                used.add(cmd["flag"])
    for flag in declared:
        if flag in ledger_flags:
            report.warn(
                Code.FLAG_REDECLARED,
                "$.declares_flags",
                f"'{flag}' already exists in the ledger; declaring it again is a no-op.",
            )
        if flag not in used:
            report.warn(
                Code.UNUSED_FLAG, "$.declares_flags", f"'{flag}' is declared but never read or set."
            )


# --------------------------------------------------------------------------
# entry points
# --------------------------------------------------------------------------

def validate_zone_package(pkg, ledger: dict, registries: Registries | None = None) -> Report:
    """Full validation of one Zone Package in the context of a ledger.

    Structural errors do not stop the semantic pass -- a repair round-trip is more
    useful when it gets every problem at once, not the first one.
    """
    report = Report(subject=f"zone package {pkg.get('id') if isinstance(pkg, dict) else '<malformed>'}")
    reg = registries or load_registries()

    check_schema(pkg, "zone_package", report)
    if not isinstance(pkg, dict):
        return report

    collision = _check_map(pkg, reg, report)
    _check_placement(pkg, ledger, reg, collision, report)
    _check_commands(pkg, ledger, reg, report)
    _check_obligations(pkg, ledger, report)
    _check_flag_hygiene(pkg, ledger, report)

    music = pkg.get("music_tag")
    if isinstance(music, str) and music not in reg.music_tags:
        report.warn(Code.UNKNOWN_TAG, "$.music_tag", f"'{music}' is not in the music tag vocabulary.")

    return report


def validate_ledger(ledger, registries: Registries | None = None) -> Report:
    """Internal consistency of the World Ledger itself."""
    report = Report(subject="ledger")
    reg = registries or load_registries()

    check_schema(ledger, "ledger", report)
    if not isinstance(ledger, dict):
        return report

    zones = ledger.get("zones") or {}
    beats = {b["id"] for b in ((ledger.get("outline") or {}).get("beats") or []) if isinstance(b, dict)}
    known_items = reg.item_ids(ledger)

    for zone_id, zone in zones.items():
        if not isinstance(zone, dict):
            continue
        if zone.get("id") != zone_id:
            report.error(
                Code.DANGLING_ZONE_REF,
                f"$.zones.{zone_id}.id",
                f"key '{zone_id}' does not match id '{zone.get('id')}'.",
            )
        for direction, target in (zone.get("exits") or {}).items():
            if target not in zones:
                report.error(
                    Code.DANGLING_ZONE_REF,
                    f"$.zones.{zone_id}.exits.{direction}",
                    f"exit points at '{target}', which has no ledger entry.",
                )
            else:
                back = zones[target]
                # A parent lists its interiors in `interiors`, not `exits`, so an
                # interior's "out" is answered by the door that leads to it.
                returns = set((back.get("exits") or {}).values()) | set(back.get("interiors") or [])
                if zone_id not in returns:
                    report.warn(
                        Code.ASYMMETRIC_EXIT,
                        f"$.zones.{zone_id}.exits.{direction}",
                        f"'{target}' does not declare a way back to '{zone_id}'.",
                    )

    for i, obligation in enumerate(ledger.get("obligations") or []):
        if not isinstance(obligation, dict):
            continue
        path = f"$.obligations[{i}]"
        for field_name in ("required_by", "must_place_before", "placed_in"):
            target = obligation.get(field_name)
            if isinstance(target, str) and target not in zones:
                report.error(
                    Code.DANGLING_ZONE_REF,
                    f"{path}.{field_name}",
                    f"'{target}' has no ledger entry.",
                )
        beat = obligation.get("gates_beat")
        if isinstance(beat, str) and beat not in beats:
            report.error(Code.UNKNOWN_BEAT, f"{path}.gates_beat", f"'{beat}' is not an outline beat.")

        if obligation.get("kind") == "key_item":
            item_id = obligation.get("item_id")
            if not isinstance(item_id, str):
                report.error(
                    Code.BAD_OBLIGATION_STATE, path, "kind 'key_item' requires an item_id."
                )
            elif item_id not in known_items:
                report.error(
                    Code.UNKNOWN_ITEM, f"{path}.item_id", f"'{item_id}' is not a known item."
                )

        status, placed_in = obligation.get("status"), obligation.get("placed_in")
        if status == "open" and placed_in is not None:
            report.error(
                Code.BAD_OBLIGATION_STATE, path, f"status 'open' but placed_in is '{placed_in}'."
            )
        if status in ("placed", "consumed") and placed_in is None:
            report.error(
                Code.BAD_OBLIGATION_STATE, path, f"status '{status}' but placed_in is null."
            )

    for i, stack in enumerate(ledger.get("inventory") or []):
        if isinstance(stack, dict) and stack.get("item_id") not in known_items:
            report.error(
                Code.UNKNOWN_ITEM,
                f"$.inventory[{i}].item_id",
                f"'{stack.get('item_id')}' is not a known item.",
            )

    pos_zone = (ledger.get("player_position") or {}).get("zone")
    if isinstance(pos_zone, str) and pos_zone not in zones:
        report.error(
            Code.DANGLING_ZONE_REF, "$.player_position.zone", f"'{pos_zone}' has no ledger entry."
        )

    for i, member in enumerate(ledger.get("party") or []):
        # A party member who knows a skill nothing defines has a dead menu entry
        # the moment battles exist.
        if isinstance(member, dict):
            for j, skill in enumerate(member.get("skills") or []):
                if skill not in reg.skills:
                    report.error(
                        Code.UNKNOWN_SKILL,
                        f"$.party[{i}].skills[{j}]",
                        f"'{skill}' is not in the skill registry.",
                    )
        if isinstance(member, dict) and isinstance(member.get("hp"), int):
            if isinstance(member.get("max_hp"), int) and member["hp"] > member["max_hp"]:
                report.error(
                    Code.BAD_PARTY_STATE,
                    f"$.party[{i}]",
                    f"hp {member['hp']} exceeds max_hp {member['max_hp']}.",
                )

    return report
