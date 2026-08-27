/**
 * Procedurally drawn placeholder art.
 *
 * Tile indices mean the same thing in every tileset (see
 * backend/registries/tilesets.json), so one painter table serves every biome
 * and only the palette changes. A few indices read badly under a straight
 * recolour -- a fence is not rubble -- so a tileset may override individual
 * painters.
 *
 * Everything is addressed by the keys the tag resolver returns (assetPack.js).
 * Dropping in real PNGs later changes the loader, not the scenes.
 */

export const TILE = 16;
const COLUMNS = 8;
const TILE_COUNT = 32;

export const tilesetKey = (tileset) => `tiles_${tileset}`;

const PALETTES = {
  overworld_temperate: {
    floor: ["#4e7a3a", "#3f6630", "#5c8a44"],
    path: ["#9c8154", "#8a7048", "#ab9065"],
    water: ["#2f5d8a", "#27507a", "#3a6d9c"],
    planks: ["#8a6a45", "#75593a"],
    dry: ["#c9b489", "#b8a279"],
    trunk: "#4a3524",
    canopy: ["#264c22", "#3d7434"],
    wall: ["#7d7468", "#6a6259"],
    door: "#5a3f28",
    knob: "#c9a45e",
    feature: "#6f6a63",
    barrier: "#7a5c3a",
    roof: ["#8a6b3a", "#6d5329"],
    detail: ["#d8657a", "#e2c65a", "#ffffff"],
    post: "#4a3524",
    stairs: ["#8d8478", "#5c554d", "#a9a094"],
  },
  interior_wood: {
    floor: ["#8a6a45", "#75593a", "#9c7b52"],
    path: ["#6b5942", "#5a4a36", "#7d6a50"],
    water: ["#3b5a68", "#2f4a56", "#4d6f7d"],
    planks: ["#7a5c3a", "#63482c"],
    dry: ["#c9b489", "#b8a279"],
    trunk: "#5a3f28",
    canopy: ["#63482c", "#7a5c3a"],
    wall: ["#b8a98d", "#9e8f74"],
    door: "#5a3f28",
    knob: "#c9a45e",
    feature: "#7d7468",
    barrier: "#7a5c3a",
    roof: ["#5a4a36", "#4a3c2b"],
    detail: ["#8a7b5c", "#a89878", "#6d6047"],
    post: "#6d5334",
    stairs: ["#8d8478", "#5c554d", "#a9a094"],
  },
  mine_damp: {
    floor: ["#4a4038", "#3c332c", "#574c42"],
    path: ["#5a5048", "#4a4038", "#6b6058"],
    water: ["#2b3a3a", "#22302f", "#38504c"],
    planks: ["#6b543a", "#57452f"],
    dry: ["#6b6058", "#574c42"],
    trunk: "#3a332c",
    canopy: ["#3f362e", "#5a5048"],
    wall: ["#332c26", "#28221d"],
    door: "#4a5058",
    knob: "#8f9298",
    feature: "#5a5048",
    barrier: "#5a5048",
    roof: ["#3f362e", "#332c26"],
    detail: ["#3b5a58", "#4a6b68", "#6f8c88"],
    post: "#6b543a",
    stairs: ["#6b6058", "#3c332c", "#8a7f74"],
  },
};

/** Deterministic noise, so a tile always dithers the same way. */
function noise(x, y, salt = 0) {
  let h = (x * 374761393 + y * 668265263 + salt * 1274126177) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177) >>> 0;
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

function fill(ctx, ox, oy, color) {
  ctx.fillStyle = color;
  ctx.fillRect(ox, oy, TILE, TILE);
}

function speckle(ctx, ox, oy, colors, density = 0.2, salt = 0) {
  for (let y = 0; y < TILE; y += 1) {
    for (let x = 0; x < TILE; x += 1) {
      const n = noise(ox + x, oy + y, salt);
      if (n < density) {
        ctx.fillStyle = colors[1];
        ctx.fillRect(ox + x, oy + y, 1, 1);
      } else if (colors[2] && n > 1 - density * 0.5) {
        ctx.fillStyle = colors[2];
        ctx.fillRect(ox + x, oy + y, 1, 1);
      }
    }
  }
}

