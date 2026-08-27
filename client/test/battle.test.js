/**
 * The battle engine (design doc 7).
 *
 * Deterministic by construction, so every fight below plays out identically on
 * every run. Where a test needs a specific outcome it fixes the seed rather
 * than loosening the assertion.
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { Battle, buildEncounter, ENEMY, PARTY } from "../src/game/battle/engine.js";
import { physicalDamage, scaleTemplate, xpToNext } from "../src/game/battle/formulas.js";
import { makeRng } from "../src/game/battle/rng.js";

import encounters from "../../backend/registries/encounters.json" with { type: "json" };
import itemsRegistry from "../../backend/registries/items.json" with { type: "json" };
import skillsRegistry from "../../backend/registries/skills.json" with { type: "json" };

const SKILLS = Object.fromEntries(skillsRegistry.skills.map((s) => [s.id, s]));
const ITEMS = Object.fromEntries(itemsRegistry.items.map((i) => [i.id, i]));
const TEMPLATES = Object.fromEntries(encounters.templates.map((t) => [t.id, t]));
const ENCOUNTERS = Object.fromEntries(encounters.encounters.map((e) => [e.id, e]));

function member(overrides = {}) {
  return {
    id: "pc_01", name: "Wren", level: 3, hp: 44, max_hp: 44, mp: 10, max_mp: 10, xp: 0,
    stats: { atk: 14, def: 9, agi: 11, mag: 4 }, skills: ["cut", "guard"],
    ...overrides,
  };
}

function makeBattle({ party, encounterId = "mine_rats", level = 2, inventory = [], seed = 7 } = {}) {
  const enemies = buildEncounter(ENCOUNTERS[encounterId], TEMPLATES, level);
  return new Battle({
    party: party ?? [member()],
    enemies, skills: SKILLS, items: ITEMS, inventory, seed,
  });
}

/** Play to the end with a fixed policy, so outcomes are reproducible. */
function playOut(battle, choose = () => ({ type: "attack" })) {
  const log = [];
  for (let guard = 0; guard < 400 && !battle.finished; guard += 1) {
    const actor = battle.actor;
    if (!actor) break;
    log.push(...battle.act(choose(battle, actor)));
  }
  return log;
}

describe("encounter construction", () => {
  it("scales a template to the encounter level", () => {
    const base = TEMPLATES.beast_rat;
    const scaled = scaleTemplate(base, 5);
    assert.ok(scaled.hp > base.hp);
    assert.ok(scaled.stats.atk > base.atk);
    assert.ok(scaled.xp > base.xp);
  });

  it("level 1 is the template as written", () => {
    const scaled = scaleTemplate(TEMPLATES.beast_rat, 1);
    assert.equal(scaled.hp, TEMPLATES.beast_rat.hp);
    assert.equal(scaled.stats.atk, TEMPLATES.beast_rat.atk);
  });

  it("letters duplicates so they can be told apart", () => {
    const enemies = buildEncounter(ENCOUNTERS.mine_rats, TEMPLATES, 2);
    assert.equal(enemies.length, 3);
    assert.deepEqual(enemies.map((e) => e.name.slice(-1)), ["A", "B", "C"]);
  });

  it("leaves a lone enemy unlettered", () => {
    const enemies = buildEncounter(ENCOUNTERS.mine_drowned, TEMPLATES, 5);
    assert.equal(enemies.length, 1);
    assert.equal(enemies[0].name, "Drowned Miner");
  });
});

describe("determinism", () => {
  it("the same seed replays exactly", () => {
    const a = playOut(makeBattle({ seed: 99 }));
    const b = playOut(makeBattle({ seed: 99 }));
    assert.deepEqual(a, b);
  });

  it("a different seed diverges", () => {
    const a = JSON.stringify(playOut(makeBattle({ seed: 1 })));
    const b = JSON.stringify(playOut(makeBattle({ seed: 2 })));
    assert.notEqual(a, b);
  });

  it("the rng itself is stable", () => {
    const rolls = () => { const r = makeRng("mine_rats"); return [r(), r(), r()]; };
    assert.deepEqual(rolls(), rolls());
  });
});

