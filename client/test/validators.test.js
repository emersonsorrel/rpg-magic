/**
 * The generated client validator must agree with the Python one about *shape*.
 *
 * It deliberately does not agree about meaning: referential integrity,
 * reachability and obligations are semantic checks that live in
 * backend/validation/validator.py and gate the commit. The client's job is to
 * refuse a package that is structurally wrong, which is all a schema can say.
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  validateEventCommand,
  validateLedger,
  validateZonePackage,
} from "../src/game/generated/validators.js";

import ledgerFixture from "../../fixtures/ledger_new_game.json" with { type: "json" };
import townFixture from "../../fixtures/zone_town_01.json" with { type: "json" };
import unknownOp from "../../fixtures/broken/01_unknown_op.json" with { type: "json" };
import textTooLong from "../../fixtures/broken/09_text_too_long.json" with { type: "json" };
import layerMismatch from "../../fixtures/broken/07_layer_size_mismatch.json" with { type: "json" };

describe("generated schema validators", () => {
  it("accepts the hand-authored town", () => {
    assert.ok(validateZonePackage(townFixture), JSON.stringify(validateZonePackage.errors, null, 2));
  });

  it("accepts the ledger", () => {
    assert.ok(validateLedger(ledgerFixture), JSON.stringify(validateLedger.errors, null, 2));
  });

  it("rejects an op outside the vocabulary", () => {
    assert.equal(validateZonePackage(unknownOp), false);
  });

  it("rejects dialogue past the box cap", () => {
    assert.equal(validateZonePackage(textTooLong), false);
  });

  it("does NOT catch a short layer -- that is a semantic check, by design", () => {
    // width*height is not expressible in JSON Schema. The Python validator
    // catches this one; the client would render a torn map. Documented, not a bug.
    assert.equal(validateZonePackage(layerMismatch), true);
  });
});

describe("event command vocabulary", () => {
  it("accepts every op the fixture uses", () => {
    for (const entity of townFixture.entities) {
      for (const command of entity.script ?? []) {
        assert.ok(validateEventCommand(command), `${entity.id}: ${JSON.stringify(command)}`);
      }
    }
  });

  it("rejects a stray parameter", () => {
    assert.ok(validateEventCommand({ op: "WAIT", frames: 30 }));
    assert.equal(validateEventCommand({ op: "WAIT", frames: 30, easing: "linear" }), false);
  });

  it("rejects params belonging to a different op", () => {
    assert.equal(validateEventCommand({ op: "GIVE_ITEM", item_id: "potion" }), false);
    assert.equal(validateEventCommand({ op: "SET_FLAG", flag: "f", value: "yes" }), false);
  });
});
