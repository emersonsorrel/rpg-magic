import * as Phaser from "phaser";
import { buildAll } from "../textures.js";

/** Draws the placeholder pack, then hands off. Design doc 6: "BootScene --
 *  load asset manifest, resolve tag mappings." */
export class BootScene extends Phaser.Scene {
  constructor() {
    super("BootScene");
  }

  create() {
    buildAll(this);
    this.scene.start("OverworldScene");
    this.scene.launch("UIScene");
  }
}
