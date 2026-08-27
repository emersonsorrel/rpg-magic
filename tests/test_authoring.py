"""M3: the authoring layer.

Design doc 10: "mock the provider in all tests except a small, manually-run live
suite." Nothing here touches the network.
"""

from __future__ import annotations

import asyncio
import copy
import json
import pathlib

import pytest

from backend.llm.author import (
    Authored, apply_outline, author_zone, normalize_script, planned_placement, slugify,
)
from backend.llm.provider import LLMError, RecordingProvider, coerce_json, verify_against_schema
from backend.packaging.assemble import slot_ids
from backend.procgen.town import generate as generate_town
from backend.world import new_game

ROOT = pathlib.Path(__file__).resolve().parents[1]
SEED = 8471029
ZONE = "zone_town_01"


@pytest.fixture
def ledger():
    return new_game.create(SEED)


@pytest.fixture
def layout(ledger):
    zone = ledger["zones"][ZONE]
    kinds = {z: v["kind"] for z, v in ledger["zones"].items()}
    return generate_town(SEED, ZONE, zone["exits"], kinds)


def fill_for(layout, **overrides):
    """A minimal well-formed response covering every slot."""
    fills = []
    for slot_id in slot_ids(layout):
        fills.append({
            "slot_id": slot_id,
            "display_name": "Someone",
            "sprite_tags": ["human", "adult"],
            "script": [{"op": "SHOW_TEXT", "speaker": "Someone", "text": "The river runs warm."}],
        })
    response = {
        "summary": "A river town where the mine has flooded and nobody says so directly.",
        "fills": fills,
        "declares_flags": [],
        "proposals": [],
    }
    response.update(overrides)
    return response


def run(coro):
    return asyncio.run(coro)


# --- strict-mode artefacts -------------------------------------------------

class TestNormalize:
    def test_empty_speaker_becomes_null(self):
        out = normalize_script([{"op": "SHOW_TEXT", "speaker": "", "text": "hi"}])
        assert out[0]["speaker"] is None

    def test_whitespace_speaker_becomes_null(self):
        out = normalize_script([{"op": "SHOW_TEXT", "speaker": "   ", "text": "hi"}])
        assert out[0]["speaker"] is None

    def test_real_speaker_survives(self):
        out = normalize_script([{"op": "SHOW_TEXT", "speaker": "Dorn", "text": "hi"}])
        assert out[0]["speaker"] == "Dorn"

    def test_empty_else_is_dropped(self):
        out = normalize_script([
            {"op": "IF_FLAG", "flag": "f", "then": [{"op": "SHOW_TEXT", "speaker": "", "text": "x"}], "else": []}
        ])
        assert "else" not in out[0]

    def test_empty_option_script_gets_a_terminator(self):
        out = normalize_script([{
            "op": "SHOW_CHOICE", "speaker": "", "prompt": "?",
            "options": [{"label": "a", "script": []}, {"label": "b", "script": []}],
        }])
        assert all(o["script"] == [{"op": "END"}] for o in out[0]["options"])

    def test_recurses_into_branches(self):
        out = normalize_script([{
            "op": "IF_FLAG", "flag": "f",
            "then": [{"op": "SHOW_TEXT", "speaker": "", "text": "deep"}],
        }])
        assert out[0]["then"][0]["speaker"] is None


# --- provider hardening ----------------------------------------------------

class TestProviderTrust:
    def test_strips_a_markdown_fence(self):
        assert coerce_json('```json\n{"a": 1}\n```', "t") == {"a": 1}

    def test_rejects_non_json(self):
        with pytest.raises(LLMError):
            coerce_json("I'm afraid I can't do that", "t")

    def test_rejects_a_json_array(self):
        with pytest.raises(LLMError):
            coerce_json("[1, 2]", "t")

    def test_catches_a_response_that_ignored_the_schema(self):
        schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}
        with pytest.raises(LLMError, match="ignored the schema"):
            verify_against_schema({"a": "not an int"}, schema, "t")

    def test_passes_a_conforming_response(self):
        schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}
        verify_against_schema({"a": 1}, schema, "t")


