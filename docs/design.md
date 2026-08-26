# Design Document: Procedurally Generated, LLM-Authored JRPG Engine

**Working title:** `jrpg-forge` (rename freely — this is just the repo slug used throughout)
**Status:** Design draft, pre-implementation
**Target first milestone:** Playable vertical slice — one town, one dungeon, turn-based battles

---

## 1. Overview

A system that generates a playable 16-bit-style JRPG on demand. A large language model supplies narrative intent and content; a deterministic engine supplies structure, consistency, and enforcement. The player experiences a conventional tile-based JRPG — walk, talk, open chests, fight — but the world's content is authored lazily, zone by zone, as they approach it.

### Design thesis

The LLM is never the source of truth. It is a content author operating inside a schema the engine defines and validates. Every fact that must survive across zones lives in an engine-owned data structure (the **World Ledger**), not in the model's context. This is what prevents long-horizon drift: the model is never asked to remember, only to write within given constraints.

### Goals

- Generate a coherent short JRPG (a few hours of play) from a single seed prompt.
- Guarantee progression integrity — if a locked door exists, its key is reachable.
- Support both hosted (OpenRouter) and local (Ollama/llama.cpp) model backends via one interface.
- Keep the runtime fully deterministic and playable offline once zones are committed.
- Allow asset swapping: bundled default set, user-provided packs, or generated art — all through one tagged interface.

### Non-goals (v1)

- Open-ended sandbox play or 20+ hour campaigns.
- Real-time combat, multiplayer, or 3D.
- LLM involvement at frame time. All model calls happen at zone-generation boundaries, never during gameplay.
- Player free-text input. The player interacts through conventional JRPG verbs (move, talk, select), not by typing prose.

---

## 2. Architecture

Three layers, with a serialized document as the boundary between backend and client.

```
┌──────────────────────────────────────────────────────────┐
│  AUTHORING BACKEND — Python / FastAPI                    │
│                                                          │
│  World Ledger ──► Zone Generator ──► LLM Author          │
│       ▲                                   │              │
│       └────────── Validator / Commit ◄────┘              │
└──────────────────────────────────────────────────────────┘
                          │
                  Zone Package (JSON)
                          │
┌──────────────────────────────────────────────────────────┐
│  CLIENT RUNTIME — Phaser 3 inside React                  │
│                                                          │
│  Tilemap Renderer │ Event Runner │ Battle Engine │ UI    │
└──────────────────────────────────────────────────────────┘
```

**The backend is an authoring service, not a game loop.** It has no notion of frames, input, or animation. It answers one primary question: *"give me the committed Zone Package for zone X, generating it if it does not yet exist."*

**The client runtime is a conventional game engine.** It never calls an LLM. It consumes Zone Packages and executes them. Given a full set of committed packages, the game is playable with the backend offline.

---

## 3. Core data structures

These four schemas are the heart of the project. Get them right before writing much else.

### 3.1 World Ledger

Engine-owned source of truth. Persisted as JSON (v1) — Postgres/SQLite later if needed.

```jsonc
{
  "seed": 8471029,
  "premise": "user's one-line prompt",
  "outline": {
    "tone": "melancholy pastoral fantasy",
    "beats": [
      { "id": "b1", "summary": "...", "zone_hint": "starting town", "status": "done" },
      { "id": "b2", "summary": "...", "zone_hint": "flooded mine", "status": "active" }
    ],
    "antagonist": { "name": "...", "motive": "..." }
  },

  "obligations": [
    {
      "id": "obl_fire_key",
      "kind": "key_item",
      "name": "Ember Sigil",
      "required_by": "zone_mine_b3",
      "placed_in": null,            // engine fills on commit
      "must_place_before": "zone_mine_b3",
      "status": "open"              // open | placed | consumed
    }
  ],

  "zones": {
    "zone_town_01": {
      "id": "zone_town_01",
      "kind": "town",
      "committed": true,
      "summary": "Riverside town of Callow Ford; villagers fear the mine.",
      "exits": { "north": "zone_mine_b1" },
      "notable_entities": ["npc_mayor_helle", "npc_smith_dorn"]
    }
  },

  "flags": { "met_mayor": true, "mine_opened": false },
  "party": [ { "id": "pc_01", "name": "...", "level": 3, "hp": 44, "skills": ["cut"] } ],
  "inventory": [ { "item_id": "potion", "qty": 3 } ],
  "player_position": { "zone": "zone_town_01", "x": 12, "y": 9 }
}
```

