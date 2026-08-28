/**
 * The shell. Plain DOM at M1/M2 -- it owns everything outside the game surface
 * (design doc 6: menus, save/load, settings, debug panel) and talks to Phaser
 * only over the GameBus. Nothing here reaches into a scene.
 */

import { bus, Events } from "../game/GameBus.js";

const MAX_LOG = 60;

export function mountShell(root, world, { seed, onNewWorld, api, zoneCache } = {}) {
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

    <h2>Prefetch</h2>
    <label class="toggle">
      <input id="prefetch" type="checkbox" checked />
      <span>Build ahead of the player</span>
    </label>
    <p class="controls" id="prefetch-stats">Buildings in this town start building the moment you arrive, nearest door first. Guessing which way you will leave waits until you stand still, and is capped at two.</p>

    <h2>Authoring</h2>
    <p id="authoring" class="zone">checking…</p>

    <h2>Saves</h2>
    <div class="seedbar">
      <input id="save-name" type="text" placeholder="name this save" maxlength="40" />
      <button id="save-btn" type="button">Save</button>
    </div>
    <ul id="saves" class="saves"></ul>

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

  const savesEl = root.querySelector("#saves");
  let currentZoneId = world.position?.zone ?? null;
  const authoringEl = root.querySelector("#authoring");

  async function refreshAuthoring() {
    if (!api) return;
    try {
      const { authoring } = await api.getStatus();
      if (!authoring.enabled) {
        authoringEl.innerHTML =
          `<b class="off">off</b> — ${authoring.reason}. Zones commit placeholder content.`;
        return;
      }
      const role = authoring.roles.zone_author ?? Object.values(authoring.roles)[0] ?? {};
      const where = role.base_url ? ` @ ${role.base_url.replace(/^https?:\/\//, "")}` : "";
      authoringEl.innerHTML = `<b class="on">on</b> — ${role.provider}: ${role.model}${where}`;
    } catch (error) {
      authoringEl.textContent = `could not read status: ${error.message}`;
    }
  }

  async function refreshSaves() {
    if (!api) return;
    try {
      const slots = (await api.listSaves()).filter((slot) => !slot.active);
      savesEl.innerHTML = slots.length
        ? slots.map((slot) => `
            <li>
              <span title="${slot.premise ?? ""}">${slot.name}
                <b class="dim">${slot.party.map((m) => `${m.name} L${m.level}`).join(", ")}</b>
              </span>
              <button type="button" data-load="${encodeURIComponent(slot.name)}">Load</button>
            </li>`).join("")
        : `<li class="empty">no saves yet</li>`;
      for (const button of savesEl.querySelectorAll("[data-load]")) {
        button.addEventListener("click", async () => {
          await api.loadSlot(decodeURIComponent(button.dataset.load));
          window.location.reload();
        });
      }
    } catch (error) {
      log(`could not list saves: ${error.message}`);
    }
  }

  const prefetchBox = root.querySelector("#prefetch");
  const prefetchStats = root.querySelector("#prefetch-stats");
  if (zoneCache) {
    prefetchBox.checked = zoneCache.enabled;
    prefetchBox.addEventListener("change", () => {
      zoneCache.setEnabled(prefetchBox.checked);
      log(prefetchBox.checked ? "prefetching on" : "prefetching off");
    });
    setInterval(() => {
      const { hits, misses, prefetched } = zoneCache.stats;
      // How much of the place you are standing in is actually ready. This is
      // the number that matters: "5 of 7 buildings ready" answers the question
      // "why did that door make me wait" before it gets asked.
      const zone = world.zones?.[currentZoneId];
      const doors = zone?.interiors ?? [];
      const ready = doors.filter(
        (id) => zoneCache.has(id) || world.zones?.[id]?.committed
      ).length;
      const buildings = doors.length
        ? `${ready}/${doors.length} buildings ready · `
        : "";
      prefetchStats.textContent =
        `${buildings}${prefetched} warmed · ${hits} instant · ${misses} waited for.`;
    }, 1000);
  } else {
    prefetchBox.disabled = true;
  }

  root.querySelector("#save-btn").addEventListener("click", async () => {
    const field = root.querySelector("#save-name");
    const name = field.value.trim();
    if (!name || !api) return;
    try {
      await api.saveSlot(name);
      field.value = "";
      log(`saved as "${name}"`);
      refreshSaves();
    } catch (error) {
      log(`save failed: ${error.message}`);
    }
  });

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
  refreshSaves();
  refreshAuthoring();

  bus.on(Events.ZONE_LOADED, ({ id, kind, summary, entities, size, authored }) => {
    currentZoneId = id;
    const verdict = authored
      ? ` · <b class="${authored === "placeholder" ? "off" : "on"}">${authored}</b>`
      : "";
    zoneLine.innerHTML =
      `<b class="on">${id}</b> — ${kind}, ${size[0]}×${size[1]}, ${entities} entities${verdict}`;
    summaryEl.textContent = summary;
    log(`entered ${id}${authored ? ` (${authored})` : ""}`);
  });
  bus.on(Events.LOG, (message) => log(message));
  bus.on(Events.DIALOGUE, ({ speaker, text, options }) => {
    const who = speaker ? `${speaker}: ` : "";
    log(options ? `${who}${text} [${options.join(" / ")}]` : `${who}${text}`);
  });

  return { log };
}
