import * as Phaser from "phaser";
import { bus, Events } from "../GameBus.js";

const WIDTH = 320;
const HEIGHT = 240;
const BOX_X = 6;
const BOX_W = WIDTH - 12;
const BOX_H = 70;
const BOX_Y = HEIGHT - BOX_H - 6;

/**
 * Dialogue, choices and menus. Runs parallel to whichever scene is active
 * (design doc 6) and is the presentation half of the EventRunner host: it owns
 * showText and showChoice, and nothing else knows how a text box works.
 */
export class UIScene extends Phaser.Scene {
  constructor() {
    super("UIScene");
    this.open = false;
    this.pending = null;
  }

  create() {
    this.panel = this.add.graphics().setDepth(1000);
    this.speakerText = this.add
      .text(BOX_X + 10, BOX_Y + 6, "", { fontFamily: "monospace", fontSize: "9px", color: "#ffd98a" })
      .setDepth(1002);
    this.bodyText = this.add
      .text(BOX_X + 10, BOX_Y + 20, "", {
        fontFamily: "monospace",
        fontSize: "9px",
        color: "#f4f1e8",
        wordWrap: { width: BOX_W - 20 },
        lineSpacing: 3,
      })
      .setDepth(1002);
    this.cursor = this.add
      .text(0, 0, "▶", { fontFamily: "monospace", fontSize: "9px", color: "#ffd98a" })
      .setDepth(1002)
      .setVisible(false);
    this.advance = this.add
      .text(BOX_X + BOX_W - 16, BOX_Y + BOX_H - 16, "▼", {
        fontFamily: "monospace",
        fontSize: "9px",
        color: "#ffd98a",
      })
      .setDepth(1002)
      .setVisible(false);

    this.tweens.add({
      targets: this.advance, alpha: 0.2, duration: 500, yoyo: true, repeat: -1,
    });

    this.optionTexts = [];
    this.hide();

    this.input.keyboard.addCapture("UP,DOWN,LEFT,RIGHT,SPACE,ENTER,W,A,S,D");
    this.keys = this.input.keyboard.addKeys("SPACE,ENTER,UP,DOWN,W,S");
    this.input.keyboard.on("keydown", (event) => this.onKey(event));
  }

  // --- host surface ------------------------------------------------------

  showText({ speaker, text }) {
    return new Promise((resolve) => {
      this.render({ speaker, body: text, options: [] });
      this.advance.setVisible(true);
      this.pending = { kind: "text", resolve };
      bus.emit(Events.DIALOGUE, { speaker, text });
    });
  }

  showChoice({ speaker, prompt, labels }) {
    return new Promise((resolve) => {
      this.render({ speaker, body: prompt, options: labels });
      this.selected = 0;
      this.drawCursor();
      this.pending = { kind: "choice", resolve };
      bus.emit(Events.DIALOGUE, { speaker, text: prompt, options: labels });
    });
  }

  // --- rendering ---------------------------------------------------------

  render({ speaker, body, options }) {
    this.open = true;
    this.panel.setVisible(true).clear();
    this.panel.fillStyle(0x12161f, 0.94).fillRoundedRect(BOX_X, BOX_Y, BOX_W, BOX_H, 5);
    this.panel.lineStyle(2, 0xf4f1e8, 0.9).strokeRoundedRect(BOX_X, BOX_Y, BOX_W, BOX_H, 5);
    this.panel.lineStyle(1, 0x4a5570, 1).strokeRoundedRect(BOX_X + 3, BOX_Y + 3, BOX_W - 6, BOX_H - 6, 4);

    this.speakerText.setText(speaker ?? "").setVisible(Boolean(speaker));
    this.bodyText.setY(speaker ? BOX_Y + 20 : BOX_Y + 12).setText(body).setVisible(true);

    for (const text of this.optionTexts) text.destroy();
    this.optionTexts = options.map((label, i) =>
      this.add
        .text(BOX_X + 24, BOX_Y + 20 + this.bodyText.height + 6 + i * 12, label, {
          fontFamily: "monospace",
          fontSize: "9px",
          color: "#f4f1e8",
        })
        .setDepth(1002)
    );
    this.advance.setVisible(false);
    this.cursor.setVisible(options.length > 0);
  }

  drawCursor() {
    const target = this.optionTexts[this.selected];
    if (!target) return;
    this.cursor.setPosition(BOX_X + 12, target.y);
    this.optionTexts.forEach((text, i) =>
      text.setColor(i === this.selected ? "#ffd98a" : "#f4f1e8")
    );
  }

  hide() {
    this.open = false;
    this.panel.setVisible(false);
    this.speakerText.setVisible(false);
    this.bodyText.setVisible(false);
    this.cursor.setVisible(false);
    this.advance.setVisible(false);
    for (const text of this.optionTexts) text.destroy();
    this.optionTexts = [];
  }

  // --- input -------------------------------------------------------------

  onKey(event) {
    if (!this.pending) return;
    const key = event.key;
    const confirm = key === " " || key === "Enter";

    if (this.pending.kind === "choice") {
      if (key === "ArrowUp" || key === "w") {
        this.selected = (this.selected + this.optionTexts.length - 1) % this.optionTexts.length;
        this.drawCursor();
      } else if (key === "ArrowDown" || key === "s") {
        this.selected = (this.selected + 1) % this.optionTexts.length;
        this.drawCursor();
      } else if (confirm) {
        const { resolve } = this.pending;
        const chosen = this.selected;
        this.pending = null;
        this.hide();
        resolve(chosen);
      }
      return;
    }

    if (confirm) {
      const { resolve } = this.pending;
      this.pending = null;
      this.hide();
      resolve();
    }
  }
}
