"""JSON Schemas for the two authoring calls (design doc 4.2, 4.3).

"Treat this exactly like a tool-calling schema. The model gets the palette; the
engine owns execution."

These are built from the live registries rather than hand-written, so an item
id or sprite tag the engine does not know is not merely rejected later -- it is
not expressible in the first place. The validator still runs afterwards; this
just removes the most common failure before it happens.

The command palette offered here is a *subset* of the full vocabulary in
schemas/event_command.schema.json. The engine owns warps, cutscene staging and
battles, so an author has no business emitting WARP, MOVE_ENTITY or
START_BATTLE while filling an NPC slot. Narrowing what is offered is cheaper
than validating what comes back.
"""

from __future__ import annotations

MAX_NESTING_DEPTH = 3
MAX_TEXT = 180


def _string(desc: str, *, max_length: int | None = None, enum: list | None = None) -> dict:
    node: dict = {"type": "string", "description": desc}
    if max_length:
        node["maxLength"] = max_length
    if enum:
        node["enum"] = enum
    return node


def _obj(properties: dict, description: str = "") -> dict:
    """Strict-mode object: every property required, nothing extra allowed."""
    node = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    if description:
        node["description"] = description
    return node


def command_schema(depth: int, *, items: list[str], flags: list[str]) -> dict:
    """One event command. Nesting is expressed by expansion rather than by
    recursion, which both fits strict JSON Schema and makes the depth cap
    structural instead of a rule someone has to remember."""
    show_text = _obj({
        "op": _string("always SHOW_TEXT", enum=["SHOW_TEXT"]),
        "speaker": _string("display name of the speaker, or empty for narration", max_length=48),
        "text": _string(f"one text box, at most {MAX_TEXT} characters", max_length=MAX_TEXT),
    }, "A line of dialogue.")

    set_flag = _obj({
        "op": _string("always SET_FLAG", enum=["SET_FLAG"]),
        "flag": _string("a flag from the list you were given, or one you declare", enum=flags) if flags
                else _string("flag name, lower_snake_case"),
        "value": {"type": "boolean", "description": "almost always true"},
    }, "Record that something happened, so other zones can react to it.")

    give_item = _obj({
        "op": _string("always GIVE_ITEM", enum=["GIVE_ITEM"]),
        "item_id": _string("must be one of these exact ids", enum=items),
        "qty": {"type": "integer", "minimum": 1, "maximum": 9},
    }, "Hand the party an item.")

    play_sfx = _obj({
        "op": _string("always PLAY_SFX", enum=["PLAY_SFX"]),
        "sfx_tag": _string("sound effect tag", enum=["chest_open", "door_open", "item_get", "text_blip"]),
    }, "A sound cue.")

    leaves = [show_text, set_flag, give_item, play_sfx]
    if depth >= MAX_NESTING_DEPTH:
        return {"anyOf": leaves}

    nested = {
        "type": "array",
        "minItems": 1,
        "maxItems": 6,
        "items": command_schema(depth + 1, items=items, flags=flags),
    }

    if_flag = _obj({
        "op": _string("always IF_FLAG", enum=["IF_FLAG"]),
        "flag": _string("the flag to test", enum=flags) if flags else _string("flag name"),
        "then": dict(nested, description="runs when the flag is set"),
        "else": dict(nested, description="runs when it is not"),
    }, "Say something different depending on what the party has already done.")

    show_choice = _obj({
        "op": _string("always SHOW_CHOICE", enum=["SHOW_CHOICE"]),
        "speaker": _string("who is asking", max_length=48),
        "prompt": _string("the question", max_length=MAX_TEXT),
        "options": {
            "type": "array",
            "minItems": 2,
            "maxItems": 3,
            "items": _obj({
                "label": _string("short button text", max_length=32),
                "script": dict(nested, description="what happens if this is picked"),
            }),
        },
    }, "Let the player answer.")

    return {"anyOf": leaves + [if_flag, show_choice]}


def zone_author_schema(*, slot_ids: list[str], sprite_tags: list[str], items: list[str],
                       flags: list[str]) -> dict:
    """Design doc 4.3 output: entity fills for each slot, plus a summary.

    Note what is absent: coordinates. The model receives slots, not a canvas,
    and never places anything spatially.
    """
    fill = _obj({
        "slot_id": _string("which slot this fills; use each exactly once", enum=slot_ids),
        "display_name": _string("the name shown in the dialogue box", max_length=32),
        "sprite_tags": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": _string("tag", enum=sprite_tags),
            "description": "how this character looks, chosen only from these tags",
        },
        "script": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": command_schema(1, items=items, flags=flags),
            "description": "what happens when the player interacts",
        },
    })

    proposal = _obj({
        "kind": _string("kind of thing", enum=["key_item", "sidequest", "npc", "location", "lore"]),
        "name": _string("short name", max_length=48),
        "summary": _string("one or two sentences", max_length=300),
    })

    schema = _obj({
        "summary": _string(
            "2-3 sentences describing this zone, written for another author who "
            "will never see the zone itself", max_length=380),
        "fills": {
            "type": "array",
            "minItems": len(slot_ids),
            "maxItems": len(slot_ids),
            "items": fill,
            "description": "exactly one entry per slot",
        },
        "declares_flags": {
            "type": "array",
            "maxItems": 6,
            "items": _string("new flag name, lower_snake_case"),
            "description": "flags this zone introduces; leave empty if none",
        },
        "proposals": {
            "type": "array",
            "maxItems": 3,
            "items": proposal,
            "description": (
                "ideas for content beyond this zone. These are never made real "
                "automatically -- leave empty unless you have a genuine one."
            ),
        },
    })
    schema["title"] = "zone_fill"
    return schema


def outline_schema() -> dict:
    """Design doc 4.2. Runs once at new-game and nothing downstream may
    contradict it."""
    beat = _obj({
        "id": _string("b1, b2, b3 ...", max_length=8),
        "summary": _string("what happens in this beat", max_length=300),
        "zone_hint": _string("where it happens, e.g. 'starting town'", max_length=80),
    })
    obligation = _obj({
        "kind": _string("always key_item for now", enum=["key_item"]),
        "name": _string("the item's display name", max_length=40),
        "gates_beat": _string("the beat id this unlocks", max_length=8),
    })
    party = _obj({
        "name": _string("given name, one word", max_length=16),
        "role": _string("what they do in a fight", max_length=40),
        "voice": _string("how they speak, in a few words", max_length=80),
    })

    schema = _obj({
        "tone": _string("a few words, e.g. 'melancholy pastoral fantasy'", max_length=80),
        "premise": _string("one or two sentences describing the situation", max_length=400),
        "antagonist": _obj({
            "name": _string("name or title", max_length=48),
            "motive": _string("what it wants and why", max_length=300),
        }),
        "beats": {
            "type": "array", "minItems": 3, "maxItems": 5, "items": beat,
            "description": "the spine of the story, in order",
        },
        "obligations": {
            "type": "array", "minItems": 1, "maxItems": 2, "items": obligation,
            "description": "key items that must exist before the beat they gate",
        },
        "party_seed": {
            "type": "array", "minItems": 2, "maxItems": 2, "items": party,
        },
    })
    schema["title"] = "outline"
    return schema
