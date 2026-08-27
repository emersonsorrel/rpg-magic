/**
 * The battle engine (design doc 7).
 *
 * Deterministic, no LLM, no Phaser, no DOM — the same discipline as the Event
 * Runner, and for the same reason: a fight has to be reproducible in a test.
 * Given the same seed and the same inputs it plays out identically every time.
 *
 * The model contributes only framing at authoring time — an enemy's display
 * name, a boss's pre-fight SHOW_TEXT. Nothing here asks it anything.
 */

import {
  fleeChance, healAmount, levelUpGains, magicDamage, physicalDamage,
  scaleTemplate, xpToNext,
} from "./formulas.js";
import { makeRng } from "./rng.js";

export const PARTY = "party";
export const ENEMY = "enemy";

/** Turn an encounter definition into combatants, scaled to level. */
export function buildEncounter(encounter, templates, level, { rng } = {}) {
  const enemies = [];
  const counts = new Map();

  for (const member of encounter.members) {
    const template = templates[member.template];
    if (!template) continue;
    for (let i = 0; i < (member.count ?? 1); i += 1) {
      const scaled = scaleTemplate(template, level);
      const seen = (counts.get(template.id) ?? 0) + 1;
      counts.set(template.id, seen);
      enemies.push({
        id: `${template.id}_${seen}`,
        name: encounter.display_name ?? template.id,
        templateId: template.id,
        tags: template.tags ?? [],
        side: ENEMY,
        level,
        hp: scaled.hp,
        maxHp: scaled.hp,
        mp: 10,
        maxMp: 10,
        stats: scaled.stats,
        skills: template.skills ?? [],
        xp: scaled.xp,
        guarding: false,
      });
    }
  }
  // Several of the same creature get letters, so "Cave Rat B" is targetable.
  const byTemplate = new Map();
  for (const enemy of enemies) {
    byTemplate.set(enemy.templateId, (byTemplate.get(enemy.templateId) ?? 0) + 1);
  }
  const running = new Map();
  for (const enemy of enemies) {
    if (byTemplate.get(enemy.templateId) > 1) {
      const n = (running.get(enemy.templateId) ?? 0);
      running.set(enemy.templateId, n + 1);
      enemy.name = `${enemy.name} ${String.fromCharCode(65 + n)}`;
    }
  }
  return enemies;
}


export class Battle {
  /**
   * @param party     ledger party members; mutated only by commit()
   * @param enemies   from buildEncounter
   * @param skills    id -> skill definition
   * @param items     id -> item definition
   * @param inventory ledger inventory array; mutated only by commit()
   */
  constructor({ party, enemies, skills = {}, items = {}, inventory = [], seed = 1 }) {
    this.rng = makeRng(seed);
    this.skills = skills;
    this.items = items;
    this.sourceParty = party;
    this.sourceInventory = inventory;
    this.spentItems = [];

    this.party = party.map((member) => ({
      id: member.id,
      name: member.name,
      side: PARTY,
      level: member.level,
      hp: member.hp,
      maxHp: member.max_hp,
      mp: member.mp ?? 0,
      maxMp: member.max_mp ?? 0,
      stats: { ...member.stats },
      skills: [...(member.skills ?? [])],
      xp: member.xp ?? 0,
      guarding: false,
      source: member,
    }));
    this.enemies = enemies;

    this.state = "active";
    this.result = null;
    this.round = 0;
    this._startRound();

    // Enemies faster than the whole party act before anyone gets a command.
    // Without this the queue opens on an enemy, `actor` is null, and the fight
    // deadlocks before it starts.
    this.openingEvents = [];
    this._runUntilPartyTurn(this.openingEvents);
  }

  // --- queries -----------------------------------------------------------

  get combatants() {
    return [...this.party, ...this.enemies];
  }

  living(side) {
    return this.combatants.filter((c) => c.side === side && c.hp > 0);
  }

  get finished() {
    return this.state !== "active";
  }

  /** The party member awaiting a command, or null when nobody is. */
  get actor() {
    if (this.finished) return null;
    const current = this.queue[this.index];
    return current && current.side === PARTY && current.hp > 0 ? current : null;
  }

  snapshot() {
    return {
      state: this.state,
      round: this.round,
      actorId: this.actor?.id ?? null,
      party: this.party.map((c) => ({ ...c, source: undefined })),
      enemies: this.enemies.map((c) => ({ ...c })),
    };
  }

  /** What the current actor can legally do. */
  options() {
    const actor = this.actor;
    if (!actor) return { skills: [], items: [] };
    return {
      skills: actor.skills
        .map((id) => this.skills[id])
        .filter(Boolean)
        .map((skill) => ({ ...skill, usable: (skill.mp ?? 0) <= actor.mp })),
      items: this._usableItems(),
    };
  }

