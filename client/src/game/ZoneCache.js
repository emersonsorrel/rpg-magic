/**
 * Zone cache and background prefetcher (design doc 6, open question 3).
 *
 *   "Prefetch adjacent zones in the background once the player is idle to hide
 *   latency."
 *
 * Open question 3 set the bar: if authoring a zone exceeds ~4 seconds,
 * prefetching stops being an optimisation and becomes mandatory. Authoring
 * against a hosted model takes considerably longer than that, so this is the
 * difference between a transition and a wait.
 *
 * Framework-free on purpose — it takes a `fetchZone` function and knows nothing
 * about Phaser, so the queue policy is testable headlessly.
 *
 * The policy matters as much as the mechanism: a zone that has never been
 * committed costs a model call to prefetch, so uncommitted neighbours are
 * strictly rationed while already-committed ones are free to warm.
 */

export class ZoneCache {
  /**
   * @param fetchZone   async (zoneId) => package
   * @param maxPending  how many uncommitted (i.e. paid) zones to speculate on
   * @param onEvent     optional reporter for logging
   */
  constructor({ fetchZone, maxPending = 2, onEvent = () => {} }) {
    this.fetchZone = fetchZone;
    this.maxPending = maxPending;
    this.onEvent = onEvent;

    this.packages = new Map();
    this.inFlight = new Map();
    this.queue = [];
    this.speculated = new Set();   // uncommitted zones we have paid to build
    this.running = false;
    this.enabled = true;
    this.stats = { hits: 0, misses: 0, prefetched: 0 };
  }

  has(zoneId) {
    return this.packages.has(zoneId);
  }

  put(pkg) {
    this.packages.set(pkg.id, pkg);
  }

  /** Cache-first fetch. Shares an in-flight request rather than duplicating it,
   *  so walking into a zone the prefetcher is already building just waits. */
  async load(zoneId) {
    if (this.packages.has(zoneId)) {
      this.stats.hits += 1;
      return this.packages.get(zoneId);
    }
    if (this.inFlight.has(zoneId)) {
      this.stats.hits += 1;
      return this.inFlight.get(zoneId);
    }
    this.stats.misses += 1;
    return this.#start(zoneId);
  }

  #start(zoneId) {
    const request = Promise.resolve(this.fetchZone(zoneId))
      .then((pkg) => {
        this.packages.set(zoneId, pkg);
        return pkg;
      })
      .finally(() => this.inFlight.delete(zoneId));
    this.inFlight.set(zoneId, request);
    return request;
  }

  /**
   * Schedule neighbours for background loading.
   *
   * @param neighbours [{ id, committed }] in priority order
   */
  schedule(neighbours) {
    if (!this.enabled) return;
    let budget = this.maxPending - this.speculated.size;
    for (const { id, committed, speculative = !committed } of neighbours) {
      if (this.packages.has(id) || this.inFlight.has(id) || this.queue.includes(id)) continue;
      if (!committed && speculative) {
        // Guessing which way the player will leave costs a model call. Ration it.
        if (budget <= 0) continue;
        budget -= 1;
        this.speculated.add(id);
      }
      this.queue.push(id);
    }
  }

  /** Work the queue one zone at a time. Serial on purpose: the backend
   *  serialises generation anyway, and a burst would only queue behind itself
   *  while making the wallet look busy. */
  async drain() {
    if (this.running) return;
    this.running = true;
    try {
      while (this.enabled && this.queue.length) {
        const zoneId = this.queue.shift();
        if (this.packages.has(zoneId) || this.inFlight.has(zoneId)) continue;
        const started = Date.now();
        try {
          await this.#start(zoneId);
          this.stats.prefetched += 1;
          this.onEvent({ kind: "prefetched", zoneId, ms: Date.now() - started });
        } catch (error) {
          // A failed prefetch is a non-event: the player may never go there, and
          // if they do, the ordinary load will surface the error properly.
          this.onEvent({ kind: "prefetch_failed", zoneId, message: error.message });
        }
      }
    } finally {
      this.running = false;
    }
  }

  /** Stop speculating; anything already cached stays cached. */
  setEnabled(enabled) {
    this.enabled = enabled;
    if (!enabled) this.queue.length = 0;
  }
}

/**
 * Which zones to warm from where the player is standing, best first.
 *
 * The spine goes first — a road out is one door among many and the likeliest
 * exit — but every interior follows, unrationed.
 *
 * That rationing was wrong for interiors. Guessing which way someone will leave
 * a town is speculation worth limiting; a town's own front doors are not. A
 * player let loose in a town will try the buildings, and having five of seven
 * stall on a live model call is the difference between a game and a wait. They
 * are also small: a room with two slots, not a dungeon floor.
 *
 * Interiors are ordered by how close their door is to the player, so the one
 * they are walking towards is built first.
 */
export function neighboursOf(pkg, ledger, from = null) {
  const zones = ledger?.zones ?? {};
  const seen = new Set();
  const spine = [];
  const interiors = [];

  for (const warp of pkg.warps ?? []) {
    const id = warp.to_zone;
    if (seen.has(id)) continue;
    seen.add(id);
    const zone = zones[id];
    const committed = Boolean(zone?.committed);
    if (zone?.kind === "interior") {
      const distance = from
        ? Math.abs(warp.x - from.x) + Math.abs(warp.y - from.y)
        : 0;
      interiors.push({ id, committed, speculative: false, distance });
    } else {
      spine.push({ id, committed, speculative: !committed });
    }
  }

  // Already-built zones first within each group: they are a free round trip.
  const byCost = (a, b) => Number(b.committed) - Number(a.committed);
  interiors.sort((a, b) => byCost(a, b) || a.distance - b.distance);
  return [...spine.sort(byCost), ...interiors];
}
