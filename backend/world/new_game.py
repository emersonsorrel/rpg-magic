"""Build a starting ledger from a seed.

At M3 the outline call fills in tone, antagonist, beats and obligations. Until
then this writes an explicitly unauthored stub, plus the zone plan -- the graph
of zones that will exist, as uncommitted stubs. The stubs matter: an obligation
cannot name a zone that has no ledger node, and neither can a warp.
"""

from __future__ import annotations

from ..procgen.rng import derive

SCHEMA_VERSION = 1

# The fixed two-floor plan M2 generates. M3 derives this from the outline's beats.
ZONE_PLAN = {
    "zone_town_01": {
        "kind": "town",
        "exits": {"north": "zone_mine_b1"},
    },
    "zone_mine_b1": {
        "kind": "dungeon",
        "exits": {"south": "zone_town_01", "down": "zone_mine_b2"},
    },
    "zone_mine_b2": {
        "kind": "dungeon",
        "exits": {"up": "zone_mine_b1"},
    },
}

PARTY_NAMES = ("Wren", "Sabel", "Odie", "Marn")


def create(seed: int, premise: str | None = None) -> dict:
    zones = {
        zone_id: {
            "id": zone_id,
            "kind": plan["kind"],
            "committed": False,
            "exits": dict(plan["exits"]),
        }
        for zone_id, plan in ZONE_PLAN.items()
    }

    first = PARTY_NAMES[derive(seed, "party", 0) % len(PARTY_NAMES)]
    second = PARTY_NAMES[(derive(seed, "party", 1) % (len(PARTY_NAMES) - 1) + 1) % len(PARTY_NAMES)]
    if second == first:
        second = PARTY_NAMES[(PARTY_NAMES.index(first) + 1) % len(PARTY_NAMES)]

    return {
        "schema_version": SCHEMA_VERSION,
        "seed": seed,
        "premise": premise or "(unauthored — the outline pass arrives in M3)",
        "outline": {
            "tone": "unauthored",
            "antagonist": {
                "name": "Unauthored",
                "motive": "The outline call has not run. M3 replaces this with a real antagonist.",
            },
            "beats": [
                {
                    "id": "b1",
                    "summary": "Placeholder beat. Proc-gen runs without an outline at M2.",
                    "zone_hint": "starting town",
                    "status": "active",
                }
            ],
        },
        # Even with no outline, the world gets one real key item and one real
        # locked door. Without it an unauthored world has no gate at all, which
        # would leave the engine's central guarantee — that a run cannot be
        # softlocked — exercised only when a model happens to be reachable.
        # apply_outline() replaces both wholesale when the outline call runs.
        "obligations": [
            {
                "id": "obl_deep_key",
                "kind": "key_item",
                "name": "Deep Key",
                "item_id": "deep_key",
                "gates_beat": "b1",
                "required_by": "zone_mine_b2",
                "must_place_before": "zone_mine_b2",
                "placed_in": None,
                "status": "open",
            }
        ],
        "defined_items": [
            {
                "id": "deep_key",
                "name": "Deep Key",
                "kind": "key_item",
                "description": "Placeholder key. The outline pass names a real one.",
            }
        ],
        "zones": zones,
        "flags": {},
        "party": [
            _member("pc_01", first, atk=14, dfn=9, agi=11, mag=4, hp=44, mp=6, skills=["cut", "guard"]),
            _member("pc_02", second, atk=7, dfn=6, agi=13, mag=15, hp=31, mp=22, skills=["spark", "mend"]),
        ],
        "inventory": [{"item_id": "potion", "qty": 3}],
        # Provisional: replaced with the town's spawn tile once it is generated.
        "player_position": {"zone": "zone_town_01", "x": 1, "y": 1},
    }


def _member(pid, name, *, atk, dfn, agi, mag, hp, mp, skills):
    return {
        "id": pid,
        "name": name,
        "level": 3,
        "hp": hp,
        "max_hp": hp,
        "mp": mp,
        "max_mp": mp,
        "xp": 0,
        "stats": {"atk": atk, "def": dfn, "agi": agi, "mag": mag},
        "skills": skills,
    }
