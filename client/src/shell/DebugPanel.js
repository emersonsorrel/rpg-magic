/**
 * The shell. Plain DOM at M1 -- it owns everything outside the game surface
 * (design doc 6: menus, save/load, settings, debug panel) and talks to Phaser
 * only over the GameBus. Nothing here reaches into a scene.
 */

import { bus, Events } from "../game/GameBus.js";

const MAX_LOG = 40;

export function mountShell(root, world) {
  root.innerHTML = `
    <h1>rpg-magic <span class="tag">M1</span></h1>
    <p class="zone" id="zone-summary">loading…</p>
    <h2>Controls</h2>
    <p class="controls">Arrows / WASD to walk · Space or Enter to talk and to advance text · Up/Down to pick an option</p>
    <h2>Flags</h2>
    <ul id="flags" class="kv"></ul>
    <h2>Inventory</h2>
    <ul id="inventory" class="kv"></ul>
    <h2>Log</h2>
    <ol id="log" class="log"></ol>
  `;

  const summaryEl = root.querySelector("#zone-summary");
  const flagsEl = root.querySelector("#flags");
  const inventoryEl = root.querySelector("#inventory");
  const logEl = root.querySelector("#log");
  const lines = [];

  function renderState() {
    flagsEl.innerHTML = Object.entries(world.flags)
      .map(
        ([flag, value]) =>
          `<li><span>${flag}</span><b class="${value ? "on" : "off"}">${value}</b></li>`
      )
      .join("");
    inventoryEl.innerHTML =
      world.inventory
        .map((stack) => `<li><span>${stack.item_id}</span><b>×${stack.qty}</b></li>`)
        .join("") || `<li class="empty">empty</li>`;
  }

  function log(message) {
    lines.push(message);
    if (lines.length > MAX_LOG) lines.shift();
    logEl.innerHTML = lines.map((line) => `<li>${line}</li>`).join("");
    logEl.scrollTop = logEl.scrollHeight;
  }

  world.subscribe(renderState);
  renderState();

  bus.on(Events.ZONE_LOADED, ({ id, summary, entities }) => {
    summaryEl.textContent = summary;
    log(`zone ${id} loaded — ${entities} entities`);
  });
  bus.on(Events.LOG, (message) => log(message));
  bus.on(Events.DIALOGUE, ({ speaker, text, options }) => {
    const who = speaker ? `${speaker}: ` : "";
    log(options ? `${who}${text} [${options.join(" / ")}]` : `${who}${text}`);
  });
  bus.on(Events.SCRIPT_END, ({ sourceId }) => {
    if (sourceId) log(`— end of ${sourceId} —`);
  });

  return { log };
}
