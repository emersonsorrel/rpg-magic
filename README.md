# jrpg-forge

A procedurally generated, LLM-authored JRPG. The engine owns structure and truth;
the model authors content inside a schema the engine validates. See
`docs/design.md` for the full design.

**Status: M0 (Contracts) complete.** No Phaser yet, by design.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m backend.validation.cli --broken
.venv/bin/python -m pytest -q
```

## What exists

```
schemas/            the contract between backend, client and model
  event_command.schema.json    closed command vocabulary (design doc 3.3)
  zone_package.schema.json     the backend -> client handoff artifact
  ledger.schema.json           World Ledger; doubles as the save file
fixtures/
  zone_town_01.map.txt         hand-drawn ASCII map -- the authoring surface
  build_zone_town_01.py        expands map + scripts into the package below
  zone_town_01.json            hand-authored 20x15 town, 2 NPCs, 1 chest, 1 warp
  ledger_new_game.json         matching ledger
  broken/                      11 deliberately-broken packages + expected.json
backend/
  registries/                  items, encounters, tilesets, tag vocabulary
  validation/                  schema pass + semantic/referential pass + CLI
tests/                         33 tests; the M0 acceptance gate
```

Edit `fixtures/zone_town_01.map.txt` or the entity scripts, then re-run
`python fixtures/build_zone_town_01.py` and `python fixtures/broken/build_broken.py`.

## Validation model

Two passes, both run even if the first fails -- a repair round-trip is more useful
when it gets every problem at once.

1. **Schema pass** proves the document is well-shaped.
2. **Semantic pass** proves it is *true*: ids resolve, entities stand somewhere a
   player can reach, obligations are discharged.

**Errors block a commit. Warnings never do.** That split exists because of the
asset rule in design doc 3.4 -- an unresolvable sprite tag degrades to a generic
sprite, it does not stop a zone from being committed.

A Zone Package is always validated *against a ledger*. A package has no meaning
without the world state it was authored into.

## Decisions taken during M0

Choices the design doc left open or did not cover, resolved here:

- **Planned zones exist as ledger stubs.** An obligation referencing
  `zone_mine_b3` requires that zone to be a node in the ledger (`committed:
  false`) before it is generated. Without this the ordering guarantee is
  uncheckable. The outline pass creates stubs from its beats.
- **`fulfills_obligations`** added to the Zone Package: engine-owned, written from
  ledger constraints *before* authoring. This makes design doc check 4 concrete --
  the validator refuses to commit unless each claimed obligation is actually
  discharged by the zone's contents. `06_obligation_unfulfilled.json` is that test.
- **`declares_flags`** added, per the SET_FLAG note in 3.3. A flag must be in the
  ledger or declared by the zone.
- **`defined_items` on the ledger** resolves open question 5: fixed core registry
  plus a small number of outline-defined key items, no new mechanics.
- **Reachability is validated**, beyond the doc's list. A flood fill from every
  entry point must reach every entity and warp. A chest that is schema-clean,
  id-clean and walled off is still a softlock (`10_entity_unreachable.json`).
- **`MOVE_ENTITY.path` is absolute tile coordinates**, not relative steps, so a
  partially-run cutscene cannot drift.
- **`schema_version` on both the ledger and the package** from day one (open
  question 6).
- **Doors are collision tiles at M0.** Interiors as separate small packages
  (open question 1) lands in M2.

## Next: M1

Phaser client loads `fixtures/zone_town_01.json`, renders the three layers, walks
a sprite, collides, and runs `npc_mayor_helle`'s script through the Event Runner.
No backend, no LLM. Generate the JS validator from the same `schemas/` directory --
the contract lives in exactly one place.
