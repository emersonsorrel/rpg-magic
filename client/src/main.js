/**
 * Entry point. Asks the authoring backend for the world and the zone the player
 * is standing in, gates both through the shared schemas, then starts Phaser.
 *
 * M1 read two fixture files from disk. That is the only thing that changed at
 * M2 — everything downstream of the Zone Package is untouched, which was the
 * point of making the package the boundary.
 */

import * as Phaser from "phaser";

import * as api from "./api.js";
import { BattleScene } from "./game/scenes/BattleScene.js";
import { BootScene } from "./game/scenes/BootScene.js";
import { OverworldScene } from "./game/scenes/OverworldScene.js";
import { UIScene } from "./game/scenes/UIScene.js";
import { WorldState } from "./game/WorldState.js";
import { ZoneCache } from "./game/ZoneCache.js";
import { mountShell } from "./shell/DebugPanel.js";
import { bus, Events } from "./game/GameBus.js";

/**
 * Whatever went wrong, the player gets a way out.
 *
 * A world that fails to load used to end at a schema error with no controls on
 * screen at all — the shell mounts after the world loads, so its New World
 * button was never there when it was most needed. A bad roll must never be a
 * dead end.
 */
function showRecovery(error, { seed } = {}) {
  const detail = error?.detail ?? error?.message ?? String(error);
  const suggested = seed ?? Math.floor(Math.random() * 4294967295);

  document.getElementById("game").innerHTML = `
    <div class="fatal">
      <h2>${error?.headline ?? "This world could not be loaded"}</h2>
      <p class="recover-lead">${error?.lead ?? "Rolling a new one replaces it. Nothing else is affected."}</p>
      <div class="recover-actions">
        <input id="recover-seed" type="number" value="${suggested}" />
        <button id="recover-new" type="button">Roll a new world</button>
        <button id="recover-retry" type="button" class="secondary">Try again</button>
      </div>
      <p id="recover-status" class="recover-status"></p>
      <details><summary>What went wrong</summary><pre>${detail}</pre></details>
    </div>`;

  const status = document.getElementById("recover-status");
  const buttons = [...document.querySelectorAll(".recover-actions button")];

  document.getElementById("recover-retry").addEventListener("click", () => window.location.reload());
  document.getElementById("recover-new").addEventListener("click", async () => {
    const value = Number(document.getElementById("recover-seed").value);
    buttons.forEach((b) => { b.disabled = true; });
    status.textContent = "Rolling… authoring the opening town can take a minute.";
    try {
      await api.newGame(Number.isFinite(value) ? value : suggested);
      window.location.reload();
    } catch (failure) {
      // Even the reroll can fail. Say so and leave the buttons usable.
      buttons.forEach((b) => { b.disabled = false; });
      status.textContent = `That roll failed too: ${failure.message}. Try another seed.`;
    }
  });
}

async function boot() {
  let ledger;
  let zone;
  let registries;
  try {
    await api.ready();
    ledger = await api.getWorld();
    [zone, registries] = await Promise.all([
      api.getZone(ledger.player_position.zone),
      api.getRegistries(),
    ]);
  } catch (error) {
    console.error(error);
    showRecovery(error, { seed: ledger?.seed });
    return;
  }

  const world = new WorldState(ledger);

  // Shared across scene restarts, so walking back into a zone is instant and a
  // prefetch started before a transition is still useful after it.
  const zoneCache = new ZoneCache({
    fetchZone: (zoneId) => api.getZone(zoneId),
    maxPending: 2,
    onEvent: (event) => {
      if (event.kind === "prefetched") {
        bus.emit(Events.LOG, `prefetched ${event.zoneId} (${event.ms}ms)`);
      } else {
        bus.emit(Events.LOG, `prefetch of ${event.zoneId} failed: ${event.message}`);
      }
    },
  });
  zoneCache.put(zone);
  mountShell(document.getElementById("shell"), world, {
    api,
    seed: ledger.seed,
    zoneCache,
    onNewWorld: async (seed) => {
      await api.newGame(seed);
      window.location.reload();
    },
  });
  bus.emit(Events.LOG, `world seed ${ledger.seed} · ledger schema v${ledger.schema_version}`);

  const game = new Phaser.Game({
    type: Phaser.AUTO,
    parent: "game",
    width: 320,
    height: 240,
    pixelArt: true,
    roundPixels: true,
    backgroundColor: "#0b0d12",
    scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH },
    scene: [BootScene, OverworldScene, BattleScene, UIScene],
    callbacks: {
      // Guaranteed to run before any scene's create(), unlike setting the
      // registry after the constructor returns.
      preBoot: (g) => {
        g.registry.set("zone", zone);
        g.registry.set("world", world);
        g.registry.set("seed", ledger.seed);
        g.registry.set("registries", registries);
        g.registry.set("zoneCache", zoneCache);
      },
    },
  });

  // Debug handle for the console and for automated checks.
  window.__rpg = { game, world, zone, ledger, api, zoneCache };
}

boot();
