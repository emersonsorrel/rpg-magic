import * as Phaser from "phaser";

import { bus, Events } from "../GameBus.js";
import { resolveSprite } from "../assetPack.js";

const W = 320;
const H = 240;

const MENU = [
  { id: "attack", label: "Attack" },
  { id: "skill", label: "Skill" },
  { id: "item", label: "Item" },
  { id: "flee", label: "Flee" },
];

const FONT = { fontFamily: "monospace", fontSize: "9px", color: "#f4f1e8" };
const DIM = { ...FONT, color: "#9aa0ae" };
const GOLD = { ...FONT, color: "#ffd98a" };

/**
 * Turn-based battle, launched over the paused overworld (design doc 6).
 *
 * This scene is presentation only. Every rule — turn order, damage, xp, level
 * ups — lives in battle/engine.js, which knows nothing about Phaser. The scene
 * asks the engine what is legal, sends it a command, and narrates the events it
 * gets back.
 */
export class BattleScene extends Phaser.Scene {
  constructor() {
    super("BattleScene");
  }

  init(data) {
    this.battle = data.battle;
    this.onDone = data.onDone;
    this.encounterName = data.encounterName ?? "Battle";
    this.mode = "message";
    this.messages = [];
    this.pending = null;
    this.cursor = 0;
    this.targetIndex = 0;
  }

  create() {
    this.add.rectangle(0, 0, W, H, 0x0d1017).setOrigin(0).setDepth(0);
    this.add.rectangle(0, 24, W, 96, 0x18202c).setOrigin(0).setDepth(1);

    this.title = this.add.text(W / 2, 8, this.encounterName, GOLD).setOrigin(0.5, 0).setDepth(5);

    this.enemySprites = [];
    this.buildEnemies();
    this.buildPartyPanel();
    this.buildMenu();

    this.log = this.add.text(8, 128, "", {
      ...FONT, wordWrap: { width: W - 16 }, lineSpacing: 2,
    }).setDepth(5);

    this.input.keyboard.addCapture("UP,DOWN,LEFT,RIGHT,SPACE,ENTER,ESC,W,A,S,D");
    this.input.keyboard.on("keydown", (event) => this.onKey(event));

    this.queueEvents(this.battle.openingEvents ?? []);
    this.pump();
  }

  // --- layout ------------------------------------------------------------

  buildEnemies() {
    for (const sprite of this.enemySprites) sprite.container.destroy();
    this.enemySprites = [];

    const enemies = this.battle.enemies;
    const gap = Math.min(72, (W - 40) / Math.max(1, enemies.length));
    const startX = W / 2 - (gap * (enemies.length - 1)) / 2;

    enemies.forEach((enemy, i) => {
      const { key } = resolveSprite(enemy.tags, { seed: enemy.templateId });
      const container = this.add.container(startX + i * gap, 72).setDepth(4);
      const image = this.add.image(0, 0, key).setOrigin(0.5);
      const name = this.add.text(0, 22, enemy.name, DIM).setOrigin(0.5, 0);
      container.add([image, name]);
      this.enemySprites.push({ enemy, container, image, name });
    });
  }

  buildPartyPanel() {
    this.add.rectangle(4, 168, 176, 68, 0x12161f, 0.95).setOrigin(0).setDepth(3)
      .setStrokeStyle(1, 0x4a5570);
    this.partyRows = this.battle.party.map((member, i) =>
      this.add.text(10, 174 + i * 16, "", FONT).setDepth(5)
    );
    this.refreshParty();
  }

  buildMenu() {
    this.add.rectangle(184, 168, 132, 68, 0x12161f, 0.95).setOrigin(0).setDepth(3)
      .setStrokeStyle(1, 0x4a5570);
    this.menuTexts = MENU.map((entry, i) =>
      this.add.text(200, 174 + i * 14, entry.label, FONT).setDepth(5)
    );
    this.menuCursor = this.add.text(190, 174, "▶", GOLD).setDepth(5);
    this.subTexts = [];
  }

