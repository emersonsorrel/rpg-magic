import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { EventRunner, MAX_NESTING_DEPTH, UnknownOpError } from "../src/game/EventRunner.js";
import { WorldState, createHost } from "../src/game/WorldState.js";
import { makeIo } from "./helpers.js";

import ledgerFixture from "../../fixtures/ledger_new_game.json" with { type: "json" };
import townFixture from "../../fixtures/zone_town_01.json" with { type: "json" };

function harness(options = {}) {
  const world = new WorldState(ledgerFixture);
  world.declareFlags(townFixture.declares_flags);
  const io = makeIo(options);
  return { world, io, runner: new EventRunner(createHost(world, io)) };
}

const entity = (id) => townFixture.entities.find((e) => e.id === id);

describe("control flow", () => {
  it("runs commands in order", async () => {
    const { runner, io } = harness();
    await runner.run([
      { op: "SHOW_TEXT", speaker: null, text: "one" },
      { op: "SHOW_TEXT", speaker: null, text: "two" },
    ]);
    assert.deepEqual(io.texts(), ["one", "two"]);
  });

  it("takes the then branch when the flag is set", async () => {
    const { runner, io, world } = harness();
    world.setFlag("met_mayor", true);
    await runner.run([
      { op: "IF_FLAG", flag: "met_mayor", then: [{ op: "SHOW_TEXT", text: "known" }], else: [{ op: "SHOW_TEXT", text: "new" }] },
    ]);
    assert.deepEqual(io.texts(), ["known"]);
  });

  it("takes the else branch when the flag is unset", async () => {
    const { runner, io } = harness();
    await runner.run([
      { op: "IF_FLAG", flag: "met_mayor", then: [{ op: "SHOW_TEXT", text: "known" }], else: [{ op: "SHOW_TEXT", text: "new" }] },
    ]);
    assert.deepEqual(io.texts(), ["new"]);
  });

  it("skips a missing else branch without complaint", async () => {
    const { runner, io } = harness();
    const halted = await runner.run([
      { op: "IF_FLAG", flag: "met_mayor", then: [{ op: "SHOW_TEXT", text: "known" }] },
      { op: "SHOW_TEXT", text: "after" },
    ]);
    assert.equal(halted, false);
    assert.deepEqual(io.texts(), ["after"]);
  });

  it("sees a flag set earlier in the same script", async () => {
    const { runner, io } = harness();
    await runner.run([
      { op: "SET_FLAG", flag: "met_mayor", value: true },
      { op: "IF_FLAG", flag: "met_mayor", then: [{ op: "SHOW_TEXT", text: "now known" }] },
    ]);
    assert.deepEqual(io.texts(), ["now known"]);
  });

  it("runs the chosen option's script", async () => {
    const { runner, io } = harness({ choices: [1] });
    await runner.run([
      { op: "SHOW_CHOICE", prompt: "well?", options: [
        { label: "yes", script: [{ op: "SHOW_TEXT", text: "took yes" }] },
        { label: "no", script: [{ op: "SHOW_TEXT", text: "took no" }] },
      ] },
    ]);
    assert.deepEqual(io.texts(), ["took no"]);
  });

  it("throws if the host returns an out-of-range choice", async () => {
    const { runner } = harness({ choices: [7] });
    await assert.rejects(
      runner.run([
        { op: "SHOW_CHOICE", prompt: "?", options: [
          { label: "a", script: [{ op: "END" }] },
          { label: "b", script: [{ op: "END" }] },
        ] },
      ]),
      RangeError
    );
  });
});

describe("halting", () => {
  it("END stops the rest of the script", async () => {
    const { runner, io } = harness();
    const halted = await runner.run([
      { op: "SHOW_TEXT", text: "before" },
      { op: "END" },
      { op: "SHOW_TEXT", text: "after" },
    ]);
    assert.equal(halted, true);
    assert.deepEqual(io.texts(), ["before"]);
  });

  it("END inside a branch stops the outer script too", async () => {
    const { runner, io } = harness();
    await runner.run([
      { op: "IF_FLAG", flag: "met_mayor", else: [{ op: "SHOW_TEXT", text: "inner" }, { op: "END" }] },
      { op: "SHOW_TEXT", text: "outer after" },
    ]);
    assert.deepEqual(io.texts(), ["inner"]);
  });

  it("WARP halts, because the zone it was running in is gone", async () => {
    const { runner, io } = harness();
    const halted = await runner.run([
      { op: "WARP", to_zone: "zone_mine_b1", to_x: 10, to_y: 28 },
      { op: "SHOW_TEXT", text: "unreachable" },
    ]);
    assert.equal(halted, true);
    assert.deepEqual(io.texts(), []);
    assert.partialDeepStrictEqual(io.log[0], { kind: "warp", toZone: "zone_mine_b1", toX: 10, toY: 28 });
  });

  it("a battle loss with no on_lose handler halts", async () => {
    const { runner, io } = harness({ battles: ["lose"] });
    const halted = await runner.run([
      { op: "START_BATTLE", encounter_id: "mine_rats" },
      { op: "SHOW_TEXT", text: "victory speech" },
    ]);
    assert.equal(halted, true);
    assert.deepEqual(io.texts(), []);
  });

  it("runs on_win after a win and on_lose after a loss", async () => {
    for (const [outcome, expected] of [["win", "won"], ["lose", "lost"]]) {
      const { runner, io } = harness({ battles: [outcome] });
      await runner.run([
        { op: "START_BATTLE", encounter_id: "mine_rats",
          on_win: [{ op: "SHOW_TEXT", text: "won" }],
          on_lose: [{ op: "SHOW_TEXT", text: "lost" }] },
      ]);
      assert.deepEqual(io.texts(), [expected]);
    }
  });
});

