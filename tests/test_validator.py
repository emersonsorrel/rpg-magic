"""M0 acceptance: the hand-written package validates, and every deliberately
broken variant fails with its specific code."""

from __future__ import annotations

import json
import pathlib

import pytest

from backend.validation.errors import Severity
from backend.validation.schema import validator_for
from backend.validation.validator import (
    MAX_NESTING_DEPTH,
    MAX_TEXT,
    OP_PARAMS,
    iter_commands,
    validate_ledger,
    validate_zone_package,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
BROKEN = FIXTURES / "broken"

EXPECTED = json.loads((BROKEN / "expected.json").read_text())


@pytest.fixture(scope="session")
def ledger():
    return json.loads((FIXTURES / "ledger_new_game.json").read_text())


@pytest.fixture(scope="session")
def town():
    return json.loads((FIXTURES / "zone_town_01.json").read_text())


# --- the M0 done-when ------------------------------------------------------

def test_hand_written_package_validates(town, ledger):
    report = validate_zone_package(town, ledger)
    assert report.ok, str(report)


def test_hand_written_package_is_warning_free(town, ledger):
    report = validate_zone_package(town, ledger)
    assert report.warnings == [], str(report)


def test_ledger_validates(ledger):
    report = validate_ledger(ledger)
    assert report.ok, str(report)


# --- the broken library ----------------------------------------------------

@pytest.mark.parametrize("filename", sorted(EXPECTED))
def test_broken_fixture_is_rejected(filename, ledger):
    report = validate_zone_package(json.loads((BROKEN / filename).read_text()), ledger)
    assert not report.ok, f"{filename} was accepted:\n{report}"


@pytest.mark.parametrize("filename", sorted(EXPECTED))
def test_broken_fixture_reports_its_specific_code(filename, ledger):
    report = validate_zone_package(json.loads((BROKEN / filename).read_text()), ledger)
    want = set(EXPECTED[filename]["expect_error_codes"])
    missing = want - report.error_codes()
    assert not missing, f"{filename} did not report {sorted(missing)}:\n{report}"


def test_broken_library_covers_distinct_failures():
    """Each fixture should be pulling its weight -- no two identical code sets."""
    signatures = [tuple(sorted(s["expect_error_codes"])) for s in EXPECTED.values()]
    assert len(signatures) == len(set(signatures))


# --- the contract holds together ------------------------------------------

def test_op_table_matches_schema_enum():
    """The semantic pass and the schema must agree on the command palette."""
    schema = validator_for("event_command").schema
    assert set(schema["properties"]["op"]["enum"]) == set(OP_PARAMS)


def test_text_cap_matches_schema():
    schema = validator_for("event_command").schema
    assert schema["$defs"]["dialogue"]["maxLength"] == MAX_TEXT


def test_iter_commands_reports_depth():
    script = [
        {"op": "IF_FLAG", "flag": "f", "then": [
            {"op": "SHOW_CHOICE", "prompt": "p", "options": [
                {"label": "a", "script": [{"op": "END"}]},
                {"label": "b", "script": [{"op": "END"}]},
            ]}
        ]}
    ]
    depths = {cmd["op"]: depth for cmd, _path, depth in iter_commands(script, "$")}
    assert depths == {"IF_FLAG": 1, "SHOW_CHOICE": 2, "END": 3}
    assert max(depths.values()) == MAX_NESTING_DEPTH


def test_command_schema_rejects_unknown_parameter():
    validator = validator_for("event_command")
    assert validator.is_valid({"op": "WAIT", "frames": 30})
    assert not validator.is_valid({"op": "WAIT", "frames": 30, "easing": "linear"})


def test_command_schema_rejects_wrong_params_for_op():
    validator = validator_for("event_command")
    assert not validator.is_valid({"op": "GIVE_ITEM", "item_id": "potion"})  # no qty
    assert not validator.is_valid({"op": "SET_FLAG", "flag": "f", "value": "yes"})  # not bool


def test_unknown_sprite_tag_warns_but_does_not_block(town, ledger):
    """Design doc 3.4: a missing asset must never block a commit."""
    town = json.loads(json.dumps(town))
    town["entities"][0]["sprite_tags"].append("wearing_a_tiny_hat")
    report = validate_zone_package(town, ledger)
    assert report.ok, str(report)
    assert any(i.severity is Severity.WARNING for i in report.issues)


def test_proposals_are_inert(town, ledger):
    """4.5: a proposal must never become mechanically live on its own."""
    town = json.loads(json.dumps(town))
    town["proposals"].append(
        {"kind": "key_item", "name": "Third Totem", "summary": "There should be a shrine needing three totems."}
    )
    report = validate_zone_package(town, ledger)
    assert report.ok, str(report)
    assert not any("totem" in str(o).lower() for o in town["fulfills_obligations"])
