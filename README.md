# rpg-magic

A procedurally generated, LLM-authored JRPG. The engine owns structure and truth;
the model authors content inside a schema the engine validates. See
`docs/design.md` for the full design.

**Status: M2 (Proc-gen + packaging) complete.** No LLM yet, by design.

## Quick start

Install:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && (cd client && npm install --ignore-scripts)
```

Play it — the authoring service serves the client too, so this is the only command:

```bash
.venv/bin/python -m uvicorn backend.app:app --port 8000
```

Then open http://127.0.0.1:8000/client/index.html

Tests:

```bash
.venv/bin/python -m pytest -q && (cd client && npm test)
```

Arrows or WASD to walk, Space/Enter to talk and advance text, Up/Down to pick an
option. Walk north out of town to reach the mine; the floor below it is generated
the first time you take the stairs. The seed box in the shell rebuilds the world.

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
  procgen/                     deterministic, LLM-free (rng, layout, town, dungeon)
  packaging/assemble.py        Layout + slots -> Zone Package
  world/                       ledger creation, persistence, the commit path
  app.py                       FastAPI authoring service; also serves the client
tests/                         119 tests: contracts, proc-gen properties, the API
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
- **Doors are collision tiles.** Interiors as separate small packages
  (open question 1) are still deferred — see the M2 notes below.

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

## Decisions taken during M2

- **Neighbouring zones agree on their shared door by derivation, not by
  patching.** A town is committed before the mine north of it exists, yet its
  warp has to name the exact tile the player lands on over there. Since
  committed is permanent, the arrival tile is made a pure function of
  `(seed, zone_id, edge)` — see `gateway()` / `arrival()` in `procgen/layout.py`.
  Both zones can compute it, and the second one to be generated treats it as a
  constraint it must leave walkable and connected. Zone *dimensions* are derived
  the same way, so a zone can reason about a neighbour that does not exist yet.
- **Connectivity is enforced, not hoped for.** The dungeon joins leftover
  components until one remains. A floor that strands its own stairs is the
  failure the obligation machinery exists to prevent.
- **Placeholder content is unmistakable.** Generated dialogue is bracketed and
  names the slot hint that produced it. Content that reads as authored but is
  not would make it impossible to tell later which zones the model has written.
- **The backend serves the client.** One origin, no CORS, one command to run
  everything.
- **The generated client validator is fingerprinted.** Changing a schema without
  rerunning `npm run build:validator` used to fail at runtime with a confusing
  rejection; now it fails a test that says what to run.
- **Deferred: town interiors.** Open question 1 (interiors as separate small
  packages) is listed under M2's town steps in the design doc, but the milestone
  gate does not need it and it is a milestone's worth of work on its own. Doors
  are still collision tiles. This is the one part of M2's brief left undone.

## Next: M3

The outline call, the zone-authoring call, the provider abstraction, the
validator's repair loop, and the template fallback. The seam is already open:
`world/authoring.py` runs proc-gen → assemble → validate → commit, and M3
inserts the authoring call between assemble and validate. *Done when: a fresh
seed produces a town whose NPCs discuss a coherent premise.*