const PAINTERS = {
  1: (ctx, ox, oy, P) => { fill(ctx, ox, oy, P.floor[0]); speckle(ctx, ox, oy, P.floor, 0.2, 1); },
  2: (ctx, ox, oy, P) => { fill(ctx, ox, oy, P.path[0]); speckle(ctx, ox, oy, P.path, 0.18, 2); },
  3: (ctx, ox, oy, P) => {
    fill(ctx, ox, oy, P.water[0]);
    ctx.fillStyle = P.water[2];
    for (let y = 2; y < TILE; y += 5) ctx.fillRect(ox + Math.floor(noise(ox, oy + y, 3) * 6), oy + y, 6, 1);
  },
  4: (ctx, ox, oy, P) => {
    fill(ctx, ox, oy, P.planks[0]);
    ctx.fillStyle = P.planks[1];
    for (let y = 3; y < TILE; y += 5) ctx.fillRect(ox, oy + y, TILE, 1);
  },
  5: (ctx, ox, oy, P) => { fill(ctx, ox, oy, P.dry[0]); speckle(ctx, ox, oy, P.dry, 0.15, 5); },

  16: (ctx, ox, oy, P) => { // tree
    ctx.fillStyle = P.trunk;
    ctx.fillRect(ox + 7, oy + 10, 2, 6);
    ctx.fillStyle = P.canopy[0];
    ctx.beginPath(); ctx.arc(ox + 8, oy + 7, 6.5, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = P.canopy[1];
    ctx.beginPath(); ctx.arc(ox + 7, oy + 6, 5, 0, Math.PI * 2); ctx.fill();
  },
  17: (ctx, ox, oy, P) => { // wall
    fill(ctx, ox, oy, P.wall[0]);
    ctx.fillStyle = P.wall[1];
    for (let y = 0; y < TILE; y += 5) {
      ctx.fillRect(ox, oy + y, TILE, 1);
      ctx.fillRect(ox + ((y / 5) % 2 === 0 ? 5 : 11), oy + y, 1, 5);
    }
  },
  18: (ctx, ox, oy, P) => { // door
    fill(ctx, ox, oy, P.wall[1]);
    ctx.fillStyle = P.door;
    ctx.fillRect(ox + 2, oy + 3, 12, 13);
    ctx.fillStyle = P.knob;
    ctx.fillRect(ox + 11, oy + 9, 2, 2);
  },
  19: (ctx, ox, oy, P) => { // well / winch
    ctx.fillStyle = P.feature;
    ctx.beginPath(); ctx.arc(ox + 8, oy + 9, 6, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#141a1f";
    ctx.beginPath(); ctx.arc(ox + 8, oy + 9, 3.5, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = P.post;
    ctx.fillRect(ox + 3, oy + 1, 1, 8);
    ctx.fillRect(ox + 12, oy + 1, 1, 8);
    ctx.fillRect(ox + 3, oy + 1, 10, 1);
  },
  20: (ctx, ox, oy, P) => { // fence
    ctx.fillStyle = P.barrier;
    ctx.fillRect(ox, oy + 7, TILE, 2);
    ctx.fillRect(ox, oy + 12, TILE, 2);
    ctx.fillRect(ox + 3, oy + 4, 2, 11);
    ctx.fillRect(ox + 11, oy + 4, 2, 11);
  },
  21: (ctx, ox, oy, P) => { // roof
    fill(ctx, ox, oy, P.roof[0]);
    ctx.fillStyle = P.roof[1];
    for (let y = 2; y < TILE; y += 4) ctx.fillRect(ox, oy + y, TILE, 1);
  },
  22: (ctx, ox, oy, P) => { // flowers
    for (let i = 0; i < 5; i += 1) {
      ctx.fillStyle = P.detail[i % P.detail.length];
      ctx.fillRect(ox + 2 + Math.floor(noise(ox, oy, i) * 12), oy + 2 + Math.floor(noise(oy, ox, i + 9) * 12), 2, 2);
    }
  },
  23: (ctx, ox, oy, P) => { // signpost
    ctx.fillStyle = P.post;
    ctx.fillRect(ox + 7, oy + 8, 2, 8);
    ctx.fillStyle = P.planks[0];
    ctx.fillRect(ox + 2, oy + 3, 12, 6);
    ctx.fillStyle = P.planks[1];
    ctx.fillRect(ox + 4, oy + 5, 8, 1);
  },
  24: (ctx, ox, oy, P) => stairs(ctx, ox, oy, P, "up"),
  25: (ctx, ox, oy, P) => stairs(ctx, ox, oy, P, "down"),
};

function stairs(ctx, ox, oy, P, direction) {
  fill(ctx, ox, oy, P.stairs[1]);
  for (let i = 0; i < 4; i += 1) {
    const y = oy + 1 + i * 4;
    const inset = direction === "down" ? i : 3 - i;
    ctx.fillStyle = P.stairs[0];
    ctx.fillRect(ox + inset, y, TILE - inset * 2, 3);
    ctx.fillStyle = P.stairs[2];
    ctx.fillRect(ox + inset, y, TILE - inset * 2, 1);
  }
}

/** A straight recolour reads wrong for these, so the mine draws its own. */
const OVERRIDES = {
  interior_wood: {
    floor: ["#8a6a45", "#75593a", "#9c7b52"],
    path: ["#6b5942", "#5a4a36", "#7d6a50"],
    water: ["#3b5a68", "#2f4a56", "#4d6f7d"],
    planks: ["#7a5c3a", "#63482c"],
    dry: ["#c9b489", "#b8a279"],
    trunk: "#5a3f28",
    canopy: ["#63482c", "#7a5c3a"],
    wall: ["#b8a98d", "#9e8f74"],
    door: "#5a3f28",
    knob: "#c9a45e",
    feature: "#7d7468",
    barrier: "#7a5c3a",
    roof: ["#5a4a36", "#4a3c2b"],
    detail: ["#8a7b5c", "#a89878", "#6d6047"],
    post: "#6d5334",
    stairs: ["#8d8478", "#5c554d", "#a9a094"],
  },
  interior_wood: {
    16: (ctx, ox, oy, P) => { // cupboard
      fill(ctx, ox, oy, P.floor[0]);
      ctx.fillStyle = P.canopy[0];
      ctx.fillRect(ox + 1, oy, 14, TILE);
      ctx.fillStyle = P.trunk;
      ctx.fillRect(ox + 1, oy + 5, 14, 1);
      ctx.fillRect(ox + 8, oy, 1, TILE);
      ctx.fillStyle = P.knob;
      ctx.fillRect(ox + 6, oy + 8, 1, 2);
      ctx.fillRect(ox + 10, oy + 8, 1, 2);
    },
    19: (ctx, ox, oy, P) => { // hearth
      fill(ctx, ox, oy, P.feature);
      ctx.fillStyle = "#2b2320";
      ctx.fillRect(ox + 3, oy + 5, 10, 11);
      ctx.fillStyle = "#d4652f";
      ctx.beginPath(); ctx.moveTo(ox + 8, oy + 8); ctx.lineTo(ox + 11, oy + 15);
      ctx.lineTo(ox + 5, oy + 15); ctx.closePath(); ctx.fill();
      ctx.fillStyle = "#f0b44a";
      ctx.fillRect(ox + 7, oy + 12, 2, 3);
    },
    20: (ctx, ox, oy, P) => { // furniture: counters, tables, beds
      fill(ctx, ox, oy, P.floor[0]);
      ctx.fillStyle = P.barrier;
      ctx.fillRect(ox, oy + 3, TILE, 11);
      ctx.fillStyle = P.planks[1];
      ctx.fillRect(ox, oy + 3, TILE, 2);
      ctx.fillRect(ox, oy + 12, TILE, 2);
    },
    23: (ctx, ox, oy, P) => { // shelf
      fill(ctx, ox, oy, P.floor[0]);
      ctx.fillStyle = P.post;
      ctx.fillRect(ox, oy + 4, TILE, 2);
      ctx.fillRect(ox, oy + 11, TILE, 2);
      for (let i = 0; i < 3; i += 1) {
        ctx.fillStyle = P.detail[i % P.detail.length];
        ctx.fillRect(ox + 2 + i * 5, oy + 1, 3, 3);
        ctx.fillRect(ox + 2 + i * 5, oy + 8, 3, 3);
      }
    },
  },
  mine_damp: {
    16: (ctx, ox, oy, P) => { // rock column
      fill(ctx, ox, oy, P.wall[1]);
      ctx.fillStyle = P.canopy[1];
      ctx.beginPath(); ctx.moveTo(ox + 3, oy + 16); ctx.lineTo(ox + 6, oy + 2);
      ctx.lineTo(ox + 11, oy + 2); ctx.lineTo(ox + 14, oy + 16); ctx.closePath(); ctx.fill();
      ctx.fillStyle = P.floor[2];
      ctx.fillRect(ox + 6, oy + 4, 2, 11);
    },
    20: (ctx, ox, oy, P) => { // rubble
      for (let i = 0; i < 7; i += 1) {
        ctx.fillStyle = i % 2 ? P.floor[2] : P.path[1];
        const rx = ox + 1 + Math.floor(noise(ox, oy, i) * 12);
        const ry = oy + 1 + Math.floor(noise(oy, ox, i + 4) * 12);
        ctx.fillRect(rx, ry, 3, 2);
      }
    },
    22: (ctx, ox, oy, P) => { // puddle
      ctx.fillStyle = P.detail[0];
      ctx.beginPath(); ctx.ellipse(ox + 8, oy + 9, 6, 4, 0, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = P.detail[2];
      ctx.fillRect(ox + 5, oy + 7, 4, 1);
    },
    23: (ctx, ox, oy, P) => { // support beam
      ctx.fillStyle = P.post;
      ctx.fillRect(ox + 2, oy, 3, TILE);
      ctx.fillRect(ox + 11, oy, 3, TILE);
      ctx.fillRect(ox, oy + 1, TILE, 3);
    },
  },
};

export function buildTileset(scene, tileset) {
  const key = tilesetKey(tileset);
  if (scene.textures.exists(key)) return key;
  const palette = PALETTES[tileset] ?? PALETTES.overworld_temperate;
  const overrides = OVERRIDES[tileset] ?? {};

  const rows = Math.ceil(TILE_COUNT / COLUMNS);
  const texture = scene.textures.createCanvas(key, COLUMNS * TILE, rows * TILE);
  const ctx = texture.getContext();
  ctx.imageSmoothingEnabled = false;

  for (let index = 0; index < TILE_COUNT; index += 1) {
    const painter = overrides[index] ?? PAINTERS[index];
    if (!painter) continue; // index 0 and unused slots stay transparent
    painter(ctx, (index % COLUMNS) * TILE, Math.floor(index / COLUMNS) * TILE, palette);
  }
  texture.refresh();
  return key;
}

export const KNOWN_TILESETS = Object.keys(PALETTES);

// --- characters ----------------------------------------------------------

const CHARACTER_W = 16;
const CHARACTER_H = 24;
export const DIRECTIONS = ["down", "left", "right", "up"];

const CHARACTERS = {
  sprite_elder:    { skin: "#e0b48c", hair: "#d8d5cf", tunic: "#6b6f9c", trim: "#43466b", legs: "#3b3a44" },
  sprite_smith:    { skin: "#c98f5f", hair: "#3a2a1c", tunic: "#8a4a32", trim: "#5e3122", legs: "#3b3a44" },
  sprite_villager: { skin: "#e6bb92", hair: "#6b4726", tunic: "#5d8a53", trim: "#3f6438", legs: "#4a4230" },
  sprite_merchant: { skin: "#dfb086", hair: "#4a3524", tunic: "#a8823c", trim: "#7a5e2a", legs: "#3b3a44" },
  sprite_miner:    { skin: "#c98f5f", hair: "#2e2620", tunic: "#5f6670", trim: "#414750", legs: "#33383f" },
  sprite_generic:  { skin: "#d9a97f", hair: "#4a3a2c", tunic: "#7a7a86", trim: "#55555f", legs: "#3b3a44" },
  sprite_player:   { skin: "#f0c69b", hair: "#c46a3a", tunic: "#3f7fa8", trim: "#2b5a7a", legs: "#3b3a44" },
};

function drawCharacter(ctx, ox, oy, direction, palette) {
  const cx = ox + 8;
  ctx.fillStyle = "rgba(0,0,0,0.25)";
  ctx.beginPath(); ctx.ellipse(cx, oy + 22, 5, 2, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = palette.legs;
  ctx.fillRect(ox + 5, oy + 18, 3, 4);
  ctx.fillRect(ox + 9, oy + 18, 3, 4);
  ctx.fillStyle = palette.tunic;
  ctx.fillRect(ox + 4, oy + 11, 8, 8);
  ctx.fillStyle = palette.trim;
  ctx.fillRect(ox + 4, oy + 17, 8, 1);
  ctx.fillStyle = palette.skin;
  ctx.fillRect(ox + 3, oy + 12, 2, 5);
  ctx.fillRect(ox + 11, oy + 12, 2, 5);
  ctx.fillRect(ox + 4, oy + 4, 8, 7);
  ctx.fillStyle = palette.hair;
  ctx.fillRect(ox + 3, oy + 2, 10, 3);
  if (direction === "up") {
    ctx.fillRect(ox + 3, oy + 2, 10, 7);
  } else {
    ctx.fillRect(ox + 3, oy + 2, 2, 5);
    ctx.fillRect(ox + 11, oy + 2, 2, 5);
    ctx.fillStyle = "#2b2b33";
    if (direction === "down") { ctx.fillRect(ox + 6, oy + 7, 1, 2); ctx.fillRect(ox + 9, oy + 7, 1, 2); }
    else if (direction === "left") ctx.fillRect(ox + 5, oy + 7, 1, 2);
    else ctx.fillRect(ox + 10, oy + 7, 1, 2);
  }
}

function drawChest(ctx, ox, oy) {
  ctx.fillStyle = "rgba(0,0,0,0.25)";
  ctx.beginPath(); ctx.ellipse(ox + 8, oy + 22, 6, 2, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#7a5230"; ctx.fillRect(ox + 2, oy + 12, 12, 9);
  ctx.fillStyle = "#8f6238"; ctx.fillRect(ox + 2, oy + 8, 12, 5);
  ctx.fillStyle = "#d0a94f"; ctx.fillRect(ox + 2, oy + 12, 12, 1); ctx.fillRect(ox + 7, oy + 13, 2, 4);
  ctx.strokeStyle = "#4a3018"; ctx.strokeRect(ox + 2.5, oy + 8.5, 11, 12);
}

function drawSign(ctx, ox, oy) {
  ctx.fillStyle = "rgba(0,0,0,0.25)";
  ctx.beginPath(); ctx.ellipse(ox + 8, oy + 22, 4, 2, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#4a3524"; ctx.fillRect(ox + 7, oy + 13, 2, 8);
  ctx.fillStyle = "#8a6a45"; ctx.fillRect(ox + 2, oy + 6, 12, 8);
  ctx.fillStyle = "#6d5334"; ctx.fillRect(ox + 4, oy + 9, 8, 1); ctx.fillRect(ox + 4, oy + 11, 6, 1);
}

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



// --- enemies -------------------------------------------------------------
//
// Bigger than overworld characters (32x32) because a battle shows three of them
// at a time and they need to read at a glance. Same tag-resolution rules as
// everything else: assetPack.js picks the key, this draws it.

const ENEMY_SIZE = 32;

const ENEMY_PAINTERS = {
  enemy_rat: (ctx, o) => {
    ctx.fillStyle = "rgba(0,0,0,0.28)";
    ctx.beginPath(); ctx.ellipse(o + 16, 29, 11, 3, 0, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#6b6058";
    ctx.beginPath(); ctx.ellipse(o + 15, 21, 11, 7, 0, 0, Math.PI * 2); ctx.fill();
    ctx.beginPath(); ctx.arc(o + 24, 17, 6, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#8a7f74";
    ctx.beginPath(); ctx.moveTo(o + 22, 12); ctx.lineTo(o + 25, 5); ctx.lineTo(o + 28, 13); ctx.fill();
    ctx.strokeStyle = "#6b6058"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(o + 5, 22); ctx.quadraticCurveTo(o - 2, 16, o + 3, 10); ctx.stroke();
    ctx.fillStyle = "#d4543f";
    ctx.fillRect(o + 26, 15, 2, 2);
  },
  enemy_bat: (ctx, o) => {
    ctx.fillStyle = "rgba(0,0,0,0.28)";
    ctx.beginPath(); ctx.ellipse(o + 16, 30, 8, 2, 0, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#4a4258";
    ctx.beginPath(); ctx.moveTo(o + 16, 14); ctx.lineTo(o + 2, 8); ctx.lineTo(o + 5, 20); ctx.fill();
    ctx.beginPath(); ctx.moveTo(o + 16, 14); ctx.lineTo(o + 30, 8); ctx.lineTo(o + 27, 20); ctx.fill();
    ctx.fillStyle = "#5f5674";
    ctx.beginPath(); ctx.ellipse(o + 16, 16, 6, 7, 0, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#4a4258";
    ctx.beginPath(); ctx.moveTo(o + 12, 10); ctx.lineTo(o + 13, 4); ctx.lineTo(o + 16, 10); ctx.fill();
    ctx.beginPath(); ctx.moveTo(o + 20, 10); ctx.lineTo(o + 19, 4); ctx.lineTo(o + 16, 10); ctx.fill();
    ctx.fillStyle = "#ffd98a";
    ctx.fillRect(o + 13, 15, 2, 2); ctx.fillRect(o + 18, 15, 2, 2);
  },
  enemy_wight: (ctx, o) => {
    ctx.fillStyle = "rgba(0,0,0,0.28)";
    ctx.beginPath(); ctx.ellipse(o + 16, 30, 10, 3, 0, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#3d4a4a";
    ctx.fillRect(o + 9, 13, 14, 16);
    ctx.fillStyle = "#546363";
    ctx.fillRect(o + 6, 15, 3, 11); ctx.fillRect(o + 23, 15, 3, 11);
    ctx.fillStyle = "#b9c6bd";
    ctx.beginPath(); ctx.ellipse(o + 16, 9, 6, 7, 0, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#101819";
    ctx.fillRect(o + 12, 8, 3, 4); ctx.fillRect(o + 17, 8, 3, 4);
    ctx.fillStyle = "#3d8f8a";
    ctx.fillRect(o + 12, 9, 3, 2); ctx.fillRect(o + 17, 9, 3, 2);
    ctx.fillStyle = "#2b3535";
    for (let i = 0; i < 4; i += 1) ctx.fillRect(o + 10 + i * 4, 20 + (i % 2), 2, 6);
  },
};

export function buildEnemies(scene) {
  for (const [key, painter] of Object.entries(ENEMY_PAINTERS)) {
    if (scene.textures.exists(key)) continue;
    const texture = scene.textures.createCanvas(key, ENEMY_SIZE, ENEMY_SIZE);
    const ctx = texture.getContext();
    ctx.imageSmoothingEnabled = false;
    painter(ctx, 0);
    texture.refresh();
  }
}


export function buildAll(scene) {
  for (const tileset of KNOWN_TILESETS) buildTileset(scene, tileset);
  buildCharacters(scene);
  buildEnemies(scene);
}
