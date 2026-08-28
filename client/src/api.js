/**
 * Talks to the authoring backend (design doc 2). The client asks for a zone;
 * whether that zone already existed or was generated on the spot is the
 * backend's business, not the client's.
 *
 * Everything is gated through the shared schemas on the way in -- the client
 * renders nothing it has not validated.
 */

import { gateLedger, gateZonePackage, loadValidators } from "./game/zoneLoader.js";

const BASE = "/api";

export class ZoneRejectedError extends Error {
  constructor(body) {
    const issues = (body.issues ?? []).map((i) => `  [${i.code}] ${i.path} ${i.message}`).join("\n");
    super(`backend refused to commit ${body.zone_id}:\n${issues}`);
    this.name = "ZoneRejectedError";
    this.issues = body.issues ?? [];
  }
}

export class WorldUnloadableError extends Error {
  constructor(detail) {
    super(detail.message ?? "the stored world could not be loaded");
    this.name = "WorldUnloadableError";
    this.headline = "This world's save is damaged";
    this.lead = detail.message ?? "";
    this.detail = (detail.issues ?? [])
      .map((issue) => `[${issue.code}] ${issue.path} ${issue.message}`)
      .join("\n");
  }
}

async function request(path, options) {
  const response = await fetch(BASE + path, options);
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    if (body?.error === "zone_rejected") throw new ZoneRejectedError(body);
    if (body?.detail?.error === "world_unloadable") throw new WorldUnloadableError(body.detail);
    const detail = typeof body?.detail === "string" ? body.detail : response.statusText;
    throw new Error(`${path}: ${response.status} ${detail}`);
  }
  return body;
}

/** Load the validator build matching the schemas the backend is serving.
 *  Must run before any gate. */
export async function ready() {
  const { schema_hash } = await request("/schema-version");
  await loadValidators(schema_hash);
  return schema_hash;
}

export const getWorld = () => request("/world").then((l) => gateLedger(l, "/api/world"));

export const getZone = (zoneId) =>
  request(`/zone/${zoneId}`).then((p) => gateZonePackage(p, `/api/zone/${zoneId}`));

/** Items, skills and the bestiary. Backend-owned so there is one definition of
 *  what a Potion does; fetched once at boot. */
export const getRegistries = () => request("/registries");

/** Whether authoring is on and who is doing it. Surfaced in the shell so a
 *  silently-disabled model is never mistaken for a broken one. */
export const getStatus = () => request("/status");

/** Persist player progress — the only part of a committed world ever rewritten. */
export const saveState = (state) =>
  request("/world/state", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state),
  });

export const listSaves = () => request("/saves").then((r) => r.saves);

export const saveSlot = (name) =>
  request(`/saves/${encodeURIComponent(name)}`, { method: "POST" });

export const loadSlot = (name) =>
  request(`/saves/${encodeURIComponent(name)}/load`, { method: "POST" });

export const newGame = (seed) =>
  request(`/new-game?seed=${encodeURIComponent(seed)}`, { method: "POST" }).then((l) =>
    gateLedger(l, "/api/new-game")
  );

export const savePosition = (zone, x, y) =>
  request(`/world/position?zone=${encodeURIComponent(zone)}&x=${x}&y=${y}`, { method: "POST" });