**The `obligations` array is the mechanism that solves the "Fire Key problem."** The outline pass writes obligations. The zone generator consults them when deciding a new zone's constraints. The validator refuses to commit a zone that violates them, and refuses to let the player reach `required_by` before the obligation is `placed`.

### 3.2 Zone Package

The handoff artifact. One document fully describes one playable zone. Deliberately close to the Tiled TMJ shape so Phaser's tilemap loader needs minimal adaptation.

```jsonc
{
  "id": "zone_town_01",
  "kind": "town",
  "width": 40, "height": 30, "tile_size": 16,
  "tileset": "overworld_temperate",

  "layers": {
    "ground":   [ /* w*h tile indices */ ],
    "decor":    [ /* w*h, 0 = empty */ ],
    "collision":[ /* w*h, 0/1 */ ]
  },

  "entities": [
    {
      "id": "npc_mayor_helle",
      "type": "npc",
      "x": 14, "y": 8,
      "sprite_tags": ["human", "elder", "authority", "biome:temperate"],
      "display_name": "Mayor Helle",
      "trigger": "interact",
      "script": [ /* event commands, see 3.3 */ ]
    },
    {
      "id": "chest_town_01a",
      "type": "chest",
      "x": 30, "y": 21,
      "script": [
        { "op": "GIVE_ITEM", "item_id": "ember_sigil", "qty": 1 },
        { "op": "SHOW_TEXT", "speaker": null, "text": "A warm sigil, faintly glowing." },
        { "op": "SET_FLAG", "flag": "has_ember_sigil", "value": true }
      ]
    }
  ],

  "warps": [
    { "x": 20, "y": 0, "to_zone": "zone_mine_b1", "to_x": 10, "to_y": 28 }
  ],

  "encounters": {
    "enabled": false,
    "table": []
  },

  "music_tag": "town_calm"
}
```

### 3.3 Event command vocabulary

**This is the single most important constraint in the system.** The LLM never emits code. It emits arrays of commands drawn from a fixed, closed set that the Event Runner knows how to execute. Anything outside this vocabulary is rejected at validation.

| Op | Params | Notes |
|---|---|---|
| `SHOW_TEXT` | `speaker`, `text` | `text` capped at ~180 chars per command |
| `SHOW_CHOICE` | `prompt`, `options[]` | each option holds a nested `script` |
| `SET_FLAG` | `flag`, `value` | flag must already exist in ledger, or be declared in the zone's `declares_flags` |
| `IF_FLAG` | `flag`, `then[]`, `else[]` | nesting depth capped at 3 |
| `GIVE_ITEM` | `item_id`, `qty` | `item_id` must exist in the item registry |
| `TAKE_ITEM` | `item_id`, `qty` | |
| `START_BATTLE` | `encounter_id`, `on_win[]`, `on_lose[]` | |
| `WARP` | `to_zone`, `to_x`, `to_y` | target must be a declared exit |
| `MOVE_ENTITY` | `entity_id`, `path[]` | for cutscene staging |
| `PLAY_SFX` | `sfx_tag` | |
| `WAIT` | `frames` | |
| `END` | — | implicit terminator |

Treat this exactly like a tool-calling schema. The model gets the palette; the engine owns execution.

### 3.4 Asset manifest

Assets are addressed by **tags**, never by filename, so the default pack, a user pack, and generated art are interchangeable.

