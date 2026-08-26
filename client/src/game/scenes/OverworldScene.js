import * as Phaser from "phaser";

import { EventRunner } from "../EventRunner.js";
import { createHost } from "../WorldState.js";
import { bus, Events } from "../GameBus.js";
import { resolveSprite } from "../assetPack.js";
import { TILE, TILESET_KEY, DIRECTIONS } from "../textures.js";

const STEP_MS = 130;
const FRAME_FOR = { down: 0, left: 1, right: 2, up: 3 };
const DELTA = { down: [0, 1], up: [0, -1], left: [-1, 0], right: [1, 0] };
// Keyed by both KeyboardEvent.code and .key: `code` is the right thing to use
// for physical layout, but it is absent on some synthetic and IME-generated
// events, and a dropped input is worse than an extra table entry.
const KEY_TO_DIR = {
  ArrowLeft: "left", KeyA: "left", a: "left", A: "left",
  ArrowRight: "right", KeyD: "right", d: "right", D: "right",
  ArrowUp: "up", KeyW: "up", w: "up", W: "up",
  ArrowDown: "down", KeyS: "down", s: "down", S: "down",
};

const isConfirm = (event) =>
  event.code === "Space" || event.code === "Enter" || event.key === " " || event.key === "Enter";

/**
 * The game surface: tilemap built programmatically from the Zone Package's
 * layer arrays (not from a Tiled file), a grid-stepped player, collision
 * against the collision layer, and interaction that hands entity scripts to
 * the Event Runner.
 */
export class OverworldScene extends Phaser.Scene {
  constructor() {
    super("OverworldScene");
  }

  create() {
    this.pkg = this.registry.get("zone");
    this.world = this.registry.get("world");
    this.busy = false;
    this.moving = false;
    this.facing = "up";

    this.world.declareFlags(this.pkg.declares_flags);
    this.buildMap();
    this.buildEntities();
    this.buildPlayer();

    this.ui = this.scene.get("UIScene");
    this.runner = new EventRunner(createHost(this.world, this.makeIo()));

    this.input.keyboard.addCapture("UP,DOWN,LEFT,RIGHT,SPACE,ENTER,W,A,S,D");
    this.cursors = this.input.keyboard.createCursorKeys();
    this.wasd = this.input.keyboard.addKeys("W,A,S,D");

    // Held keys are polled in update(); a tap shorter than one frame would be
    // missed by polling alone, so keydown queues a single step as well.
    this.queued = null;
    this.input.keyboard.on("keydown", (event) => {
      if (isConfirm(event)) {
        if (!this.busy && !this.ui.open && !this.moving) this.tryInteract();
        return;
      }
      const direction = KEY_TO_DIR[event.code] ?? KEY_TO_DIR[event.key];
      if (direction) this.queued = direction;
    });

    bus.emit(Events.ZONE_LOADED, {
      id: this.pkg.id,
      summary: this.pkg.summary,
      entities: this.pkg.entities.length,
    });
  }

  // --- construction ------------------------------------------------------

  buildMap() {
    const { width, height, layers } = this.pkg;
    const to2D = (flat, empty = null) => {
      const rows = [];
      for (let y = 0; y < height; y += 1) {
        const row = [];
        for (let x = 0; x < width; x += 1) {
          const value = flat[y * width + x];
          row.push(empty !== null && value === empty ? -1 : value);
        }
        rows.push(row);
      }
      return rows;
    };

    const map = this.make.tilemap({ tileWidth: TILE, tileHeight: TILE, width, height });
    const tileset = map.addTilesetImage(TILESET_KEY, TILESET_KEY, TILE, TILE, 0, 0);

    map.createBlankLayer("ground", tileset, 0, 0).putTilesAt(to2D(layers.ground), 0, 0).setDepth(0);
    // 0 means empty in the decor layer, which is -1 to Phaser.
    map.createBlankLayer("decor", tileset, 0, 0).putTilesAt(to2D(layers.decor, 0), 0, 0).setDepth(1);

    this.collision = layers.collision;
    this.mapWidth = width;
    this.mapHeight = height;
  }

  buildEntities() {
    this.entities = new Map();
    this.blocked = new Set();
    const seed = this.registry.get("seed") ?? 0;

    for (const entity of this.pkg.entities) {
      const { key, fallback } = resolveSprite(entity.sprite_tags, { seed });
      if (fallback) {
        bus.emit(Events.LOG, `no sprite matched ${entity.id} [${(entity.sprite_tags ?? []).join(", ")}] - using generic`);
      }
      const sprite = this.add
        .sprite(entity.x * TILE + TILE / 2, entity.y * TILE + TILE, key, 0)
        .setOrigin(0.5, 1)
        .setDepth(10 + entity.y);

      this.entities.set(entity.id, { def: entity, sprite });

      const blocking = entity.blocking ?? entity.type !== "trigger";
      if (blocking) this.blocked.add(`${entity.x},${entity.y}`);
    }
  }

