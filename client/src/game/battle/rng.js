/**
 * Seeded deterministic RNG for combat.
 *
 * Design doc 7: the battle engine is deterministic and has no LLM in it. That
 * matters for testing above all -- a damage roll that varies run to run makes
 * every assertion about a fight a flake.
 */

export function hashSeed(...parts) {
  let h = 0x811c9dc5 >>> 0;
  for (const part of parts) {
    const text = String(part);
    for (let i = 0; i < text.length; i += 1) {
      h ^= text.charCodeAt(i);
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    h = Math.imul(h ^ 0x9e3779b9, 0x85ebca6b) >>> 0;
  }
  return h >>> 0;
}

/** mulberry32: small, fast, and good enough for damage variance. */
export function makeRng(seed) {
  let state = (typeof seed === "number" ? seed : hashSeed(seed)) >>> 0;
  const next = () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  next.int = (maxExclusive) => Math.floor(next() * maxExclusive);
  next.pick = (list) => list[Math.floor(next() * list.length)];
  next.chance = (p) => next() < p;
  return next;
}
