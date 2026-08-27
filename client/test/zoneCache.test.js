/**
 * Prefetch policy (design doc 6, open question 3).
 *
 * The mechanism is easy; the policy is what needs pinning down, because a
 * careless one speculatively authors seven building interiors nobody enters and
 * bills the user for all of them.
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { ZoneCache, neighboursOf } from "../src/game/ZoneCache.js";

function stubFetcher({ delay = 0, fail = [] } = {}) {
  const calls = [];
  const fetchZone = async (id) => {
    calls.push(id);
    if (delay) await new Promise((r) => setTimeout(r, delay));
    if (fail.includes(id)) throw new Error(`boom: ${id}`);
    return { id, width: 8, height: 8 };
  };
  return { fetchZone, calls };
}

const ledger = {
  zones: {
    zone_town_01: { id: "zone_town_01", kind: "town", committed: true },
    zone_mine_b1: { id: "zone_mine_b1", kind: "dungeon", committed: false },
    zone_mine_b2: { id: "zone_mine_b2", kind: "dungeon", committed: true },
    zone_town_01_in01: { id: "zone_town_01_in01", kind: "interior", committed: false },
    zone_town_01_in02: { id: "zone_town_01_in02", kind: "interior", committed: true },
  },
};

const townPackage = {
  id: "zone_town_01",
  warps: [
    { to_zone: "zone_town_01_in01" },
    { to_zone: "zone_mine_b1" },
    { to_zone: "zone_town_01_in02" },
    { to_zone: "zone_mine_b2" },
  ],
};

describe("neighbour priority", () => {
  it("puts the spine ahead of front doors", () => {
    const order = neighboursOf(townPackage, ledger).map((n) => n.id);
    assert.deepEqual(order.slice(0, 2).sort(), ["zone_mine_b1", "zone_mine_b2"]);
    assert.deepEqual(order.slice(2).sort(), ["zone_town_01_in01", "zone_town_01_in02"]);
  });

  it("puts already-built zones first within a group, since they are free", () => {
    const order = neighboursOf(townPackage, ledger);
    assert.equal(order[0].id, "zone_mine_b2");
    assert.equal(order[0].committed, true);
  });

  it("does not repeat a zone reachable through two warps", () => {
    const twoDoors = { id: "z", warps: [{ to_zone: "zone_mine_b1" }, { to_zone: "zone_mine_b1" }] };
    assert.equal(neighboursOf(twoDoors, ledger).length, 1);
  });
});

describe("caching", () => {
  it("serves a second request from memory", async () => {
    const { fetchZone, calls } = stubFetcher();
    const cache = new ZoneCache({ fetchZone });
    await cache.load("a");
    await cache.load("a");
    assert.deepEqual(calls, ["a"]);
    assert.equal(cache.stats.hits, 1);
    assert.equal(cache.stats.misses, 1);
  });

  it("shares an in-flight request instead of starting a second", async () => {
    const { fetchZone, calls } = stubFetcher({ delay: 20 });
    const cache = new ZoneCache({ fetchZone });
    const [first, second] = await Promise.all([cache.load("a"), cache.load("a")]);
    assert.equal(calls.length, 1);
    assert.equal(first, second);
  });

  it("walking into a zone the prefetcher is building just waits for it", async () => {
    const { fetchZone, calls } = stubFetcher({ delay: 20 });
    const cache = new ZoneCache({ fetchZone });
    cache.schedule([{ id: "a", committed: false }]);
    const draining = cache.drain();
    const pkg = await cache.load("a");        // player arrives mid-prefetch
    await draining;
    assert.equal(calls.length, 1, "the zone must not be built twice");
    assert.equal(pkg.id, "a");
  });
});

describe("rationing paid work", () => {
  it("speculates on at most maxPending uncommitted zones", async () => {
    const { fetchZone, calls } = stubFetcher();
    const cache = new ZoneCache({ fetchZone, maxPending: 2 });
    cache.schedule([
      { id: "u1", committed: false },
      { id: "u2", committed: false },
      { id: "u3", committed: false },
      { id: "u4", committed: false },
    ]);
    await cache.drain();
    assert.deepEqual(calls, ["u1", "u2"]);
  });

  it("does not ration zones that already exist", async () => {
    const { fetchZone, calls } = stubFetcher();
    const cache = new ZoneCache({ fetchZone, maxPending: 1 });
    cache.schedule([
      { id: "c1", committed: true },
      { id: "c2", committed: true },
      { id: "c3", committed: true },
      { id: "u1", committed: false },
    ]);
    await cache.drain();
    assert.deepEqual(calls.sort(), ["c1", "c2", "c3", "u1"]);
  });

  it("keeps its budget spent across separate schedules", async () => {
    const { fetchZone, calls } = stubFetcher();
    const cache = new ZoneCache({ fetchZone, maxPending: 1 });
    cache.schedule([{ id: "u1", committed: false }]);
    await cache.drain();
    cache.schedule([{ id: "u2", committed: false }]);
    await cache.drain();
    assert.deepEqual(calls, ["u1"], "the budget is a total, not a per-call allowance");
  });
});

describe("failure and control", () => {
  it("a failed prefetch is reported but not thrown", async () => {
    const events = [];
    const { fetchZone } = stubFetcher({ fail: ["bad"] });
    const cache = new ZoneCache({ fetchZone, onEvent: (e) => events.push(e) });
    cache.schedule([{ id: "bad", committed: true }]);
    await cache.drain();
    assert.equal(events[0].kind, "prefetch_failed");
    assert.equal(cache.has("bad"), false);
  });

  it("a zone that failed to prefetch still loads normally afterwards", async () => {
    let attempt = 0;
    const cache = new ZoneCache({
      fetchZone: async (id) => {
        attempt += 1;
        if (attempt === 1) throw new Error("transient");
        return { id };
      },
    });
    cache.schedule([{ id: "z", committed: true }]);
    await cache.drain();
    assert.equal((await cache.load("z")).id, "z");
  });

  it("turning it off clears the queue and stops spending", async () => {
    const { fetchZone, calls } = stubFetcher();
    const cache = new ZoneCache({ fetchZone });
    cache.schedule([{ id: "u1", committed: false }]);
    cache.setEnabled(false);
    await cache.drain();
    assert.deepEqual(calls, []);
  });

  it("turning it off keeps what was already cached", async () => {
    const { fetchZone } = stubFetcher();
    const cache = new ZoneCache({ fetchZone });
    await cache.load("a");
    cache.setEnabled(false);
    assert.equal(cache.has("a"), true);
    assert.equal((await cache.load("a")).id, "a");
  });
});