  _usableItems() {
    const stacks = this.sourceInventory.filter((stack) => {
      const item = this.items[stack.item_id];
      return item && item.kind === "consumable" && stack.qty > 0;
    });
    return stacks.map((stack) => ({ ...this.items[stack.item_id], qty: stack.qty }));
  }

  // --- the turn loop -----------------------------------------------------

  _startRound() {
    this.round += 1;
    for (const c of this.combatants) c.guarding = false;
    // Agility order, ties broken by id so the sort is stable across runs.
    this.queue = this.combatants
      .filter((c) => c.hp > 0)
      .sort((a, b) => b.stats.agi - a.stats.agi || (a.id < b.id ? -1 : 1));
    this.index = 0;
  }

  _advance(events) {
    this._step();
    this._runUntilPartyTurn(events);
  }

  _step() {
    this.index += 1;
    if (this.index >= this.queue.length) this._startRound();
  }

  /** Resolve every enemy turn between here and the next living party member. */
  _runUntilPartyTurn(events) {
    for (let guard = 0; guard < 500 && !this.finished; guard += 1) {
      const current = this.queue[this.index];
      if (!current || current.hp <= 0) {
        this._step();
        continue;
      }
      if (current.side === PARTY) return;      // hand control back to the player
      this._enemyTurn(current, events);
      if (this._checkEnd(events)) return;
      this._step();
    }
  }

  /**
   * Take the current party member's action, then run every enemy turn up to
   * the next party member's. Returns everything that happened, in order.
   */
  act(action) {
    const events = [];
    const actor = this.actor;
    if (!actor) return events;

    if (action.type === "flee") {
      const chance = fleeChance(this.living(PARTY), this.living(ENEMY));
      if (this.rng.chance(chance)) {
        this.state = "fled";
        this.result = { outcome: "fled", xp: 0, levelUps: [] };
        events.push({ kind: "flee", ok: true, actorName: actor.name });
        return events;
      }
      events.push({ kind: "flee", ok: false, actorName: actor.name });
      this._advance(events);
      return events;
    }

    this._resolve(actor, action, events);
    if (this._checkEnd(events)) return events;
    this._advance(events);
    return events;
  }

  _resolve(actor, action, events) {
    if (action.type === "attack") {
      const target = this._target(action.targetId, ENEMY);
      if (!target) return;
      events.push({ kind: "action", actorName: actor.name, label: `${actor.name} attacks!` });
      this._damage(actor, target, physicalDamage(actor, target, 1, this.rng), events);
      return;
    }

    if (action.type === "skill") {
      const skill = this.skills[action.skillId];
      if (!skill || (skill.mp ?? 0) > actor.mp) return;
      actor.mp -= skill.mp ?? 0;
      events.push({ kind: "action", actorName: actor.name, label: `${actor.name} uses ${skill.name}!` });

      if (skill.kind === "guard") {
        actor.guarding = true;
        events.push({ kind: "guard", targetName: actor.name });
        return;
      }
      for (const target of this._targetsFor(actor, skill, action.targetId)) {
        if (skill.kind === "heal") {
          this._heal(target, healAmount(actor, skill.power, this.rng), events);
        } else {
          const amount = skill.kind === "magic"
            ? magicDamage(actor, target, skill.power, this.rng)
            : physicalDamage(actor, target, skill.power, this.rng);
          this._damage(actor, target, amount, events);
        }
      }
      return;
    }

    if (action.type === "item") {
      const item = this.items[action.itemId];
      const stack = this.sourceInventory.find((s) => s.item_id === action.itemId);
      if (!item || !stack || stack.qty <= 0) return;
      const target = this._target(action.targetId, PARTY) ?? actor;
      events.push({ kind: "action", actorName: actor.name, label: `${actor.name} uses ${item.name}.` });
      this.spentItems.push(item.id);
      if (item.effect === "heal_hp") this._heal(target, item.power ?? 0, events);
      else if (item.effect === "heal_mp") {
        target.mp = Math.min(target.maxMp, target.mp + (item.power ?? 0));
        events.push({ kind: "mp", targetName: target.name, amount: item.power ?? 0 });
      } else if (item.effect === "revive" && target.hp <= 0) {
        target.hp = Math.max(1, Math.round(target.maxHp * ((item.power ?? 25) / 100)));
        events.push({ kind: "revive", targetName: target.name, hp: target.hp });
      }
    }
  }

