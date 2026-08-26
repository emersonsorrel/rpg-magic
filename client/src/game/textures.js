/**
 * Procedurally drawn placeholder art.
 *
 * There is no art pack yet, and design doc 3.4 is explicit that a missing asset
 * must never block anything -- so the "default pack" at M1 is drawn at boot into
 * canvas textures. Everything here is addressed by the same keys the tag
 * resolver returns (see assetPack.js), so dropping in real PNGs later means
 * changing the loader, not the scenes.
 *
 * Tile indices match backend/registries/tilesets.json.
 */

export const TILE = 16;
export const TILESET_KEY = "tiles";
const COLUMNS = 8;
const TILE_COUNT = 32;

const PALETTE = {
  grass: ["#4e7a3a", "#3f6630", "#5c8a44"],
  road: ["#9c8154", "#8a7048", "#ab9065"],
  water: ["#2f5d8a", "#27507a", "#3a6d9c"],
  planks: ["#8a6a45", "#75593a"],
  sand: ["#c9b489", "#b8a279"],
  trunk: "#4a3524",
  leaf: ["#2f5d28", "#3d7434", "#264c22"],
  stone: ["#7d7468", "#6a6259", "#8d8478"],
  door: "#5a3f28",
  wellStone: "#6f6a63",
  fence: "#7a5c3a",
  thatch: "#8a6b3a",
  flower: ["#d8657a", "#e2c65a", "#ffffff"],
};

/** Deterministic noise so the same tile always dithers the same way. */
function noise(x, y, salt = 0) {
  let h = (x * 374761393 + y * 668265263 + salt * 1274126177) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177) >>> 0;
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

function speckle(ctx, ox, oy, colors, density = 0.22, salt = 0) {
  for (let y = 0; y < TILE; y += 1) {
    for (let x = 0; x < TILE; x += 1) {
      const n = noise(ox + x, oy + y, salt);
      if (n < density) {
        ctx.fillStyle = colors[1];
        ctx.fillRect(ox + x, oy + y, 1, 1);
      } else if (n > 1 - density * 0.5 && colors[2]) {
        ctx.fillStyle = colors[2];
        ctx.fillRect(ox + x, oy + y, 1, 1);
      }
    }
  }
}

function fill(ctx, ox, oy, color) {
  ctx.fillStyle = color;
  ctx.fillRect(ox, oy, TILE, TILE);
}

