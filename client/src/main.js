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
import { BootScene } from "./game/scenes/BootScene.js";
import { OverworldScene } from "./game/scenes/OverworldScene.js";
import { UIScene } from "./game/scenes/UIScene.js";
import { WorldState } from "./game/WorldState.js";
import { mountShell } from "./shell/DebugPanel.js";
import { bus, Events } from "./game/GameBus.js";

function fatal(message, detail) {
  document.getElementById("game").innerHTML =
    `<div class="fatal"><h2>${message}</h2><pre>${detail ?? ""}</pre></div>`;
}

async function boot() {
  let ledger;
  let zone;
  try {
    const schemaHash = await api.ready();
    ledger = await api.getWorld();
    zone = await api.getZone(ledger.player_position.zone);
  } catch (error) {
    console.error(error);
    fatal("Could not start", error.message);
    return;
  }

  const world = new WorldState(ledger);
  mountShell(document.getElementById("shell"), world, {
    seed: ledger.seed,
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
    scene: [BootScene, OverworldScene, UIScene],
    callbacks: {
      // Guaranteed to run before any scene's create(), unlike setting the
      // registry after the constructor returns.
      preBoot: (g) => {
        g.registry.set("zone", zone);
        g.registry.set("world", world);
        g.registry.set("seed", ledger.seed);
      },
    },
  });

  // Debug handle for the console and for automated checks.
  window.__rpg = { game, world, zone, ledger, api };
}

boot();