describe("world effects", () => {
  it("GIVE_ITEM stacks onto an existing stack", async () => {
    const { runner, world } = harness();
    assert.equal(world.countItem("potion"), 3);
    await runner.run([{ op: "GIVE_ITEM", item_id: "potion", qty: 2 }]);
    assert.equal(world.countItem("potion"), 5);
  });

  it("GIVE_ITEM creates a stack for a new item", async () => {
    const { runner, world } = harness();
    await runner.run([{ op: "GIVE_ITEM", item_id: "ember_sigil", qty: 1 }]);
    assert.equal(world.countItem("ember_sigil"), 1);
  });

  it("TAKE_ITEM removes the stack when it empties", async () => {
    const { runner, world } = harness();
    await runner.run([{ op: "TAKE_ITEM", item_id: "bronze_sword", qty: 1 }]);
    assert.equal(world.countItem("bronze_sword"), 0);
    assert.equal(world.inventory.some((s) => s.item_id === "bronze_sword"), false);
  });

  it("does not mutate the fixture it was constructed from", async () => {
    const { runner, world } = harness();
    await runner.run([{ op: "SET_FLAG", flag: "met_mayor", value: true }]);
    assert.equal(world.getFlag("met_mayor"), true);
    assert.equal(ledgerFixture.flags.met_mayor, false);
  });
});

describe("guards", () => {
  it("rejects an op outside the vocabulary", async () => {
    const { runner } = harness();
    await assert.rejects(runner.run([{ op: "SUMMON_DRAGON" }]), UnknownOpError);
  });

  it("refuses to nest deeper than the validated cap", async () => {
    const { runner } = harness();
    const deep = { op: "IF_FLAG", flag: "met_mayor", else: [
      { op: "IF_FLAG", flag: "met_mayor", else: [
        { op: "IF_FLAG", flag: "met_mayor", else: [{ op: "SHOW_TEXT", text: "too deep" }] },
      ] },
    ] };
    await assert.rejects(runner.run([deep]), RangeError);
    assert.equal(MAX_NESTING_DEPTH, 3);
  });

  it("refuses to run two scripts at once", async () => {
    const { runner } = harness();
    let release;
    const gate = new Promise((resolve) => { release = resolve; });
    runner.host.showText = () => gate;
    const first = runner.run([{ op: "SHOW_TEXT", text: "holding" }]);
    await assert.rejects(runner.run([{ op: "SHOW_TEXT", text: "second" }]), /already running/);
    release();
    await first;
  });
});

describe("the hand-authored fixture", () => {
  it("plays the mayor's first meeting and sets both flags", async () => {
    const { runner, io, world } = harness({ choices: [0] });
    await runner.run(entity("npc_mayor_helle").script);

    assert.deepEqual(io.kinds(), ["text", "text", "choice", "text"]);
    assert.match(io.texts()[0], /from the guild/);
    assert.deepEqual(io.log[2].labels, ["We'll go.", "Not yet."]);
    assert.equal(world.getFlag("mayor_warned_us"), true);
    assert.equal(world.getFlag("met_mayor"), true);
  });

  it("plays the mayor's short line on a second meeting", async () => {
    const { runner, io, world } = harness();
    world.setFlag("met_mayor", true);
    await runner.run(entity("npc_mayor_helle").script);
    assert.deepEqual(io.kinds(), ["text"]);
    assert.match(io.texts()[0], /Still here\?/);
  });

  it("declining the mayor still records the meeting but not the warning", async () => {
    const { runner, world } = harness({ choices: [1] });
    await runner.run(entity("npc_mayor_helle").script);
    assert.equal(world.getFlag("met_mayor"), true);
    assert.equal(world.getFlag("mayor_warned_us"), false);
  });

  it("the chest hands over the Ember Sigil and flags it", async () => {
    const { runner, io, world } = harness();
    await runner.run(entity("chest_town_01a").script);
    assert.equal(world.countItem("ember_sigil"), 1);
    assert.equal(world.countItem("potion"), 5);
    assert.equal(world.getFlag("has_ember_sigil"), true);
    assert.partialDeepStrictEqual(io.log[0], { kind: "sfx", sfxTag: "chest_open" });
  });

  it("Dorn's line changes once the sigil is held", async () => {
    const before = harness();
    await before.runner.run(entity("npc_smith_dorn").script);
    assert.match(before.io.texts()[1], /chest by the south fence/);

    const after = harness();
    after.world.setFlag("has_ember_sigil", true);
    await after.runner.run(entity("npc_smith_dorn").script);
    assert.match(after.io.texts()[1], /my grandfather's/);
  });
});