describe("turn order", () => {
  it("is agility-ordered", () => {
    const battle = makeBattle({
      party: [member({ id: "slow", name: "Slow", stats: { atk: 9, def: 9, agi: 1, mag: 4 } })],
    });
    const agilities = battle.queue.map((c) => c.stats.agi);
    assert.deepEqual(agilities, [...agilities].sort((a, b) => b - a));
  });

  it("puts a fast party member first", () => {
    const battle = makeBattle({
      party: [member({ stats: { atk: 14, def: 9, agi: 99, mag: 4 } })],
    });
    assert.equal(battle.queue[0].id, "pc_01");
    assert.equal(battle.actor.id, "pc_01");
  });
});

describe("actions", () => {
  it("an attack takes hp off an enemy", () => {
    const battle = makeBattle();
    const before = battle.enemies[0].hp;
    const events = battle.act({ type: "attack", targetId: battle.enemies[0].id });
    const hit = events.find((e) => e.kind === "damage" && e.side === ENEMY);
    assert.ok(hit.amount > 0);
    assert.equal(battle.enemies[0].hp, before - hit.amount);
  });

  it("guarding reduces the damage taken", () => {
    const fixed = () => 0.5;   // lands exactly on the middle of the variance band
    const attacker = { stats: { atk: 20, def: 5, agi: 5, mag: 5 }, guarding: false };
    const open = { stats: { atk: 1, def: 8, agi: 1, mag: 1 }, guarding: false };
    const guarded = { ...open, guarding: true };
    assert.ok(physicalDamage(attacker, guarded, 1, fixed) < physicalDamage(attacker, open, 1, fixed));
  });

  it("an enemy faster than the whole party still gets its turn", () => {
    /* The queue opens on the enemy; the fight must not deadlock waiting for a
       command from someone who is not up yet. */
    const battle = makeBattle({
      party: [member({ stats: { atk: 14, def: 9, agi: 1, mag: 4 } })],
      encounterId: "mine_bats",
    });
    assert.ok(battle.openingEvents.length > 0, "the fast enemies should have acted");
    assert.ok(battle.actor, "control must come back to the party");
  });

  it("a skill costs mp", () => {
    const battle = makeBattle({ party: [member({ skills: ["spark"], stats: { atk: 7, def: 6, agi: 13, mag: 15 } })] });
    const before = battle.actor.mp;
    battle.act({ type: "skill", skillId: "spark", targetId: battle.enemies[0].id });
    assert.equal(battle.party[0].mp, before - SKILLS.spark.mp);
  });

  it("a skill the actor cannot afford does nothing", () => {
    const battle = makeBattle({ party: [member({ mp: 0, skills: ["spark"] })] });
    const enemyHp = battle.enemies.map((e) => e.hp);
    battle.act({ type: "skill", skillId: "spark", targetId: battle.enemies[0].id });
    assert.deepEqual(battle.enemies.map((e) => e.hp), enemyHp);
  });

  it("options() reports what is actually affordable", () => {
    const battle = makeBattle({ party: [member({ mp: 0, skills: ["spark", "guard"] })] });
    const byId = Object.fromEntries(battle.options().skills.map((s) => [s.id, s.usable]));
    assert.equal(byId.spark, false);
    assert.equal(byId.guard, true);
  });

  it("healing is capped at max hp", () => {
    // act() also runs every enemy turn up to the party's next one, so the
    // assertion is on the heal itself rather than on hp afterwards.
    const battle = makeBattle({
      party: [member({ hp: 20, max_hp: 44, skills: ["mend"], mp: 10 })],
    });
    const events = battle.act({ type: "skill", skillId: "mend", targetId: "pc_01" });
    const heal = events.find((e) => e.kind === "heal");
    assert.ok(heal, "expected a heal event");
    assert.ok(heal.hp <= 44, `healed past max hp: ${heal.hp}`);
  });

  it("healing never overshoots into a bigger number than the deficit", () => {
    const battle = makeBattle({
      party: [member({ hp: 43, max_hp: 44, skills: ["mend"], mp: 10 })],
    });
    const heal = battle.act({ type: "skill", skillId: "mend", targetId: "pc_01" })
      .find((e) => e.kind === "heal");
    assert.equal(heal.hp, 44);
    assert.ok(heal.amount <= 44 - 1, "reported more healing than was missing");
  });

  it("an item heals and is only spent on commit", () => {
    const inventory = [{ item_id: "potion", qty: 3 }];
    // Tanky enough to survive the opening enemy turns, hurt enough to heal.
    const battle = makeBattle({
      party: [member({ hp: 20, max_hp: 44, stats: { atk: 14, def: 60, agi: 11, mag: 4 } })],
      inventory,
    });
    const events = battle.act({ type: "item", itemId: "potion", targetId: "pc_01" });
    const heal = events.find((e) => e.kind === "heal");
    assert.ok(heal && heal.amount > 0, "the potion should have healed something");
    assert.equal(inventory[0].qty, 3, "inventory must not change mid-fight");

    playOut(battle);
    if (battle.finished) battle.commit();
    assert.equal(inventory[0].qty, 2, "the potion is spent once the fight ends");
  });
});

