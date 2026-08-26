/**
 * Compile the shared JSON Schemas into a standalone ES module.
 *
 * Design doc 8: "the schema is the contract between three parties (backend,
 * client and model) -- it should exist in exactly one place." The Python side
 * validates against /schemas at runtime; the client can't parse JSON Schema
 * without shipping a validator, so it precompiles the same files to plain JS
 * here. Ajv is a build-time dependency only -- the generated module imports
 * nothing, which is what lets the client run with no bundler.
 *
 *     npm run build:validator
 *
 * Re-run whenever anything in /schemas changes.
 */

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const Ajv = require("ajv/dist/2020.js");
const standaloneCode = require("ajv/dist/standalone/index.js");
const ajvVersion = require("ajv/package.json").version;

const AjvClass = Ajv.default ?? Ajv;
const generate = standaloneCode.default ?? standaloneCode;

const clientDir = path.resolve(import.meta.dirname, "..");
const schemaDir = path.join(clientDir, "..", "schemas");
const outFile = path.join(clientDir, "src", "game", "generated", "validators.js");

/**
 * Ajv's standalone output reaches for two runtime helpers via require(), which
 * an ES module cannot do. They are small and stable, so they are inlined here
 * verbatim from ajv/dist/runtime/ucs2length.js and fast-deep-equal (which
 * ajv/dist/runtime/equal.js re-exports).
 *
 * If Ajv ever needs a helper that is not in this table the build fails loudly
 * rather than emitting a module that throws on import.
 */
const INLINED_HELPERS = {
  'require("ajv/dist/runtime/ucs2length").default': "__ucs2length",
  'require("ajv/dist/runtime/equal").default': "__equal",
};

const HELPER_PRELUDE = `
// --- inlined Ajv runtime helpers (Ajv ${ajvVersion}) ---------------------------
// Counts UTF-16 code points, so a surrogate pair costs one character.
function __ucs2length(str) {
  const len = str.length;
  let length = 0;
  let pos = 0;
  let value;
  while (pos < len) {
    length++;
    value = str.charCodeAt(pos++);
    if (value >= 0xd800 && value <= 0xdbff && pos < len) {
      value = str.charCodeAt(pos);
      if ((value & 0xfc00) === 0xdc00) pos++;
    }
  }
  return length;
}

function __equal(a, b) {
  if (a === b) return true;
  if (a && b && typeof a == "object" && typeof b == "object") {
    if (a.constructor !== b.constructor) return false;
    let length, i, keys;
    if (Array.isArray(a)) {
      length = a.length;
      if (length != b.length) return false;
      for (i = length; i-- !== 0; ) if (!__equal(a[i], b[i])) return false;
      return true;
    }
    if (a.constructor === RegExp) return a.source === b.source && a.flags === b.flags;
    if (a.valueOf !== Object.prototype.valueOf) return a.valueOf() === b.valueOf();
    if (a.toString !== Object.prototype.toString) return a.toString() === b.toString();
    keys = Object.keys(a);
    length = keys.length;
    if (length !== Object.keys(b).length) return false;
    for (i = length; i-- !== 0; )
      if (!Object.prototype.hasOwnProperty.call(b, keys[i])) return false;
    for (i = length; i-- !== 0; ) {
      const key = keys[i];
      if (!__equal(a[key], b[key])) return false;
    }
    return true;
  }
  return a !== a && b !== b;
}
`;

const SCHEMA_FILES = [
  "event_command.schema.json",
  "zone_package.schema.json",
  "ledger.schema.json",
];

/** Fingerprint of the inputs, stamped into the output so a stale build is a
 *  test failure rather than a puzzling runtime rejection. */
export function schemaHash(dir = schemaDir) {
  const hash = crypto.createHash("sha256");
  for (const name of SCHEMA_FILES) hash.update(fs.readFileSync(path.join(dir, name)));
  return hash.digest("hex").slice(0, 16);
}

const load = (name) => JSON.parse(fs.readFileSync(path.join(schemaDir, name), "utf8"));

export function build() {
  const eventCommand = load("event_command.schema.json");
  const zonePackage = load("zone_package.schema.json");
  const ledger = load("ledger.schema.json");

  const ajv = new AjvClass({
    code: { source: true, esm: true },
    strict: false,
    allErrors: true,
  });
  ajv.addSchema(eventCommand);
  ajv.addSchema(zonePackage);
  ajv.addSchema(ledger);

  let code = generate(ajv, {
    validateZonePackage: zonePackage.$id,
    validateLedger: ledger.$id,
    validateEventCommand: eventCommand.$id,
  });

  for (const [call, replacement] of Object.entries(INLINED_HELPERS)) {
    code = code.split(call).join(replacement);
  }

  const leftover = code.match(/require\([^)]*\)/g);
  if (leftover) {
    console.error(
      `Ajv ${ajvVersion} emitted runtime helpers this build does not inline:\n` +
        [...new Set(leftover)].map((r) => `  ${r}`).join("\n") +
        "\nAdd them to INLINED_HELPERS in tools/build-validator.js."
    );
    process.exit(1);
  }

  // "use strict" is implicit in a module, and leaving it first would push the
  // helper prelude below the export that uses it.
  code = code.replace(/^"use strict";/, "");

  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  fs.writeFileSync(
    outFile,
    "// GENERATED FILE -- do not edit.\n" +
      `// Built from /schemas by client/tools/build-validator.js (Ajv ${ajvVersion}).\n` +
      "// Regenerate with: npm run build:validator\n" +
      `// schema-hash: ${schemaHash()}\n` +
      HELPER_PRELUDE +
      code +
      "\n"
  );

  console.log(
    `wrote ${path.relative(clientDir, outFile)} ` +
      `(${(fs.statSync(outFile).size / 1024).toFixed(1)} KB, no imports)`
  );
}


// Only build when run directly. Importing this module (the staleness test does)
// must not regenerate the very file that test is checking.
if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) build();
