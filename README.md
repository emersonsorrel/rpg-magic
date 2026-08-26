# rpg-magic

A procedurally generated, LLM-authored JRPG. The engine owns structure and truth;
the model authors content inside a schema the engine validates. See
`docs/design.md` for the full design.

**Status: M1 (Runtime on canned data) complete.** No backend, no LLM yet, by design.

## Quick start

Backend contracts and validator:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m backend.validation.cli --broken
.venv/bin/python -m pytest -q
```

Client:

```bash
cd client && npm install --ignore-scripts && npm test
```

Play it — serve the repo root, then open `/client/index.html`:

```bash
python3 -m http.server 5173 --directory "$(git rev-parse --show-toplevel)"
```

Arrows or WASD to walk, Space/Enter to talk and advance text, Up/Down to pick an
option. Walk up to Mayor Helle, Dorn, or the chest by the south fence.

### Why there is no bundler

The client is plain ES modules with an import map and **no build step**: Phaser's
prebuilt ESM dist is imported directly and any static file server will do. Vite
was the original plan (design doc 6), but the sandbox this repo is developed in
kills freshly-downloaded native binaries, so esbuild and rolldown cannot run.
Rather than half-verify the client, it was built to run without them.

The one thing this costs is JSX, so the M1 shell is plain DOM instead of React.
The React/Phaser boundary the design calls for is still there —
`src/game/GameBus.js` — and the shell talks to the game only across it, so
swapping in React later touches the shell and nothing else.

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
client/
  index.html                   import map + shell layout; no bundler
  src/game/
    EventRunner.js             framework-free interpreter -- no Phaser, no DOM
    WorldState.js              client-side ledger; owns facts, not presentation
    assetPack.js               tag-based sprite resolution (design doc 3.4)
    textures.js                placeholder art, drawn at boot
    zoneLoader.js              fetch + schema gate before anything renders
    GameBus.js                 the shell <-> Phaser seam
    scenes/                    Boot, Overworld, UI
    generated/validators.js    COMMITTED build output -- see below
  src/shell/DebugPanel.js      flags, inventory and a live event log
  tools/build-validator.js     /schemas -> standalone JS validator
  test/                        38 tests, run by node --test
```

`client/src/game/generated/validators.js` is generated from `/schemas` and
**committed on purpose** — there is no build step in the serve path, so the
browser fetches it directly. Regenerate it whenever a schema changes:

```bash
cd client && npm run build:validator
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

## Decisions taken during M1

- **No bundler** (see above). The knock-on effect is that Ajv's standalone output
  needs two runtime helpers it normally `require()`s; `tools/build-validator.js`
  inlines them and fails loudly if Ajv ever asks for a third.
- **The client validates shape, the backend validates meaning.** The generated
  validator rejects structurally wrong packages. Referential integrity,
  reachability and obligations stay in `backend/validation/` where they gate the
  commit — a client-side check of those would be theatre.
- **`once` entity state lives outside the ledger** for now (`WorldState.spent`).
  It needs a home in the ledger schema when save/load lands in M5.
- **Movement is buffered, not polled only.** A tap shorter than one frame used to
  be dropped; keydown now queues one step, and a press mid-step is held until the
  step lands. Direction keys match on both `KeyboardEvent.code` and `.key`,
  because `code` is absent on some synthetic and IME-generated events.
- **Unimplemented ops degrade to a labelled text box** rather than a crash:
  `START_BATTLE` says battles arrive in M4, `WARP` says the target zone is not
  authored yet. Both are clearly marked as placeholders on screen.

## Next: M2

Backend generates a town and a dungeon floor deterministically from a seed and
emits valid Zone Packages with placeholder-filled slots. The client swaps
`zoneLoader.js`'s two fixture URLs for `api.js` calls; nothing downstream of the
Zone Package needs to change. *Done when: two generated zones connect and are
walkable.*
