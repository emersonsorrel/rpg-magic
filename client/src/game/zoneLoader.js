/**
 * Fetch and gate a Zone Package before the client will render it.
 *
 * The backend's semantic validator is the real commit gate (reachability,
 * obligations, referential integrity). This is the client's own front door:
 * it refuses anything structurally wrong, plus the one check a JSON Schema
 * cannot express -- that each layer is exactly width*height long. A torn map
 * is a miserable way to find out.
 */

import { validateLedger, validateZonePackage } from "./generated/validators.js";

export class ZoneValidationError extends Error {
  constructor(source, errors) {
    const detail = (errors ?? [])
      .slice(0, 5)
      .map((e) => `  ${e.instancePath || "$"} ${e.message}`)
      .join("\n");
    super(`${source} failed schema validation:\n${detail}`);
    this.name = "ZoneValidationError";
    this.errors = errors;
  }
}

async function loadJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status} ${response.statusText}`);
  return response.json();
}

export async function loadZonePackage(url) {
  const pkg = await loadJson(url);
  if (!validateZonePackage(pkg)) throw new ZoneValidationError(url, validateZonePackage.errors);

  const expected = pkg.width * pkg.height;
  for (const [name, layer] of Object.entries(pkg.layers)) {
    if (layer.length !== expected) {
      throw new ZoneValidationError(url, [
        {
          instancePath: `/layers/${name}`,
          message: `has ${layer.length} tiles, expected width*height = ${expected}`,
        },
      ]);
    }
  }
  return pkg;
}

export async function loadLedger(url) {
  const ledger = await loadJson(url);
  if (!validateLedger(ledger)) throw new ZoneValidationError(url, validateLedger.errors);
  return ledger;
}