  _enemyTurn(enemy, events) {
    const targets = this.living(PARTY);
    if (!targets.length) return;

    const usable = enemy.skills.map((id) => this.skills[id]).filter((s) => s && (s.mp ?? 0) <= enemy.mp);
    const skill = usable.length && this.rng.chance(0.35) ? this.rng.pick(usable) : null;

    if (!skill) {
      const target = this.rng.pick(targets);
      events.push({ kind: "action", actorName: enemy.name, label: `${enemy.name} attacks!` });
      this._damage(enemy, target, physicalDamage(enemy, target, 1, this.rng), events);
      return;
    }

    enemy.mp -= skill.mp ?? 0;
    events.push({ kind: "action", actorName: enemy.name, label: `${enemy.name} uses ${skill.name}!` });
    const hit = skill.target === "all_enemies" ? targets : [this.rng.pick(targets)];
    for (const target of hit) {
      const amount = skill.kind === "magic"
        ? magicDamage(enemy, target, skill.power, this.rng)
        : physicalDamage(enemy, target, skill.power, this.rng);
      this._damage(enemy, target, amount, events);
    }
  }

  // --- effects -----------------------------------------------------------

  _damage(source, target, amount, events) {
    target.hp = Math.max(0, target.hp - amount);
    events.push({
      kind: "damage", targetId: target.id, targetName: target.name,
      side: target.side, amount, hp: target.hp,
    });
    if (target.hp === 0) {
      events.push({ kind: "defeat", targetId: target.id, targetName: target.name, side: target.side });
    }
  }

  _heal(target, amount, events) {
    if (target.hp <= 0) return;
    const before = target.hp;
    target.hp = Math.min(target.maxHp, target.hp + amount);
    events.push({
      kind: "heal", targetId: target.id, targetName: target.name,
      amount: target.hp - before, hp: target.hp,
    });
  }

  _target(id, side) {
    return this.combatants.find((c) => c.id === id && c.hp > 0)
        ?? this.living(side)[0]
        ?? null;
  }

  _targetsFor(actor, skill, targetId) {
    const foes = this.living(actor.side === PARTY ? ENEMY : PARTY);
    const allies = this.living(actor.side);
    switch (skill.target) {
      case "all_enemies": return foes;
      case "all_allies": return allies;
      case "self": return [actor];
      case "one_ally": return [this.combatants.find((c) => c.id === targetId && c.hp > 0) ?? allies[0]].filter(Boolean);
      default: return [this._target(targetId, actor.side === PARTY ? ENEMY : PARTY)].filter(Boolean);
    }
  }

  // --- ending ------------------------------------------------------------

  _checkEnd(events) {
    if (!this.living(ENEMY).length) {
      this.state = "won";
      const xp = this.enemies.reduce((n, e) => n + (e.xp ?? 0), 0);
      const levelUps = this._awardXp(xp, events);
      this.result = { outcome: "won", xp, levelUps };
      events.push({ kind: "victory", xp });
      return true;
    }
    if (!this.living(PARTY).length) {
      this.state = "lost";
      this.result = { outcome: "lost", xp: 0, levelUps: [] };
      events.push({ kind: "lost" });
      return true;
    }
    return false;
  }

  _awardXp(total, events) {
    const levelUps = [];
    for (const member of this.party) {
      if (member.hp <= 0) continue;   // the fallen learn nothing
      member.xp += total;
      while (member.xp >= xpToNext(member.level)) {
        member.xp -= xpToNext(member.level);
        member.level += 1;
        const gains = levelUpGains(member);
        member.maxHp += gains.max_hp;
        member.maxMp += gains.max_mp;
        member.hp = Math.min(member.maxHp, member.hp + gains.max_hp);
        member.mp = Math.min(member.maxMp, member.mp + gains.max_mp);
        member.stats.atk += gains.atk;
        member.stats.def += gains.def;
        member.stats.agi += gains.agi;
        member.stats.mag += gains.mag;
        levelUps.push({ id: member.id, name: member.name, level: member.level, gains });
        events.push({ kind: "levelup", targetName: member.name, level: member.level, gains });
      }
    }
    return levelUps;
  }

  /**
   * Write the outcome back to the ledger. Separate from the fight itself so a
   * test can play a battle without touching world state, and so nothing is
   * persisted until the battle has actually ended.
   */
  commit() {
    if (!this.finished) throw new Error("battle is still running");
    for (const combatant of this.party) {
      const member = combatant.source;
      member.hp = combatant.hp;
      member.mp = combatant.mp;
      member.xp = combatant.xp;
      member.level = combatant.level;
      member.max_hp = combatant.maxHp;
      member.max_mp = combatant.maxMp;
      member.stats = { ...combatant.stats };
    }
    for (const itemId of this.spentItems) {
      const index = this.sourceInventory.findIndex((s) => s.item_id === itemId);
      if (index === -1) continue;
      const stack = this.sourceInventory[index];
      if (stack.qty <= 1) this.sourceInventory.splice(index, 1);
      else stack.qty -= 1;
    }
    this.spentItems = [];
    return this.result;
  }
}