```jsonc
{
  "pack_id": "default_16bit",
  "sprites": [
    {
      "file": "npc_elder_01.png",
      "tags": ["human", "elder", "authority", "biome:temperate"],
      "frames": { "w": 16, "h": 24, "walk_down": [0,1,2,1] }
    }
  ],
  "tilesets": [ { "file": "overworld_temperate.png", "tags": ["biome:temperate"] } ]
}
```

Resolution rule: score candidates by tag overlap, break ties with the world seed for determinism. If nothing scores above a floor, fall back to a guaranteed-present generic sprite rather than failing. A missing asset must never block a commit.

---

## 4. LLM layer

### 4.1 Provider abstraction

One interface, two implementations, selected per call-site by config. This matters because the two call shapes have very different cost profiles.

```python
class LLMProvider(Protocol):
    async def complete(
        self, *, system: str, user: str, schema: dict, max_tokens: int
    ) -> dict: ...
```

- `OpenRouterProvider` — HTTP, model name from config, API key from env.
- `LocalProvider` — Ollama or llama.cpp server, same signature.

Config maps *roles* to providers, not calls to models:

```yaml
llm:
  outline:      { provider: openrouter, model: <strong model> }
  zone_author:  { provider: local,      model: <fast local model> }
  fallback:     { provider: openrouter, model: <mid model> }
```

Rationale: the outline call happens once and defines the whole game — worth spending on. Zone authoring happens dozens of times with narrow context — a good candidate for local inference.

### 4.2 Call A — Outline (rare, expensive)

**Input:** the user's premise, desired length, tone preferences.
**Output (JSON, schema-enforced):**

```jsonc
{
  "tone": "...",
  "antagonist": { "name": "...", "motive": "..." },
  "beats": [ { "id": "b1", "summary": "...", "zone_hint": "..." } ],
  "obligations": [ { "kind": "key_item", "name": "Ember Sigil", "gates_beat": "b3" } ],
  "party_seed": [ { "name": "...", "role": "...", "voice": "..." } ]
}
```

Runs once at new-game. Writes the ledger's outline and initial obligations. Nothing downstream may contradict it.

### 4.3 Call B — Zone authoring (frequent, narrow)

**Input (assembled by the engine, never by the model):**

- Zone shape already generated by proc-gen: dimensions, room graph, list of *slots* (`npc_slot`, `chest_slot`, `sign_slot`) with coordinates.
- Zone `kind` (town / dungeon / wilderness) and biome.
- Summaries of adjacent and recently visited zones (2–3 sentences each, from the ledger).
- Active story beat.
- **Obligations that must be fulfilled in this zone**, stated explicitly.
- Available sprite tag vocabulary.
- The event command palette.

**Output (JSON, schema-enforced):** entity fills for each slot — names, sprite tags, dialogue scripts, chest contents — plus a 2–3 sentence `summary` of the zone to be written back to the ledger.

Note the shape: the model receives *slots*, not a blank canvas. It never places anything spatially. It fills in meaning where the generator has already decided structure fits.

### 4.4 Validation and repair

Every authoring response passes through a validator before commit. Checks:

1. JSON parses; conforms to schema.
2. Every `op` is in the command vocabulary; nesting depth within limits.
3. Every `item_id`, `flag`, `to_zone`, `encounter_id` resolves to something real.
4. Every obligation marked `must_place_before` this zone is actually satisfied by the output.
5. No new obligations invented outside declared slots (see 4.5).
6. Text lengths within caps; no empty dialogue.

On failure: one repair round-trip with the specific validation errors appended, then fall back to a deterministic template fill (generic NPC, generic chest contents). **A failed LLM call must degrade to a boring zone, never to a crash or a broken gate.**

This is the same shape as the tag-healing pass in Inkwell, applied to JSON and to referential integrity rather than to markup.

### 4.5 Asymmetric trust on new content