  buildPlayer() {
    const start = this.world.position;
    this.px = start.x;
    this.py = start.y;
    this.player = this.add
      .sprite(this.px * TILE + TILE / 2, this.py * TILE + TILE, "sprite_player", FRAME_FOR.up)
      .setOrigin(0.5, 1)
      .setDepth(10 + this.py);
  }

  // --- the Event Runner's presentation half ------------------------------

  makeIo() {
    return {
      showText: (payload) => this.ui.showText(payload),
      showChoice: (payload) => this.ui.showChoice(payload),
      playSfx: (sfxTag) => bus.emit(Events.LOG, `sfx: ${sfxTag}`),
      wait: (frames) =>
        new Promise((resolve) => this.time.delayedCall((frames * 1000) / 60, resolve)),
      moveEntity: (entityId, path) => this.moveEntity(entityId, path),
      startBattle: async (encounterId) => {
        await this.ui.showText({
          speaker: null,
          text: `[${encounterId}: battles arrive in M4. Counting this as a win.]`,
        });
        return "win";
      },
      warp: async ({ toZone, toX, toY }) => {
        await this.ui.showText({
          speaker: null,
          text: `[${toZone} has not been authored yet. M2 generates it; the backend will serve it at (${toX},${toY}).]`,
        });
      },
    };
  }

  async moveEntity(entityId, path) {
    const target = this.entities.get(entityId);
    if (!target) return;
    for (const step of path) {
      await new Promise((resolve) => {
        this.tweens.add({
          targets: target.sprite,
          x: step.x * TILE + TILE / 2,
          y: step.y * TILE + TILE,
          duration: STEP_MS,
          onComplete: resolve,
        });
      });
      target.sprite.setDepth(10 + step.y);
    }
  }

  // --- movement ----------------------------------------------------------

  isBlocked(x, y) {
    if (x < 0 || y < 0 || x >= this.mapWidth || y >= this.mapHeight) return true;
    if (this.collision[y * this.mapWidth + x]) return true;
    return this.blocked.has(`${x},${y}`);
  }

  readDirection() {
    if (this.cursors.left.isDown || this.wasd.A.isDown) return "left";
    if (this.cursors.right.isDown || this.wasd.D.isDown) return "right";
    if (this.cursors.up.isDown || this.wasd.W.isDown) return "up";
    if (this.cursors.down.isDown || this.wasd.S.isDown) return "down";
    return null;
  }

  update() {
    if (this.busy || this.ui?.open) {
      // Movement pressed during dialogue is discarded, not buffered -- nobody
      // wants to walk three tiles the instant a text box closes.
      this.queued = null;
      return;
    }
    // A press mid-step is held until the step lands, so tapping a direction
    // repeatedly walks smoothly instead of dropping inputs.
    if (this.moving) return;

    const direction = this.readDirection() ?? this.queued;
    this.queued = null;
    if (!direction) return;

    this.facing = direction;
    this.player.setFrame(FRAME_FOR[direction]);

    const [dx, dy] = DELTA[direction];
    const nx = this.px + dx;
    const ny = this.py + dy;
    if (this.isBlocked(nx, ny)) return;

    this.moving = true;
    this.tweens.add({
      targets: this.player,
      x: nx * TILE + TILE / 2,
      y: ny * TILE + TILE,
      duration: STEP_MS,
      onComplete: () => {
        this.px = nx;
        this.py = ny;
        this.player.setDepth(10 + ny);
        this.world.setPosition(this.pkg.id, nx, ny);
        this.moving = false;
        this.checkWarp();
      },
    });
  }

  checkWarp() {
    const warp = this.pkg.warps.find((w) => w.x === this.px && w.y === this.py);
    if (warp) this.runScript([{ op: "WARP", to_zone: warp.to_zone, to_x: warp.to_x, to_y: warp.to_y }]);
  }

  // --- interaction -------------------------------------------------------

  tryInteract() {
    const [dx, dy] = DELTA[this.facing];
    const tx = this.px + dx;
    const ty = this.py + dy;

    for (const { def } of this.entities.values()) {
      if (def.x !== tx || def.y !== ty) continue;
      if ((def.trigger ?? "interact") !== "interact") continue;
      if (!def.script?.length) continue;
      if (def.once && this.world.isSpent(def.id)) {
        this.runScript([{ op: "SHOW_TEXT", speaker: null, text: "Empty." }]);
        return;
      }
      if (def.once) this.world.markSpent(def.id);
      this.runScript(def.script, def.id);
      return;
    }
  }

  async runScript(script, sourceId = null) {
    if (this.busy) return;
    this.busy = true;
    bus.emit(Events.SCRIPT_START, { sourceId });
    try {
      await this.runner.run(script);
    } catch (error) {
      // A committed package should never do this -- the validator would have
      // caught it. Surface it loudly rather than wedging the scene.
      console.error("script failed:", error);
      bus.emit(Events.LOG, `script error: ${error.message}`);
    } finally {
      bus.emit(Events.SCRIPT_END, { sourceId });
      // Swallow the keypress that closed the last box so it cannot immediately
      // re-trigger the same entity.
      this.time.delayedCall(120, () => {
        this.busy = false;
      });
    }
  }
}

export { DIRECTIONS };