  refreshParty() {
    this.battle.party.forEach((member, i) => {
      const row = this.partyRows[i];
      if (!row) return;
      const down = member.hp <= 0;
      row.setText(`${member.name.slice(0, 8).padEnd(8)} ${String(member.hp).padStart(3)}/${member.maxHp}  MP ${member.mp}`);
      row.setColor(down ? "#8a5c5c" : member.hp < member.maxHp * 0.3 ? "#e0a25c" : "#f4f1e8");
    });
    for (const entry of this.enemySprites) {
      entry.container.setAlpha(entry.enemy.hp > 0 ? 1 : 0.25);
    }
  }

  // --- narration ---------------------------------------------------------

  queueEvents(events) {
    for (const event of events) {
      const line = describe(event);
      if (line) this.messages.push(line);
      if (event.kind === "levelup" || event.kind === "victory") {
        bus.emit(Events.LOG, line);
      }
    }
  }

  /** Show queued messages one at a time, then hand control back. */
  pump() {
    this.refreshParty();
    if (this.messages.length) {
      this.mode = "message";
      const shown = this.messages.splice(0, 1);
      this.log.setText(shown[0]);
      this.time.delayedCall(650, () => this.pump());
      return;
    }
    if (this.battle.finished) {
      this.finish();
      return;
    }
    this.mode = "command";
    this.cursor = 0;
    this.clearSub();
    this.drawMenu();
  }

  drawMenu() {
    const actor = this.battle.actor;
    this.log.setText(actor ? `${actor.name}'s turn.` : "");
    this.menuTexts.forEach((text, i) => {
      text.setVisible(true);
      text.setColor(i === this.cursor && this.mode === "command" ? "#ffd98a" : "#f4f1e8");
    });
    this.menuCursor.setVisible(this.mode === "command").setY(174 + this.cursor * 14);
  }

  clearSub() {
    for (const text of this.subTexts) text.destroy();
    this.subTexts = [];
    this.targetMarker?.destroy();
    this.targetMarker = null;
  }

  showList(entries, title) {
    this.clearSub();
    this.log.setText(title);
    this.menuCursor.setVisible(false);
    this.subTexts = entries.map((entry, i) =>
      this.add.text(200, 174 + i * 12, entry.label, entry.usable === false ? DIM : FONT).setDepth(6)
    );
    this.listEntries = entries;
    this.cursor = 0;
    this.highlightList();
  }

  highlightList() {
    this.subTexts.forEach((text, i) => {
      const entry = this.listEntries[i];
      text.setColor(i === this.cursor ? "#ffd98a" : entry.usable === false ? "#6a7284" : "#f4f1e8");
    });
  }

  showTargets(side) {
    this.mode = "target";
    this.targetSide = side;
    const list = side === "enemy"
      ? this.enemySprites.filter((e) => e.enemy.hp > 0)
      : this.battle.party.filter((m) => m.hp > 0);
    this.targets = list;
    this.targetIndex = 0;
    this.log.setText("Choose a target.");
    this.drawTargetMarker();
  }

  drawTargetMarker() {
    this.targetMarker?.destroy();
    const target = this.targets[this.targetIndex];
    if (!target) return;
    if (this.targetSide === "enemy") {
      this.targetMarker = this.add.text(target.container.x, 44, "▼", GOLD)
        .setOrigin(0.5).setDepth(7);
    } else {
      const row = this.battle.party.indexOf(target);
      this.targetMarker = this.add.text(6, 174 + row * 16, "▶", GOLD).setDepth(7);
    }
  }

  targetId() {
    const target = this.targets[this.targetIndex];
    if (!target) return null;
    return this.targetSide === "enemy" ? target.enemy.id : target.id;
  }

  // --- input -------------------------------------------------------------

