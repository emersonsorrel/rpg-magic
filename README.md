# rpg-magic

A procedurally generated, LLM-authored JRPG. The engine owns structure and truth;
the model authors content inside a schema the engine validates. See
`docs/design.md` for the full design.

**Status: M5 complete — all five milestones done.** The design doc calls M5
"the real test of the design"; the harness that proves it is
`tests/test_softlock.py`.

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
  app.py                       FastAPI authoring service; also serves the client
  registries/                  items, encounters, tilesets, tag vocabulary
  validation/                  schema pass + semantic/referential pass + CLI
  procgen/                     rng, layout, town, dungeon, ascii render
  packaging/assemble.py        Layout + slots (+ fills) -> Zone Package
  world/                       ledger store, new game, the commit path
  llm/
    provider.py                LLMProvider protocol + the test double
    openrouter.py, local.py    two implementations, one interface
    config.py                  role -> provider mapping from llm.yaml
    schemas.py                 response schemas built from the registries
    author.py                  outline + zone authoring + the repair ladder
    prompts/                   outline.md, zone_author.md
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
    scenes/                    Boot, Overworld, Battle, UI
    battle/
      engine.js                turn queue, actions, xp — no Phaser, no DOM
      formulas.js              every number in the battle system
      rng.js                   seeded, so a fight replays exactly
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

## Decisions taken during M3

- **Only OpenAI models are configured, and it is not about quality.** OpenRouter
  enforces `strict` json_schema server-side for some upstreams and not others.
  OpenAI models honour it. Anthropic models accept the request, return HTTP 200,
  and quietly ignore the schema once it is as nested as the event-command
  palette — measured, not assumed. Reaching those models properly needs the
  tool-calling path rather than `response_format`; that is a real change, not a
  config tweak. `llm.yaml` says all of this at the point of use.
- **A provider verifies its own output.** Because of the above, every response is
  validated against the schema that was requested before it is returned. A
  provider that silently stops enforcing a schema raises `LLMError` and drops
  into the repair ladder instead of poisoning a zone.
- **The engine normalises its own schema's side effects.** Strict mode requires
  *every* declared property, so a model with no speaker writes `speaker: ""` and
  an `IF_FLAG` with nothing to say writes `else: []` — both illegal in the
  command vocabulary. Left alone this failed validation on essentially every
  zone and burned the one repair round-trip on punctuation. `normalize_script`
  fixes it up front; fixing it took the town from `repaired` to `authored` and
  halved the cost per zone.
- **The model fills slots; the engine places them.** The authoring response has
  no coordinates in it at all. It cannot move an NPC even if it wants to.
- **The engine, not the model, decides where a key item goes.** The outline names
  what must exist and which beat it gates; `planned_placement` puts it in the
  zone before the one that needs it. That is the whole Fire Key mechanism, and
  the model never touches it.
- **Flags used but not declared are declared automatically.** The alternative is
  spending the one repair round-trip on bookkeeping. The cost is that a typo
  becomes a new flag rather than an error, so every auto-declaration is carried
  on the package where the shell can show it.
- **Tests never call an LLM.** The default run is offline and free; the live
  suite (`RPG_MAGIC_LIVE=1 pytest tests/test_live_llm.py`) exists to catch the
  one thing mocks cannot — a provider quietly ceasing to honour the schema.

Roughly $0.005 for the outline and $0.005–0.008 per zone at the configured
models, so a full three-zone world costs about two cents.

## What is deliberately missing

Named so it is not mistaken for finished work:

- **Shops and inns do not transact.** The slot kinds exist and get authored
  dialogue — a shopkeeper stands behind a real counter in a real room — but
  there is no buy/sell UI.
- **Death is a convenience, not a consequence.** Losing a fight puts the party
  back in town at half health. Now that saves exist, this is a design choice
  left open rather than a missing piece.
- **Enemies have no authored framing yet.** Design doc 7 allows the model to
  name enemies and write a boss's pre-fight lines. Encounters currently use the
  registry's display names.
