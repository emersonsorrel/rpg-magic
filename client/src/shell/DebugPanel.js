/**
 * The shell. Plain DOM at M1/M2 -- it owns everything outside the game surface
 * (design doc 6: menus, save/load, settings, debug panel) and talks to Phaser
 * only over the GameBus. Nothing here reaches into a scene.
 */

import { bus, Events } from "../game/GameBus.js";

const MAX_LOG = 60;

export function mountShell(root, world, { seed, onNewWorld } = {}) {
  root.innerHTML = `
    <h1>rpg-magic <span class="tag">M2</span></h1>
    <p class="zone" id="zone-line">loading…</p>
    <p class="zone" id="zone-summary"></p>

    <h2>World</h2>
    <div class="seedbar">
      <input id="seed" type="number" value="${seed ?? 0}" />
      <button id="regen" type="button">New world</button>
    </div>
    <p class="controls">Same seed, same world — regenerating with the seed above rebuilds it tile for tile.</p>

    <h2>Controls</h2>
    <p class="controls">Arrows / WASD to walk · Space or Enter to talk and advance · Up/Down to pick an option</p>

    <h2>Flags</h2>
    <ul id="flags" class="kv"></ul>
    <h2>Inventory</h2>
    <ul id="inventory" class="kv"></ul>
    <h2>Log</h2>
    <ol id="log" class="log"></ol>
  `;

  const zoneLine = root.querySelector("#zone-line");
  const summaryEl = root.querySelector("#zone-summary");
  const flagsEl = root.querySelector("#flags");
  const inventoryEl = root.querySelector("#inventory");
  const logEl = root.querySelector("#log");
  const lines = [];

  root.querySelector("#regen").addEventListener("click", () => {
    const value = Number(root.querySelector("#seed").value);
    if (Number.isFinite(value) && onNewWorld) onNewWorld(value);
  });

  function renderState() {
    flagsEl.innerHTML =
      Object.entries(world.flags)
        .map(([flag, v]) => `<li><span>${flag}</span><b class="${v ? "on" : "off"}">${v}</b></li>`)
        .join("") || `<li class="empty">none yet</li>`;
    inventoryEl.innerHTML =
      world.inventory.map((s) => `<li><span>${s.item_id}</span><b>×${s.qty}</b></li>`).join("") ||
      `<li class="empty">empty</li>`;
  }

  function log(message) {
    lines.push(message);
    if (lines.length > MAX_LOG) lines.shift();
    logEl.innerHTML = lines.map((line) => `<li>${line}</li>`).join("");
    logEl.scrollTop = logEl.scrollHeight;
  }

  world.subscribe(renderState);
  renderState();

  bus.on(Events.ZONE_LOADED, ({ id, kind, summary, entities, size }) => {
    zoneLine.innerHTML = `<b class="on">${id}</b> — ${kind}, ${size[0]}×${size[1]}, ${entities} entities`;
    summaryEl.textContent = summary;
    log(`entered ${id}`);
  });
  bus.on(Events.LOG, (message) => log(message));
  bus.on(Events.DIALOGUE, ({ speaker, text, options }) => {
    const who = speaker ? `${speaker}: ` : "";
    log(options ? `${who}${text} [${options.join(" / ")}]` : `${who}${text}`);
  });

  return { log };
}
