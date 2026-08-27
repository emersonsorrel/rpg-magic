/**
 * Every number the battle system cares about, in one file.
 *
 * Design doc 7: "Damage formula configurable in one place; start simple
 * (atk² / (atk + def) style) and tune." This is that place. Nothing else in the
 * battle code should contain a magic constant.
 */

export const GUARD_MULTIPLIER = 2.0;   // effective defence while guarding
export const VARIANCE = 0.12;          // ±12% damage roll
export const FLEE_BASE = 0.45;

/** atk² / (atk + def): grows fast enough that levelling feels real, and never
 *  collapses to zero against a heavy defender. */
function exchange(attack, defence) {
  const a = Math.max(1, attack);
  const d = Math.max(1, defence);
  return Math.max(1, Math.round((a * a) / (a + d)));
}

function roll(rng) {
  return 1 + (rng() * 2 - 1) * VARIANCE;
}

export function physicalDamage(attacker, defender, power = 1, rng = Math.random) {
  const defence = defender.stats.def * (defender.guarding ? GUARD_MULTIPLIER : 1);
  return Math.max(1, Math.round(exchange(attacker.stats.atk * power, defence) * roll(rng)));
}

export function magicDamage(attacker, defender, power = 1, rng = Math.random) {
  // Magic reads defence at half weight, so a heavily armoured enemy is still
  // worth spending MP on.
  const defence = (defender.stats.def * 0.5) * (defender.guarding ? GUARD_MULTIPLIER : 1);
  return Math.max(1, Math.round(exchange(attacker.stats.mag * power, defence) * roll(rng)));
}

export function healAmount(healer, power, rng = Math.random) {
  return Math.max(1, Math.round((power + healer.stats.mag * 0.6) * roll(rng)));
}

export function fleeChance(party, enemies) {
  const ours = party.reduce((n, c) => n + c.stats.agi, 0) / Math.max(1, party.length);
  const theirs = enemies.reduce((n, c) => n + c.stats.agi, 0) / Math.max(1, enemies.length);
  return Math.min(0.95, Math.max(0.1, FLEE_BASE * (ours / Math.max(1, theirs))));
}

/** XP needed to go from `level` to the next one. Relative, not cumulative, so a
 *  party can start at any level without a back-dated xp total. */
export function xpToNext(level) {
  return Math.round(18 * Math.pow(level, 1.4));
}

/** Enemy templates are level-1 baselines; encounters scale them. */
export function scaleTemplate(template, level) {
  const f = 1 + (level - 1) * 0.18;
  const at = (n) => Math.max(1, Math.round((n ?? 1) * f));
  return {
    hp: at(template.hp),
    stats: {
      atk: at(template.atk),
      def: at(template.def),
      agi: at(template.agi),
      mag: at(template.mag ?? 1),
    },
    xp: at(template.xp),
  };
}

/** What a level-up gives. Deliberately flat and readable rather than clever. */
export function levelUpGains(member) {
  const magish = member.stats.mag >= member.stats.atk;
  return {
    max_hp: magish ? 4 : 7,
    max_mp: magish ? 4 : 1,
    atk: magish ? 1 : 2,
    def: 1,
    agi: 1,
    mag: magish ? 2 : 1,
  };
}