- **Beats never advance.** `status` is written once at outline time and nothing
  moves it. M5's territory.

## Decisions taken while building interiors

Open question 1 asked whether a town is one zone or a zone plus interior
sub-zones, and recommended separate small packages. That is what these are.

- **Interiors are lazily generated like any other zone.** A town commits with a
  door per building and a stub in the ledger; the room behind it does not exist
  until somebody opens it. Entering costs one authoring call for a two- or
  three-slot room.
- **Interiors are not in `exits`.** `exits` is keyed by direction, and a town has
  one north road but eight front doors. They live in their own `interiors` list,
  which also keeps them out of the traversal spine that obligation placement
  walks — a key item behind a random front door would make "the zone before the
  door" meaningless.
- **Committing a zone can extend the zone graph.** Interior stubs are registered
  before the town package is validated, or its own door warps look like dangling
  references. The consequence is that anything iterating `ledger["zones"]` while
  generating must drain a queue rather than iterate the dict — which the property
  tests now do, and which incidentally gets every interior validated too.
- **The engine decides the doorstep.** A town knows where its own front steps
  are; an interior does not. The parent writes `return_to` into the stub, and
  the interior warps back to it — never onto the door tile, which would bounce
  the player straight back inside.
- **Traders moved indoors.** The street slots are all villagers now; the
  shopkeeper stands in a gap in their own counter, where a customer on the near
  side is directly facing them.
- **Furniture is placed, then unblocked.** Tables and counters go down without
  checking what they seal off, and anything left unreachable from the doorway is
  opened back up. A chest behind a table is the indoor version of the walled-off
  chest the M0 validator already refuses.

Two service fixes fell out of this:

- **`begin()` no longer saves the ledger before the starting town commits.** A
  second request arriving mid-generation was loading a world whose town was
  uncommitted and whose doors led nowhere. A single writer lock now serialises
  generation, which a client prefetching neighbours would have hit anyway.
- **The client asks for its validator by content.** The generated validator is
  build output, and a browser holding a stale copy rejects perfectly valid
  documents while blaming the backend. `/api/schema-version` reports the
  fingerprint of the schemas actually being served, and the client imports that
  exact build; static files are additionally served `no-store`.

## Decisions taken during M4

- **The battle engine is client-side, and framework-free.** Design doc 2 requires
  the game to stay playable with the backend offline, so combat cannot round-trip
  to a server. `battle/engine.js` knows nothing about Phaser or the DOM, exactly
  like the Event Runner, which is what lets 25 tests play whole fights headlessly.
- **Seeded and deterministic.** Same seed, same fight, every time. Damage
  variance comes from a seeded RNG rather than `Math.random`, because a damage
  roll that moves between runs makes every assertion about a battle a flake.
- **Every number lives in `battle/formulas.js`.** Damage, healing, flee odds, the
  XP curve, level-up gains and enemy scaling. Design doc 7 asked for the damage
  formula to be configurable in one place; this is that place, and nothing else
  in the battle code contains a constant.
- **Random encounters go through `START_BATTLE`.** Walking into a fight and being
  scripted into one are the same code path, through the Event Runner, so there is
  one thing to test and one thing to get wrong.
- **The engine never writes to the ledger mid-fight.** `commit()` moves hp, mp,
  xp, level and spent items across only once a battle has actually ended, so a
  fight abandoned halfway leaves no trace.
- **The backend owns the registries; the client owns the fight.** `/api/registries`
  serves items, skills and the bestiary so there is one definition of what a
  Potion does, and `/api/world/state` takes progress back — validated before it
  is written, since player progress is the only part of a committed world that is
  ever rewritten.
- **Skills are now a real registry.** Party members had been referencing `cut`,
  `guard`, `spark` and `mend`, none of which existed anywhere. The ledger
  validator now rejects a party member who knows a skill nothing defines.

## Decisions taken during M5

