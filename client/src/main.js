/**
 * Entry point. Loads the canned Zone Package and ledger, gates them through the
 * generated schema validators, then starts Phaser.
 *
 * M1 has no backend: the fixture is fetched straight off disk. From M2 this is
 * the one place that changes -- api.js asks the authoring service for the zone
 * instead, and everything downstream is untouched.
 */

import * as Phaser from "phaser";

import { BootScene } from "./game/scenes/BootScene.js";
import { OverworldScene } from "./game/scenes/OverworldScene.js";
import { UIScene } from "./game/scenes/UIScene.js";
import { WorldState } from "./game/WorldState.js";
import { loadLedger, loadZonePackage } from "./game/zoneLoader.js";
import { mountShell } from "./shell/DebugPanel.js";
import { bus, Events } from "./game/GameBus.js";

const LEDGER_URL = "/fixtures/ledger_new_game.json";
const ZONE_URL = "/fixtures/zone_town_01.json";

function fatal(message, detail) {
  document.getElementById("game").innerHTML =
    `<div class="fatal"><h2>${message}</h2><pre>${detail ?? ""}</pre></div>`;
}

async function boot() {
  let ledger;
  let zone;
  try {
    [ledger, zone] = await Promise.all([loadLedger(LEDGER_URL), loadZonePackage(ZONE_URL)]);
  } catch (error) {
    console.error(error);
    fatal("Refused to load", error.message);
    return;
  }

  const world = new WorldState(ledger);
  mountShell(document.getElementById("shell"), world);
  bus.emit(Events.LOG, `ledger seed ${ledger.seed} · schema v${ledger.schema_version}`);

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
      preBoot: (game) => {
        game.registry.set("zone", zone);
        game.registry.set("world", world);
        game.registry.set("seed", ledger.seed);
      },
    },
  });

  // Debug handle for the console and for automated checks. Read-only in spirit.
  window.__rpg = { game, world, zone, ledger };
}

boot();