const TILE_PAINTERS = {
  1: (ctx, ox, oy) => { fill(ctx, ox, oy, PALETTE.grass[0]); speckle(ctx, ox, oy, PALETTE.grass, 0.2, 1); },
  2: (ctx, ox, oy) => { fill(ctx, ox, oy, PALETTE.road[0]); speckle(ctx, ox, oy, PALETTE.road, 0.18, 2); },
  3: (ctx, ox, oy) => {
    fill(ctx, ox, oy, PALETTE.water[0]);
    ctx.fillStyle = PALETTE.water[2];
    for (let y = 2; y < TILE; y += 5) {
      const shift = Math.floor(noise(ox, oy + y, 3) * 6);
      ctx.fillRect(ox + shift, oy + y, 6, 1);
    }
  },
  4: (ctx, ox, oy) => {
    fill(ctx, ox, oy, PALETTE.planks[0]);
    ctx.fillStyle = PALETTE.planks[1];
    for (let y = 3; y < TILE; y += 5) ctx.fillRect(ox, oy + y, TILE, 1);
  },
  5: (ctx, ox, oy) => { fill(ctx, ox, oy, PALETTE.sand[0]); speckle(ctx, ox, oy, PALETTE.sand, 0.15, 5); },

  16: (ctx, ox, oy) => { // tree
    ctx.fillStyle = PALETTE.trunk;
    ctx.fillRect(ox + 7, oy + 10, 2, 6);
    ctx.fillStyle = PALETTE.leaf[2];
    ctx.beginPath(); ctx.arc(ox + 8, oy + 7, 6.5, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = PALETTE.leaf[1];
    ctx.beginPath(); ctx.arc(ox + 7, oy + 6, 5, 0, Math.PI * 2); ctx.fill();
  },
  17: (ctx, ox, oy) => { // stone wall
    fill(ctx, ox, oy, PALETTE.stone[0]);
    ctx.fillStyle = PALETTE.stone[1];
    for (let y = 0; y < TILE; y += 5) ctx.fillRect(ox, oy + y, TILE, 1);
    for (let y = 0; y < TILE; y += 5) {
      const offset = (y / 5) % 2 === 0 ? 5 : 11;
      ctx.fillRect(ox + offset, oy + y, 1, 5);
    }
  },
  18: (ctx, ox, oy) => { // door
    fill(ctx, ox, oy, PALETTE.stone[1]);
    ctx.fillStyle = PALETTE.door;
    ctx.fillRect(ox + 2, oy + 3, 12, 13);
    ctx.fillStyle = "#c9a45e";
    ctx.fillRect(ox + 11, oy + 9, 2, 2);
  },
  19: (ctx, ox, oy) => { // well
    fill(ctx, ox, oy, PALETTE.grass[0]);
    ctx.fillStyle = PALETTE.wellStone;
    ctx.beginPath(); ctx.arc(ox + 8, oy + 9, 6, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#1d2a33";
    ctx.beginPath(); ctx.arc(ox + 8, oy + 9, 3.5, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = PALETTE.trunk;
    ctx.fillRect(ox + 3, oy + 1, 1, 8); ctx.fillRect(ox + 12, oy + 1, 1, 8);
    ctx.fillRect(ox + 3, oy + 1, 10, 1);
  },
  20: (ctx, ox, oy) => { // fence
    ctx.fillStyle = PALETTE.fence;
    ctx.fillRect(ox, oy + 7, TILE, 2);
    ctx.fillRect(ox, oy + 12, TILE, 2);
    ctx.fillRect(ox + 3, oy + 4, 2, 11);
    ctx.fillRect(ox + 11, oy + 4, 2, 11);
  },
  21: (ctx, ox, oy) => { // thatch roof
    fill(ctx, ox, oy, PALETTE.thatch);
    ctx.fillStyle = "#6d5329";
    for (let y = 2; y < TILE; y += 4) ctx.fillRect(ox, oy + y, TILE, 1);
  },
  22: (ctx, ox, oy) => { // flowers
    for (let i = 0; i < 5; i += 1) {
      const fx = ox + 2 + Math.floor(noise(ox, oy, i) * 12);
      const fy = oy + 2 + Math.floor(noise(oy, ox, i + 9) * 12);
      ctx.fillStyle = PALETTE.flower[i % PALETTE.flower.length];
      ctx.fillRect(fx, fy, 2, 2);
    }
  },
  23: (ctx, ox, oy) => { // signpost
    ctx.fillStyle = PALETTE.trunk;
    ctx.fillRect(ox + 7, oy + 8, 2, 8);
    ctx.fillStyle = PALETTE.planks[0];
    ctx.fillRect(ox + 2, oy + 3, 12, 6);
    ctx.fillStyle = PALETTE.planks[1];
    ctx.fillRect(ox + 4, oy + 5, 8, 1);
  },
};

export function buildTileset(scene) {
  if (scene.textures.exists(TILESET_KEY)) return;
  const rows = Math.ceil(TILE_COUNT / COLUMNS);
  const texture = scene.textures.createCanvas(TILESET_KEY, COLUMNS * TILE, rows * TILE);
  const ctx = texture.getContext();
  ctx.imageSmoothingEnabled = false;

  for (let index = 0; index < TILE_COUNT; index += 1) {
    const painter = TILE_PAINTERS[index];
    if (!painter) continue; // stays transparent: index 0 and every unused slot
    painter(ctx, (index % COLUMNS) * TILE, Math.floor(index / COLUMNS) * TILE);
  }
  texture.refresh();
}

// --- characters ----------------------------------------------------------

const CHARACTER_W = 16;
const CHARACTER_H = 24;
export const DIRECTIONS = ["down", "left", "right", "up"];

const CHARACTERS = {
  sprite_elder:    { skin: "#e0b48c", hair: "#d8d5cf", tunic: "#6b6f9c", trim: "#43466b", legs: "#3b3a44" },
  sprite_smith:    { skin: "#c98f5f", hair: "#3a2a1c", tunic: "#8a4a32", trim: "#5e3122", legs: "#3b3a44" },
  sprite_villager: { skin: "#e6bb92", hair: "#6b4726", tunic: "#5d8a53", trim: "#3f6438", legs: "#4a4230" },
  sprite_generic:  { skin: "#d9a97f", hair: "#4a3a2c", tunic: "#7a7a86", trim: "#55555f", legs: "#3b3a44" },
  sprite_player:   { skin: "#f0c69b", hair: "#c46a3a", tunic: "#3f7fa8", trim: "#2b5a7a", legs: "#3b3a44" },
};

function drawCharacter(ctx, ox, oy, direction, palette) {
  const cx = ox + 8;
  // shadow
  ctx.fillStyle = "rgba(0,0,0,0.25)";
  ctx.beginPath(); ctx.ellipse(cx, oy + 22, 5, 2, 0, 0, Math.PI * 2); ctx.fill();
  // legs
  ctx.fillStyle = palette.legs;
  ctx.fillRect(ox + 5, oy + 18, 3, 4);
  ctx.fillRect(ox + 9, oy + 18, 3, 4);
  // body
  ctx.fillStyle = palette.tunic;
  ctx.fillRect(ox + 4, oy + 11, 8, 8);
  ctx.fillStyle = palette.trim;
  ctx.fillRect(ox + 4, oy + 17, 8, 1);
  // arms
  ctx.fillStyle = palette.skin;
  ctx.fillRect(ox + 3, oy + 12, 2, 5);
  ctx.fillRect(ox + 11, oy + 12, 2, 5);
  // head
  ctx.fillStyle = palette.skin;
  ctx.fillRect(ox + 4, oy + 4, 8, 7);
  // hair
  ctx.fillStyle = palette.hair;
  ctx.fillRect(ox + 3, oy + 2, 10, 3);
  if (direction === "up") {
    ctx.fillRect(ox + 3, oy + 2, 10, 7); // back of the head
  } else {
    ctx.fillRect(ox + 3, oy + 2, 2, 5);
    ctx.fillRect(ox + 11, oy + 2, 2, 5);
    ctx.fillStyle = "#2b2b33";
    if (direction === "down") {
      ctx.fillRect(ox + 6, oy + 7, 1, 2);
      ctx.fillRect(ox + 9, oy + 7, 1, 2);
    } else if (direction === "left") {
      ctx.fillRect(ox + 5, oy + 7, 1, 2);
    } else {
      ctx.fillRect(ox + 10, oy + 7, 1, 2);
    }
  }
}

function drawChest(ctx, ox, oy) {
  ctx.fillStyle = "rgba(0,0,0,0.25)";
  ctx.beginPath(); ctx.ellipse(ox + 8, oy + 22, 6, 2, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#7a5230";
  ctx.fillRect(ox + 2, oy + 12, 12, 9);
  ctx.fillStyle = "#8f6238";
  ctx.fillRect(ox + 2, oy + 8, 12, 5);
  ctx.fillStyle = "#d0a94f";
  ctx.fillRect(ox + 2, oy + 12, 12, 1);
  ctx.fillRect(ox + 7, oy + 13, 2, 4);
  ctx.fillStyle = "#4a3018";
  ctx.strokeStyle = "#4a3018";
  ctx.strokeRect(ox + 2.5, oy + 8.5, 11, 12);
}

function drawSign(ctx, ox, oy) {
  ctx.fillStyle = "rgba(0,0,0,0.25)";
  ctx.beginPath(); ctx.ellipse(ox + 8, oy + 22, 4, 2, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#4a3524";
  ctx.fillRect(ox + 7, oy + 13, 2, 8);
  ctx.fillStyle = "#8a6a45";
  ctx.fillRect(ox + 2, oy + 6, 12, 8);
  ctx.fillStyle = "#6d5334";
  ctx.fillRect(ox + 4, oy + 9, 8, 1);
  ctx.fillRect(ox + 4, oy + 11, 6, 1);
}

/** One texture per sprite key, four frames wide: down, left, right, up. */
export function buildCharacters(scene) {
  for (const [key, palette] of Object.entries(CHARACTERS)) {
    if (scene.textures.exists(key)) continue;
    const texture = scene.textures.createCanvas(key, CHARACTER_W * 4, CHARACTER_H);
    const ctx = texture.getContext();
    ctx.imageSmoothingEnabled = false;
    DIRECTIONS.forEach((direction, i) => {
      drawCharacter(ctx, i * CHARACTER_W, 0, direction, palette);
      texture.add(i, 0, i * CHARACTER_W, 0, CHARACTER_W, CHARACTER_H);
    });
    texture.refresh();
  }

  for (const [key, painter] of [["sprite_chest", drawChest], ["sprite_sign", drawSign]]) {
    if (scene.textures.exists(key)) continue;
    const texture = scene.textures.createCanvas(key, CHARACTER_W * 4, CHARACTER_H);
    const ctx = texture.getContext();
    ctx.imageSmoothingEnabled = false;
    for (let i = 0; i < 4; i += 1) {
      painter(ctx, i * CHARACTER_W, 0);
      texture.add(i, 0, i * CHARACTER_W, 0, CHARACTER_W, CHARACTER_H);
    }
    texture.refresh();
  }
}

export function buildAll(scene) {
  buildTileset(scene);
  buildCharacters(scene);
}
