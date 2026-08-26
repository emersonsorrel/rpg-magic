/**
 * The client's front door for anything the backend hands it.
 *
 * The backend's semantic validator is the real commit gate -- reachability,
 * obligations, referential integrity. This refuses anything structurally
 * wrong, plus the one check a JSON Schema cannot express: that each layer is
 * exactly width*height long. A torn map is a miserable way to find out.
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

export function gateZonePackage(pkg, source = "zone package") {
  if (!validateZonePackage(pkg)) throw new ZoneValidationError(source, validateZonePackage.errors);

  const expected = pkg.width * pkg.height;
  for (const [name, layer] of Object.entries(pkg.layers)) {
    if (layer.length !== expected) {
      throw new ZoneValidationError(source, [
        { instancePath: `/layers/${name}`, message: `has ${layer.length} tiles, expected ${expected}` },
      ]);
    }
  }
  return pkg;
}

export function gateLedger(ledger, source = "ledger") {
  if (!validateLedger(ledger)) throw new ZoneValidationError(source, validateLedger.errors);
  return ledger;
}