This is the milestone the design doc calls the real test, so the guarantee is
stated as an executable one: `tests/test_softlock.py` generates whole worlds
across seven seeds and walks each of them to a fixed point, opening a locked
door only when the key is genuinely in hand. Design doc 10 asked for exactly
this. It is checked in and runs in about two seconds.

- **The door stands one zone short of what it gates.** `required_by` names the
  zone a key lets you *into*, so the lock belongs on the near side of that
  threshold — and the key is placed a zone earlier still, so finding it and
  using it are separated by at least one place. With the default three-zone
  plan that puts the key in the town and the door in the mine, which is the
  design doc's own worked example.
- **The validator refuses the door, not the key.** Committing a locked warp
  whose obligation has not yet been placed in a committed zone raises
  `gate_before_key`. That is the exact moment a run becomes unwinnable, and it
  is the cheapest place to catch it.
- **The template fill places key items too.** It did not, which meant a world
  generated with no model could not be committed at all — the placeholder chest
  offered a potion where the obligation demanded a key, and the zone was
  rejected. Design doc 4.4 promises a failed call degrades to a boring zone,
  never to a broken gate; a template fill that dropped the key *was* the broken
  gate.
- **An unauthored world still gets a real gate.** `new_game` seeds one key item
  and one locked door, which `apply_outline` replaces wholesale when the outline
  call runs. Without it, a world generated offline had no obligations at all,
  and the engine's central guarantee would only ever have been exercised when a
  model happened to be reachable.
- **A save is the ledger plus its committed packages.** Committed is permanent
  (open question 2), so restoring a save has to bring back the exact zones that
  world had rather than regenerating them. Save names are validated before they
  become directory names.
- **The harness was checked for teeth.** Deliberately placing a key behind the
  door it opens fails 28 of its 29 assertions. A softlock test that cannot fail
  is worse than none, because it reads like proof.

## Prefetching (open question 3, resolved)

Open question 3 set the bar: "if local zone-authoring exceeds ~4 seconds,
prefetching becomes mandatory rather than an optimization." Authoring against a
hosted model takes roughly twenty, so it was mandatory.

`client/src/game/ZoneCache.js` warms neighbouring zones while the player stands
still. Measured on a cold world: walking into the mine went from a twenty-second
wait to a sub-second transition, most of which is the fade.

The policy is the interesting part, because a careless one speculatively authors
seven building interiors nobody enters and bills you for all of them:

- **Idle-gated.** A player crossing a town has not chosen a door yet, so nothing
  is speculated until they have been still for two seconds.
- **The spine before front doors.** A town has one road out and seven front
  doors; the road is far likelier.
- **Paid work is rationed, free work is not.** Warming an already-committed zone
  is one cheap round trip, so it is unrestricted. Building an uncommitted one
  costs a model call, so at most two are ever built ahead — a running total, not
  a per-tick allowance.
- **In-flight requests are shared.** Walking into a zone the prefetcher is
  already building waits for that build instead of starting a second one.
- **A failed prefetch is a non-event.** The player may never go there; if they
  do, the ordinary load surfaces the error properly.
- **There is an off switch** in the shell, because this spends money in the
  background.

## Beyond M5

What the design doc leaves open, roughly in the order it would pay off:

- **Shops and inns that transact.** The rooms, the counters and the shopkeepers
  all exist.
- **Beats that advance.** `status` is written once at outline time and nothing
  moves it, so the outline is a backdrop rather than a spine.
- **Authored enemy framing** (design doc 7): the model may name enemies and
  write a boss's pre-fight lines; encounters currently use registry names.
- **More world.** The zone plan is a fixed three-zone chain in `new_game`;
  deriving it from the outline's beats is the obvious next structural step.

## Retired: M5

The outline call, the zone-authoring call, the provider abstraction, the
validator's repair loop, and the template fallback. The seam is already open:
`world/authoring.py` runs proc-gen → assemble → validate → commit, and M3
inserts the authoring call between assemble and validate. *Done when: a fresh
seed produces a town whose NPCs discuss a coherent premise.*
