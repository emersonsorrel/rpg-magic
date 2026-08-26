/**
 * Tag-based asset resolution (design doc 3.4).
 *
 * Assets are addressed by tags, never by filename, so the default pack, a user
 * pack and generated art are interchangeable. Resolution scores candidates by
 * tag overlap and breaks ties with the world seed, so the same seed always
 * picks the same sprite.
 *
 * The hard rule: if nothing scores above the floor, fall back to a
 * guaranteed-present generic sprite. A missing asset must never block a commit,
 * and it must never crash a scene either.
 *
 * At M1 the "pack" is procedurally drawn placeholder art (see textures.js).
 * Swapping in real PNGs later changes this table, not the resolution logic.
 */

export const PLACEHOLDER_PACK = {
  pack_id: "placeholder_16bit",
  fallback: "sprite_generic",
  sprites: [
    { key: "sprite_elder", tags: ["human", "elder", "authority", "biome:temperate"] },
    { key: "sprite_smith", tags: ["human", "adult", "smith", "biome:temperate"] },
    { key: "sprite_villager", tags: ["human", "adult", "farmer", "biome:temperate"] },
    { key: "sprite_chest", tags: ["chest", "wooden"] },
    { key: "sprite_sign", tags: ["signpost", "prop", "wooden"] },
    { key: "sprite_generic", tags: ["human"] },
  ],
};

/** Cheap deterministic hash. Only needs to be stable, not good. */
function hash(seed, key) {
  let h = (seed >>> 0) ^ 0x9e3779b9;
  for (let i = 0; i < key.length; i += 1) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

/**
 * @param {string[]} tags       the entity's sprite_tags
 * @param {object}   options    { pack, seed, floor }
 * @returns {{ key: string, score: number, fallback: boolean }}
 */
export function resolveSprite(tags = [], { pack = PLACEHOLDER_PACK, seed = 0, floor = 1 } = {}) {
  const wanted = new Set(tags);
  let best = null;

  for (const candidate of pack.sprites) {
    const score = candidate.tags.reduce((n, tag) => n + (wanted.has(tag) ? 1 : 0), 0);
    if (score < floor) continue;
    if (
      best === null ||
      score > best.score ||
      // Deterministic tie-break on the world seed, so a re-run of the same seed
      // dresses the town identically.
      (score === best.score && hash(seed, candidate.key) < hash(seed, best.key))
    ) {
      best = { key: candidate.key, score };
    }
  }

  if (best === null) return { key: pack.fallback, score: 0, fallback: true };
  return { ...best, fallback: false };
}