# --- outline ---------------------------------------------------------------

OUTLINE = {
    "tone": "melancholy pastoral fantasy",
    "premise": "The mine flooded and the water came back warm.",
    "antagonist": {"name": "The Kindled Deep", "motive": "It is cold and reaching for heat."},
    "beats": [
        {"id": "b1", "summary": "Arrive in the town.", "zone_hint": "town"},
        {"id": "b2", "summary": "Descend the workings.", "zone_hint": "mine"},
        {"id": "b3", "summary": "Open the deep door.", "zone_hint": "deep"},
    ],
    "obligations": [{"kind": "key_item", "name": "Ember Sigil", "gates_beat": "b3"}],
    "party_seed": [
        {"name": "Wren", "role": "blade", "voice": "clipped"},
        {"name": "Sabel", "role": "spark", "voice": "wry"},
    ],
}


class TestOutline:
    def test_writes_tone_and_beats(self, ledger):
        apply_outline(ledger, OUTLINE, list(ledger["zones"]))
        assert ledger["outline"]["tone"] == "melancholy pastoral fantasy"
        assert [b["id"] for b in ledger["outline"]["beats"]] == ["b1", "b2", "b3"]

    def test_first_beat_is_active_and_the_rest_pending(self, ledger):
        apply_outline(ledger, OUTLINE, list(ledger["zones"]))
        statuses = [b["status"] for b in ledger["outline"]["beats"]]
        assert statuses == ["active", "pending", "pending"]

    def test_turns_a_named_item_into_a_real_obligation(self, ledger):
        order = list(ledger["zones"])
        apply_outline(ledger, OUTLINE, order)
        obligation = ledger["obligations"][0]
        assert obligation["item_id"] == "ember_sigil"
        assert obligation["status"] == "open"
        assert obligation["placed_in"] is None
        # b3 is the third beat, so the door is in the third zone.
        assert obligation["required_by"] == order[2]

    def test_registers_the_item_so_references_resolve(self, ledger):
        apply_outline(ledger, OUTLINE, list(ledger["zones"]))
        assert [i["id"] for i in ledger["defined_items"]] == ["ember_sigil"]

    def test_renames_the_party(self, ledger):
        apply_outline(ledger, OUTLINE, list(ledger["zones"]))
        assert [m["name"] for m in ledger["party"]] == ["Wren", "Sabel"]

    def test_the_key_is_placed_before_the_door(self, ledger):
        """The whole point of the mechanism: never in or after the zone that
        needs it."""
        order = list(ledger["zones"])
        apply_outline(ledger, OUTLINE, order)
        obligation = ledger["obligations"][0]
        placement = planned_placement(ledger, obligation, order)
        assert order.index(placement) < order.index(obligation["required_by"])

    def test_slugify_makes_a_legal_identifier(self):
        assert slugify("Foreman's Silver Talisman") == "foreman_s_silver_talisman"
        assert slugify("!!!") == "item"


# --- the authoring ladder --------------------------------------------------

