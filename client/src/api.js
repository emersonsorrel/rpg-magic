/**
 * Talks to the authoring backend (design doc 2). The client asks for a zone;
 * whether that zone already existed or was generated on the spot is the
 * backend's business, not the client's.
 *
 * Everything is gated through the shared schemas on the way in -- the client
 * renders nothing it has not validated.
 */

import { gateLedger, gateZonePackage } from "./game/zoneLoader.js";

const BASE = "/api";

export class ZoneRejectedError extends Error {
  constructor(body) {
    const issues = (body.issues ?? []).map((i) => `  [${i.code}] ${i.path} ${i.message}`).join("\n");
    super(`backend refused to commit ${body.zone_id}:\n${issues}`);
    this.name = "ZoneRejectedError";
    this.issues = body.issues ?? [];
  }
}

async function request(path, options) {
  const response = await fetch(BASE + path, options);
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    if (body?.error === "zone_rejected") throw new ZoneRejectedError(body);
    throw new Error(`${path}: ${response.status} ${body?.detail ?? response.statusText}`);
  }
  return body;
}

export const getWorld = () => request("/world").then((l) => gateLedger(l, "/api/world"));

export const getZone = (zoneId) =>
  request(`/zone/${zoneId}`).then((p) => gateZonePackage(p, `/api/zone/${zoneId}`));

export const newGame = (seed) =>
  request(`/new-game?seed=${encodeURIComponent(seed)}`, { method: "POST" }).then((l) =>
    gateLedger(l, "/api/new-game")
  );

export const savePosition = (zone, x, y) =>
  request(`/world/position?zone=${encodeURIComponent(zone)}&x=${x}&y=${y}`, { method: "POST" });
