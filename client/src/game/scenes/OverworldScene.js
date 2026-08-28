import * as Phaser from "phaser";

import * as api from "../../api.js";
import { EventRunner } from "../EventRunner.js";
import { createHost } from "../WorldState.js";
import { bus, Events } from "../GameBus.js";
import { resolveSprite } from "../assetPack.js";
import { Battle, buildEncounter } from "../battle/engine.js";
import { hashSeed, makeRng } from "../battle/rng.js";
import { neighboursOf } from "../ZoneCache.js";
import { TILE, tilesetKey } from "../textures.js";

const STEP_MS = 130;
// How long the player has to stand still before we start speculating on
// neighbours. Long enough that crossing a room does not trigger it.
const IDLE_BEFORE_PREFETCH = 2000;
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
 *
 * Stepping onto a warp asks the backend for the target zone. Whether that zone
 * already existed or was generated on the spot is not this scene's business.
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
    this.queued = null;
    this.pendingWarp = null;
    this.facing = "up";

    this.world.declareFlags(this.pkg.declares_flags);
    this.registries = this.registry.get("registries") ?? { encounters: {}, templates: {}, skills: {}, items: {} };
    this.cache = this.registry.get("zoneCache") ?? null;
    this.cache?.put(this.pkg);
    this.idleSince = 0;
    this.prefetchArmed = false;
    this.battleCount = 0;
    this._armEncounters();
    this.buildMap();
    this.buildEntities();
    this.buildPlayer();
    this.buildCamera();

    this.ui = this.scene.get("UIScene");
    this.runner = new EventRunner(createHost(this.world, this.makeIo()));

    this.cursors = this.input.keyboard.createCursorKeys();
    this.wasd = this.input.keyboard.addKeys("W,A,S,D");
    this.input.keyboard.addCapture("UP,DOWN,LEFT,RIGHT,SPACE,ENTER,W,A,S,D");

    // Held keys are polled in update(); a tap shorter than one frame would be
    // missed by polling alone, so keydown queues a single step as well.
    this.input.keyboard.on("keydown", (event) => {
      if (isConfirm(event)) {
        if (!this.busy && !this.ui.open && !this.moving) this.tryInteract();
        return;
      }
      const direction = KEY_TO_DIR[event.code] ?? KEY_TO_DIR[event.key];
      if (direction) this.queued = direction;
      this.idleSince = this.time.now;   // any input resets the idle clock
    });

    bus.emit(Events.ZONE_LOADED, {
      id: this.pkg.id,
      kind: this.pkg.kind,
      authored: this.world.zones?.[this.pkg.id]?.authored ?? null,
      summary: this.pkg.summary,
      entities: this.pkg.entities.length,
      size: [this.pkg.width, this.pkg.height],
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

    const key = tilesetKey(this.pkg.tileset);
    const map = this.make.tilemap({ tileWidth: TILE, tileHeight: TILE, width, height });
    const tileset = map.addTilesetImage(key, key, TILE, TILE, 0, 0);

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
        bus.emit(Events.LOG, `no sprite matched ${entity.id} [${(entity.sprite_tags ?? []).join(", ")}] — using generic`);
      }
      const sprite = this.add
        .sprite(entity.x * TILE + TILE / 2, entity.y * TILE + TILE, key, 0)
        .setOrigin(0.5, 1)
        .setDepth(10 + entity.y);

      this.entities.set(entity.id, { def: entity, sprite });
      if (entity.blocking ?? entity.type !== "trigger") this.blocked.add(`${entity.x},${entity.y}`);
    }
  }

  buildPlayer() {
    const start = this.world.position;
    this.px = start.x;
    this.py = start.y;
    this.player = this.add
      .sprite(this.px * TILE + TILE / 2, this.py * TILE + TILE, "sprite_player", FRAME_FOR.down)
      .setOrigin(0.5, 1)
      .setDepth(10 + this.py);
  }

  buildCamera() {
    const camera = this.cameras.main;
    camera.setBounds(0, 0, this.mapWidth * TILE, this.mapHeight * TILE);
    camera.startFollow(this.player, true, 0.18, 0.18);
    camera.fadeIn(220, 0, 0, 0);
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
      startBattle: (encounterId) => this.startBattle(encounterId),
      // Recorded, not acted on: WARP halts the script, and tearing the scene
      // down while the runner is still unwinding through it would be a mess.
      warp: async (destination) => {
        this.pendingWarp = destination;
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

  // --- prefetching -------------------------------------------------------

  /** Design doc 6: warm the neighbours once the player has stopped moving.
   *  Waiting for idle matters — a player crossing a town has not chosen a door
   *  yet, and speculating while they walk would build the wrong one. */
  maybePrefetch() {
    if (!this.cache || this.prefetchArmed) return;
    if (!this.idleSince) {
      this.idleSince = this.time.now;
      return;
    }
    if (this.time.now - this.idleSince < IDLE_BEFORE_PREFETCH) return;
    this.prefetchArmed = true;
    this.prefetchNeighbours();
  }

  prefetchNeighbours() {
    if (!this.cache) return;
    this.cache.schedule(neighboursOf(this.pkg, this.world.ledger));
    this.cache.drain();
  }

  // --- battles -----------------------------------------------------------

  /** Arm the encounter counter for this zone. Deterministic from the world
   *  seed, so the same walk through the same floor meets the same things. */
  _armEncounters() {
    const table = this.pkg.encounters;
    this.encounterRng = makeRng(hashSeed(this.registry.get("seed"), this.pkg.id, "encounters"));
    this.stepsToEncounter = table?.enabled ? this._rollSteps() : Infinity;
  }

  _rollSteps() {
    const rate = this.pkg.encounters?.rate ?? 24;
    // Somewhere between half and one and a half times the rate, so the player
    // cannot count paces.
    return Math.max(4, Math.round(rate * (0.5 + this.encounterRng())));
  }

  _pickEncounter() {
    const table = (this.pkg.encounters?.table ?? []).filter((row) => this.registries.encounters[row.encounter_id]);
    if (!table.length) return null;
    const total = table.reduce((n, row) => n + (row.weight ?? 1), 0);
    let roll = this.encounterRng() * total;
    for (const row of table) {
      roll -= row.weight ?? 1;
      if (roll <= 0) return row;
    }
    return table[table.length - 1];
  }

  _onStepTaken() {
    if (this.stepsToEncounter === Infinity || this.busy) return;
    this.stepsToEncounter -= 1;
    if (this.stepsToEncounter > 0) return;
    this.stepsToEncounter = this._rollSteps();
    const row = this._pickEncounter();
    if (!row) return;
    // Routed through the ordinary op, so a random encounter and a scripted one
    // are the same code path all the way down.
    this.runScript([{ op: "START_BATTLE", encounter_id: row.encounter_id }]);
  }

  /**
   * Build a battle and hand it to BattleScene, which runs over this one paused.
   * Resolves "win" or "lose" for the Event Runner's START_BATTLE.
   */
  startBattle(encounterId) {
    const encounter = this.registries.encounters[encounterId];
    if (!encounter) {
      bus.emit(Events.LOG, `unknown encounter '${encounterId}' — skipping`);
      return Promise.resolve("win");
    }
    const row = (this.pkg.encounters?.table ?? []).find((r) => r.encounter_id === encounterId);
    const level = row?.level ?? encounter.base_level ?? 1;

    const battle = new Battle({
      party: this.world.party,
      enemies: buildEncounter(encounter, this.registries.templates, level),
      skills: this.registries.skills,
      items: this.registries.items,
      inventory: this.world.inventory,
      seed: hashSeed(this.registry.get("seed"), this.pkg.id, encounterId, this.battleCount++),
    });

    bus.emit(Events.LOG, `${encounter.display_name} — level ${level}`);

    return new Promise((resolve) => {
      this.scene.pause();
      this.scene.launch("BattleScene", {
        battle,
        encounterName: encounter.display_name,
        onDone: (outcome, result) => {
          this.scene.resume();
          this._afterBattle(outcome, result);
          resolve(outcome);
        },
      });
    });
  }

  _afterBattle(outcome, result) {
    for (const levelUp of result?.levelUps ?? []) {
      bus.emit(Events.LOG, `${levelUp.name} reached level ${levelUp.level}`);
    }
    if (outcome === "lose") {
      // Classic convention rather than a hard game over: the party wakes up
      // back in town, worse for wear. M5 can make death mean more.
      for (const member of this.world.party) {
        member.hp = Math.max(1, Math.floor(member.max_hp / 2));
      }
      const home = this.world.homeZone;
      bus.emit(Events.LOG, "the party wakes up back in town");
      if (home) {
        this.pendingWarp = { toZone: home.id, toX: home.spawn[0], toY: home.spawn[1] };
      }
    }
    this.world.touch();
    api.saveState(this.world.progressSnapshot()).catch((error) => {
      bus.emit(Events.LOG, `could not save progress: ${error.message}`);
    });
  }

  // --- zone transitions --------------------------------------------------

  async enterZone({ toZone, toX, toY }) {
    this.busy = true;
    this.cameras.main.fadeOut(180, 0, 0, 0);
    const curtain = this.showCurtain(`Entering ${toZone}…`);
    bus.emit(Events.LOG, `requesting ${toZone} from the authoring service`);

    try {
      const started = performance.now();
      const warmed = this.cache?.has(toZone) ?? false;
      const pkg = this.cache ? await this.cache.load(toZone) : await api.getZone(toZone);
      const ms = Math.round(performance.now() - started);
      bus.emit(
        Events.LOG,
        warmed
          ? `${toZone} was already warm (${ms}ms)`
          : `${toZone} ready in ${ms}ms (${pkg.width}×${pkg.height})`
      );

      this.world.setPosition(toZone, toX, toY);
      api.savePosition(toZone, toX, toY).catch(() => {});
      this.registry.set("zone", pkg);
      this.scene.restart();
    } catch (error) {
      console.error(error);
      curtain.destroy();
      this.cameras.main.fadeIn(180, 0, 0, 0);
      bus.emit(Events.LOG, `failed to enter ${toZone}: ${error.message}`);
      await this.ui.showText({ speaker: null, text: `[could not enter ${toZone} — see the log]` });
      this.busy = false;
      this.pendingWarp = null;
    }
  }

  showCurtain(message) {
    const { width, height } = this.scale;
    const container = this.add.container(0, 0).setDepth(2000).setScrollFactor(0);
    container.add(this.add.rectangle(0, 0, width, height, 0x0b0d12, 0.85).setOrigin(0));
    container.add(
      this.add
        .text(width / 2, height / 2, message, {
          fontFamily: "monospace",
          fontSize: "9px",
          color: "#ffd98a",
        })
        .setOrigin(0.5)
    );
    return container;
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

    this.maybePrefetch();

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
        if (!this.pendingWarp && !this.busy) this._onStepTaken();
      },
    });
  }

  checkWarp() {
    const warp = this.pkg.warps.find((w) => w.x === this.px && w.y === this.py);
    if (!warp) return;

    const lock = warp.locked;
    if (lock?.requires_item && this.world.countItem(lock.requires_item) < 1) {
      // The backend guarantees this key exists somewhere already visitable, so
      // this is a "not yet", never a dead end.
      this.runScript([{ op: "SHOW_TEXT", speaker: null, text: lock.locked_text ?? "It will not open." }]);
      return;
    }
    if (lock?.requires_item) {
      if (lock.consumes) this.world.takeItem(lock.requires_item, 1);
      if (this.world.consumeObligation(lock.requires_item)) {
        bus.emit(Events.LOG, `the ${lock.requires_item} opens the way to ${warp.to_zone}`);
        api.saveState(this.world.progressSnapshot()).catch(() => {});
      }
    }
    this.enterZone({ toZone: warp.to_zone, toX: warp.to_x, toY: warp.to_y });
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
      const warp = this.pendingWarp;
      this.pendingWarp = null;
      if (warp) {
        this.enterZone(warp);
      } else {
        // Swallow the keypress that closed the last box so it cannot
        // immediately re-trigger the same entity.
        this.time.delayedCall(120, () => {
          this.busy = false;
        });
      }
    }
  }
}