The model may *propose* new content ("there should be a shrine needing three totems"). It becomes a real obligation only if the ledger has an open slot for one — otherwise it is downgraded to flavor text with no mechanical effect. Proposals arrive in a separate `proposals` field, never inline with committed content, so the distinction is structural rather than a matter of interpretation.

---

## 5. Procedural generation layer

Deterministic, seeded, LLM-free. Given `(seed, zone_id, kind, constraints)` it always produces the same layout.

- **Town:** road skeleton → building footprints along roads → interior warps → NPC slots on walkable tiles near buildings → shop/inn slots.
- **Dungeon floor:** BSP or cellular-automata rooms → corridor connection → guarantee connectivity → place chest slots in dead ends → stairs/warps → lock placement if a gate is required here.
- **Slot generation** is the key output. Proc-gen decides *how many* NPCs and chests a zone supports and *where* they stand. The LLM only decides *who* and *what*.

Constraint inputs from the ledger include: "this zone must contain a placement for `ember_sigil`," or "this zone must contain a locked exit requiring `ember_sigil`."

---

## 6. Client runtime (Phaser 3 in React)

Wrap the Phaser canvas in a React component. Don't try to drive Phaser's scene graph from React state — React owns the shell (menus, save/load, settings, debug panel), Phaser owns the game surface. They communicate through a small event emitter, not shared reactive state.

**Scenes:**

- `BootScene` — load asset manifest, resolve tag mappings.
- `OverworldScene` — tilemap from Zone Package (`Phaser.Tilemaps.Tilemap` built programmatically from layer arrays, not from a Tiled file), player controller, collision against the collision layer, entity sprites, interaction raycast.
- `BattleScene` — turn-based, launched over the paused overworld.
- `UIScene` — dialogue box, choices, menus; runs parallel to whichever scene is active.

**Event Runner** is a plain interpreter class, framework-agnostic and unit-testable in isolation: takes a command array, steps through it, yields on async ops (text advance, battle, movement). Keep it out of Phaser so it can be tested headlessly.

**Zone transitions:** on stepping onto a warp, the client requests the target Zone Package from the backend. If uncommitted, the backend generates it (proc-gen → LLM → validate → commit) while the client shows a transition screen. Prefetch adjacent zones in the background once the player is idle to hide latency.

---

## 7. Battle engine

Deterministic, no LLM at runtime.

- Classic turn-based: agility-ordered turn queue, Attack / Skill / Item / Flee.
- Damage formula configurable in one place; start simple (`atk² / (atk + def)` style) and tune.
- Enemy templates live in a registry keyed by tag (`undead`, `beast`, `biome:mine`); the zone's encounter table references template IDs plus level scaling.
- The LLM contributes only the *framing* at authoring time — enemy display names, a boss's pre-fight dialogue — via normal `SHOW_TEXT` and encounter references in the Zone Package.
- Party stats, HP, and inventory read from and write back to the ledger.

---

## 8. Repository layout

```
jrpg-forge/
├─ backend/
│  ├─ app.py                 # FastAPI entrypoint
│  ├─ ledger/                # World Ledger model, persistence, obligations
│  ├─ procgen/               # town.py, dungeon.py, slots.py
│  ├─ llm/
│  │  ├─ provider.py         # LLMProvider protocol
│  │  ├─ openrouter.py
│  │  ├─ local.py
│  │  ├─ prompts/            # outline.md, zone_author.md
│  │  └─ validate.py         # schema + referential checks + repair
│  ├─ packaging/             # ZonePackage assembly
│  └─ assets/                # manifest loading, tag resolution
├─ client/
│  ├─ src/
│  │  ├─ App.jsx             # React shell
│  │  ├─ game/
│  │  │  ├─ scenes/          # Boot, Overworld, Battle, UI
│  │  │  ├─ EventRunner.js   # framework-free interpreter
│  │  │  └─ battle/
│  │  └─ api.js
├─ packs/
│  └─ default_16bit/         # manifest.json + png files
└─ schemas/                  # JSON Schema for ledger, zone package, commands
```

