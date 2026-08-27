/**
 * The client's front door for anything the backend hands it.
 *
 * The backend's semantic validator is the real commit gate -- reachability,
 * obligations, referential integrity. This refuses anything structurally
 * wrong, plus the one check a JSON Schema cannot express: that each layer is
 * exactly width*height long. A torn map is a miserable way to find out.
 */

/**
 * The generated validator is build output, regenerated whenever a schema
 * changes, and a browser that has cached an older copy rejects documents that
 * are perfectly valid — reported as a backend failure, which is a thoroughly
 * misleading place to start looking. So it is loaded by content: the backend
 * reports the fingerprint of the schemas it is actually serving, and the client
 * asks for that exact build.
 */
let validators = null;

export async function loadValidators(version) {
  if (validators) return validators;
  const url = new URL("./generated/validators.js", import.meta.url);
  if (version) url.search = `v=${version}`;
  validators = await import(url.href);
  return validators;
}

function ready() {
  if (!validators) {
    throw new Error("loadValidators() must run before anything is validated");
  }
  return validators;
}

export class ZoneValidationError extends Error {
  constructor(source, errors) {
    const detail = (errors ?? [])
      .slice(0, 5)
      .map((e) => `  ${e.instancePath || "$"} ${e.message}`)
      .join("\n");
    super(`${source} failed schema validation:\n${detail}`);
    this.name = "ZoneValidationError";
    this.errors = errors;
    // Read by the recovery screen, so a schema dump is not the first thing a
    // player sees when a roll goes wrong.
    this.headline = "This world did not come out valid";
    this.lead = "Something the generator produced does not match the schema. Rolling again usually fixes it.";
    this.detail = `${source}\n${detail}`;
  }
}

export function gateZonePackage(pkg, source = "zone package") {
  const { validateZonePackage } = ready();
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
  const { validateLedger } = ready();
  if (!validateLedger(ledger)) throw new ZoneValidationError(source, validateLedger.errors);
  return ledger;
}
