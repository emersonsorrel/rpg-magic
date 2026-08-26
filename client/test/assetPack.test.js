import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { PLACEHOLDER_PACK, resolveSprite } from "../src/game/assetPack.js";
import townFixture from "../../fixtures/zone_town_01.json" with { type: "json" };

const tagsFor = (id) => townFixture.entities.find((e) => e.id === id).sprite_tags;

describe("tag resolution", () => {
  it("picks the best tag overlap", () => {
    assert.equal(resolveSprite(tagsFor("npc_mayor_helle")).key, "sprite_elder");
    assert.equal(resolveSprite(tagsFor("npc_smith_dorn")).key, "sprite_smith");
    assert.equal(resolveSprite(tagsFor("chest_town_01a")).key, "sprite_chest");
  });

  it("falls back rather than failing when nothing scores", () => {
    const result = resolveSprite(["kraken", "biome:moon"]);
    assert.equal(result.fallback, true);
    assert.equal(result.key, PLACEHOLDER_PACK.fallback);
  });

  it("falls back on an entity with no tags at all", () => {
    assert.equal(resolveSprite([]).fallback, true);
    assert.equal(resolveSprite(undefined).fallback, true);
  });

  it("is deterministic for a given seed", () => {
    const first = resolveSprite(["human"], { seed: 8471029 }).key;
    for (let i = 0; i < 20; i += 1) {
      assert.equal(resolveSprite(["human"], { seed: 8471029 }).key, first);
    }
  });

  it("lets the seed decide a tie", () => {
    const keys = new Set();
    for (let seed = 0; seed < 64; seed += 1) keys.add(resolveSprite(["human"], { seed }).key);
    assert.ok(keys.size > 1, "seed never changed the pick");
  });

  it("never returns a key the pack does not contain", () => {
    const known = new Set(PLACEHOLDER_PACK.sprites.map((s) => s.key));
    for (const e of townFixture.entities) {
      assert.ok(known.has(resolveSprite(e.sprite_tags).key));
    }
  });
});