Put the JSON Schemas in a shared top-level directory and generate validators on both sides from them. The schema is the contract between three parties (backend, client, model) — it should exist in exactly one place.

---

## 9. Milestones

**M0 — Contracts.** Write the JSON Schemas for Ledger, Zone Package, and the event command set. Write a hand-authored example Zone Package by hand. No code beyond validation. *Done when: a hand-written package validates.*

**M1 — Runtime on canned data.** Phaser client loads the hand-written package, renders tiles, walks a sprite, collides, triggers an NPC script through the Event Runner, shows dialogue. No backend, no LLM. *Done when: you can walk up to an NPC and read hand-written text.*

**M2 — Proc-gen + packaging.** Backend generates a town and a dungeon floor deterministically from a seed, emits valid Zone Packages with empty slots filled by placeholder entities. Client renders generated zones and warps between them. *Done when: two generated zones connect and are walkable.*

**M3 — LLM authoring.** Provider abstraction, outline call, zone-authoring call, validator, repair loop, template fallback. Slots fill with real content. *Done when: a fresh seed produces a town whose NPCs discuss a coherent premise.*

**M4 — Battles.** Battle scene, turn queue, enemy registry, encounter tables, `START_BATTLE` op, party progression written back to the ledger. *Done when: the dungeon has fights and the party levels.*

**M5 — Obligations end-to-end.** Locked door in the dungeon, key placed in the town, validator enforcing the ordering, save/load via ledger serialization. *Done when: a run cannot be softlocked.*

M5 is the real test of the design. Everything before it is scaffolding.

---

## 10. Testing strategy

- **Event Runner:** headless unit tests over command arrays. Highest-value tests in the project.
- **Validator:** fixture library of deliberately broken LLM outputs (bad ops, dangling item IDs, unmet obligations) that must all be caught.
- **Proc-gen:** property tests — every generated dungeon is fully connected; every required slot count is met; same seed produces identical output.
- **Obligation integrity:** a fuzz harness that generates N full games headlessly (no rendering, scripted traversal) and asserts no run is softlocked. Run this in CI; it is the cheapest guard against the failure mode that would most damage the experience.
- **LLM calls:** mock the provider in all tests except a small, manually-run live suite.

---

## 11. Open questions to resolve during build

1. **Zone granularity.** Is a town one zone or a zone plus interior sub-zones? Recommendation: interiors as separate small packages, generated with the town, to keep individual packages small.
2. **Regeneration policy.** Can a committed zone ever be re-authored? Default answer: no. Committed is permanent. Revisit only if content quality demands it.
3. **Latency budget.** How long is acceptable at a zone boundary? If local zone-authoring exceeds ~4 seconds, prefetching becomes mandatory rather than an optimization.
4. **Outline revision.** If the player does something the outline didn't anticipate, does the outline ever get amended mid-run? Simplest v1 answer: no — beats advance or stall, but never rewrite.
5. **Item registry authorship.** Fixed list, or can the outline call define new items? Recommendation: fixed core list plus a small number of outline-defined key items with mechanically generic behavior.
6. **Save format versioning.** Add a `schema_version` to the ledger from day one; you will change the schema.

---

## 12. Immediate first task for Claude Code

Start at M0. Concretely:

1. Create `schemas/event_command.schema.json` encoding the full command table from §3.3.
2. Create `schemas/zone_package.schema.json` and `schemas/ledger.schema.json`.
3. Hand-author `fixtures/zone_town_01.json` — a small 20×15 town with two NPCs, one chest, one warp.
4. Write a Python validator that loads the fixture and asserts conformance, plus five deliberately-broken variants that must fail with specific errors.

Do not start on Phaser until the fixture validates. The schemas are the project's spine; everything else is replaceable.