  onKey(event) {
    const key = event.key;
    const confirm = key === " " || key === "Enter";
    const back = key === "Escape";
    const up = key === "ArrowUp" || key === "w";
    const down = key === "ArrowDown" || key === "s";
    const left = key === "ArrowLeft" || key === "a";
    const right = key === "ArrowRight" || key === "d";

    if (this.mode === "message" || this.mode === "resolving") return;

    if (this.mode === "command") {
      if (up) { this.cursor = (this.cursor + MENU.length - 1) % MENU.length; this.drawMenu(); }
      else if (down) { this.cursor = (this.cursor + 1) % MENU.length; this.drawMenu(); }
      else if (confirm) this.chooseCommand(MENU[this.cursor].id);
      return;
    }

    if (this.mode === "skill" || this.mode === "item") {
      if (up) { this.cursor = (this.cursor + this.listEntries.length - 1) % this.listEntries.length; this.highlightList(); }
      else if (down) { this.cursor = (this.cursor + 1) % this.listEntries.length; this.highlightList(); }
      else if (back) { this.mode = "command"; this.clearSub(); this.drawMenu(); }
      else if (confirm) this.chooseListEntry();
      return;
    }

    if (this.mode === "target") {
      if (left || up) { this.targetIndex = (this.targetIndex + this.targets.length - 1) % this.targets.length; this.drawTargetMarker(); }
      else if (right || down) { this.targetIndex = (this.targetIndex + 1) % this.targets.length; this.drawTargetMarker(); }
      else if (back) { this.mode = "command"; this.clearSub(); this.drawMenu(); }
      else if (confirm) this.commit();
    }
  }

  chooseCommand(id) {
    if (id === "attack") {
      this.pending = { type: "attack" };
      this.showTargets("enemy");
      return;
    }
    if (id === "flee") {
      this.pending = { type: "flee" };
      this.commit();
      return;
    }
    const options = this.battle.options();
    if (id === "skill") {
      if (!options.skills.length) return;
      this.mode = "skill";
      this.showList(options.skills.map((s) => ({
        id: s.id, label: `${s.name}${s.mp ? ` ${s.mp}mp` : ""}`, usable: s.usable, skill: s,
      })), "Which skill?");
      return;
    }
    if (id === "item") {
      if (!options.items.length) return;
      this.mode = "item";
      this.showList(options.items.map((i) => ({
        id: i.id, label: `${i.name} x${i.qty}`, item: i,
      })), "Which item?");
    }
  }

  chooseListEntry() {
    const entry = this.listEntries[this.cursor];
    if (!entry || entry.usable === false) return;

    if (this.mode === "skill") {
      this.pending = { type: "skill", skillId: entry.id };
      const target = entry.skill.target;
      if (target === "self" || target === "all_enemies" || target === "all_allies") {
        this.commit();
      } else {
        this.showTargets(target === "one_ally" ? "party" : "enemy");
      }
      return;
    }
    this.pending = { type: "item", itemId: entry.id };
    this.showTargets("party");
  }

  commit() {
    this.mode = "resolving";
    this.clearSub();
    this.menuCursor.setVisible(false);
    const action = { ...this.pending };
    if (this.targets?.length) action.targetId = this.targetId();
    this.pending = null;
    this.queueEvents(this.battle.act(action));
    this.pump();
  }

  finish() {
    this.mode = "resolving";
    const outcome = this.battle.state;
    this.log.setText(
      outcome === "won" ? "Victory!" : outcome === "fled" ? "Got away." : "The party falls..."
    );
    this.time.delayedCall(900, () => {
      const result = this.battle.commit();
      this.clearSub();
      this.scene.stop();
      this.onDone?.(outcome === "lost" ? "lose" : "win", result);
    });
  }
}

/** Events are data; this is the only place they become English. */
function describe(event) {
  switch (event.kind) {
    case "action": return event.label;
    case "damage": return `${event.targetName} takes ${event.amount}.`;
    case "heal": return `${event.targetName} recovers ${event.amount}.`;
    case "mp": return `${event.targetName} recovers ${event.amount} MP.`;
    case "guard": return `${event.targetName} braces.`;
    case "revive": return `${event.targetName} is back on their feet.`;
    case "defeat": return `${event.targetName} is defeated.`;
    case "flee": return event.ok ? `${event.actorName} breaks away!` : `${event.actorName} cannot escape!`;
    case "victory": return `Victory! ${event.xp} XP.`;
    case "levelup": return `${event.targetName} reaches level ${event.level}!`;
    case "lost": return "The party falls...";
    default: return null;
  }
}