describe("ending a fight", () => {
  it("wins when the last enemy falls, and pays out xp", () => {
    const battle = makeBattle({
      party: [member({ stats: { atk: 400, def: 40, agi: 99, mag: 4 } })],
    });
    const log = playOut(battle);
    assert.equal(battle.state, "won");
    assert.ok(log.some((e) => e.kind === "victory"));
    assert.ok(battle.result.xp > 0);
  });

  it("levels the party up off the back of a win", () => {
    /* The milestone's gate: the dungeon has fights and the party levels. */
    const weakling = member({ level: 1, xp: xpToNext(1) - 1, stats: { atk: 400, def: 40, agi: 99, mag: 4 } });
    const battle = makeBattle({ party: [weakling] });
    playOut(battle);
    assert.equal(battle.state, "won");
    assert.ok(battle.result.levelUps.length >= 1, "expected a level-up");
    assert.equal(battle.party[0].level, 2);
    assert.ok(battle.party[0].maxHp > weakling.max_hp);
  });

  it("loses when the party is wiped", () => {
    const battle = makeBattle({
      party: [member({ hp: 1, max_hp: 1, stats: { atk: 1, def: 1, agi: 1, mag: 1 } })],
      encounterId: "mine_drowned", level: 9,
    });
    playOut(battle);
    assert.equal(battle.state, "lost");
    assert.equal(battle.result.outcome, "lost");
  });

  it("the fallen learn nothing", () => {
    const alive = member({ id: "pc_alive", name: "Alive", stats: { atk: 400, def: 40, agi: 99, mag: 4 } });
    const downed = member({ id: "pc_downed", name: "Downed", hp: 0, stats: { atk: 1, def: 1, agi: 1, mag: 1 } });
    const battle = makeBattle({ party: [alive, downed] });
    playOut(battle);
    assert.equal(battle.state, "won");
    assert.equal(battle.party.find((c) => c.id === "pc_downed").xp, 0);
    assert.ok(battle.party.find((c) => c.id === "pc_alive").xp > 0);
  });

  it("fleeing ends the fight without a payout", () => {
    const battle = makeBattle({
      party: [member({ stats: { atk: 14, def: 9, agi: 999, mag: 4 } })], seed: 3,
    });
    let fled = false;
    for (let i = 0; i < 40 && !battle.finished; i += 1) {
      const events = battle.act({ type: "flee" });
      if (events.some((e) => e.kind === "flee" && e.ok)) fled = true;
    }
    assert.ok(fled, "a very fast party should escape within 40 tries");
    assert.equal(battle.state, "fled");
    assert.equal(battle.result.xp, 0);
  });
});

describe("writing back to the ledger", () => {
  it("commit() moves hp, mp, xp and level onto the party", () => {
    const party = [member({ level: 1, xp: xpToNext(1) - 1, stats: { atk: 400, def: 40, agi: 99, mag: 4 } })];
    const battle = makeBattle({ party });
    playOut(battle);
    battle.commit();
    assert.equal(party[0].level, 2);
    assert.equal(party[0].hp, battle.party[0].hp);
    assert.equal(party[0].max_hp, battle.party[0].maxHp);
    assert.equal(party[0].stats.atk, battle.party[0].stats.atk);
  });

  it("nothing is written while the fight is still running", () => {
    const party = [member()];
    const battle = makeBattle({ party });
    battle.act({ type: "attack", targetId: battle.enemies[0].id });
    assert.throws(() => battle.commit(), /still running/);
    assert.equal(party[0].hp, 44, "the ledger must be untouched mid-fight");
  });
});