class TestAuthorZone:
    def test_a_good_response_is_authored_on_the_first_try(self, ledger, layout):
        provider = RecordingProvider(responses=[fill_for(layout)])
        result = run(author_zone(ledger, ZONE, layout, provider=provider,
                                 repair_provider=RecordingProvider()))
        assert result.status == "authored"
        assert result.attempts == 1
        assert result.package["entities"][0]["display_name"] == "Someone"

    def test_the_model_never_moves_anything(self, ledger, layout):
        provider = RecordingProvider(responses=[fill_for(layout)])
        result = run(author_zone(ledger, ZONE, layout, provider=provider,
                                 repair_provider=RecordingProvider()))
        placed = {(e["x"], e["y"]) for e in result.package["entities"]}
        assert placed == {(s.x, s.y) for s in layout.slots}

    def test_a_bad_response_is_repaired_on_the_second_try(self, ledger, layout):
        bad = fill_for(layout)
        bad["fills"][0]["script"] = [{"op": "GIVE_ITEM", "item_id": "no_such_item", "qty": 1}]
        provider = RecordingProvider(responses=[bad])
        repair = RecordingProvider(responses=[fill_for(layout)])
        result = run(author_zone(ledger, ZONE, layout, provider=provider, repair_provider=repair))
        assert result.status == "repaired"
        assert result.attempts == 2

    def test_the_repair_prompt_carries_the_validator_errors(self, ledger, layout):
        bad = fill_for(layout)
        bad["fills"][0]["script"] = [{"op": "GIVE_ITEM", "item_id": "no_such_item", "qty": 1}]
        repair = RecordingProvider(responses=[fill_for(layout)])
        run(author_zone(ledger, ZONE, layout, provider=RecordingProvider(responses=[bad]),
                        repair_provider=repair))
        assert "unknown_item" in repair.calls[0]["user"]

    def test_two_failures_degrade_to_placeholders(self, ledger, layout):
        bad = fill_for(layout)
        bad["fills"][0]["script"] = [{"op": "GIVE_ITEM", "item_id": "no_such_item", "qty": 1}]
        result = run(author_zone(ledger, ZONE, layout,
                                 provider=RecordingProvider(responses=[copy.deepcopy(bad)]),
                                 repair_provider=RecordingProvider(responses=[copy.deepcopy(bad)])))
        assert result.status == "placeholder"
        assert "placeholder" in json.dumps(result.package["entities"])

    def test_a_dead_provider_degrades_to_placeholders(self, ledger, layout):
        """4.4: a failed call must degrade to a boring zone, never to a crash."""
        result = run(author_zone(ledger, ZONE, layout,
                                 provider=RecordingProvider(responses=[LLMError("network is down")]),
                                 repair_provider=RecordingProvider(responses=[LLMError("still down")])))
        assert result.status == "placeholder"

    def test_the_placeholder_fallback_still_validates(self, ledger, layout):
        from backend.validation.validator import validate_zone_package

        result = run(author_zone(ledger, ZONE, layout,
                                 provider=RecordingProvider(responses=[LLMError("down")]),
                                 repair_provider=RecordingProvider(responses=[LLMError("down")])))
        assert validate_zone_package(result.package, ledger).ok

    def test_flags_used_but_not_declared_are_declared(self, ledger, layout):
        response = fill_for(layout)
        response["fills"][0]["script"] = [
            {"op": "SET_FLAG", "flag": "warned_about_the_mine", "value": True},
            {"op": "SHOW_TEXT", "speaker": "Someone", "text": "Careful up there."},
        ]
        result = run(author_zone(ledger, ZONE, layout, provider=RecordingProvider(responses=[response]),
                                 repair_provider=RecordingProvider()))
        assert result.status == "authored"
        assert "warned_about_the_mine" in result.package["declares_flags"]

    def test_a_proposal_never_becomes_an_obligation(self, ledger, layout):
        """4.5: proposals arrive in their own field and stay inert."""
        response = fill_for(layout)
        response["proposals"] = [
            {"kind": "key_item", "name": "Third Totem", "summary": "There should be a shrine."}
        ]
        before = len(ledger["obligations"])
        result = run(author_zone(ledger, ZONE, layout, provider=RecordingProvider(responses=[response]),
                                 repair_provider=RecordingProvider()))
        assert result.package["proposals"][0]["name"] == "Third Totem"
        assert result.package["fulfills_obligations"] == []
        assert len(ledger["obligations"]) == before

    def test_the_engine_assembles_the_context_not_the_model(self, ledger, layout):
        """4.3: the model is told what it may know; it never asks."""
        provider = RecordingProvider(responses=[fill_for(layout)])
        run(author_zone(ledger, ZONE, layout, provider=provider, repair_provider=RecordingProvider()))
        sent = provider.calls[0]["user"]
        for slot_id in slot_ids(layout):
            assert slot_id in sent
        assert "Slots to fill" in sent
