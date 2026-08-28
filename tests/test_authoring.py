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
from backend.world.authoring import register_interiors

ROOT = pathlib.Path(__file__).resolve().parents[1]
SEED = 8471029
ZONE = "zone_town_01"


@pytest.fixture
def ledger():
    """A world with no outstanding obligations.

    new_game seeds one so that an unauthored world still has a real gate, but
    these tests are about the authoring ladder rather than the Fire Key
    machinery — obligations get their own test below.
    """
    world = new_game.create(SEED)
    world["obligations"] = []
    return world


@pytest.fixture
def ledger_with_obligation():
    return new_game.create(SEED)


@pytest.fixture
def layout(ledger):
    zone = ledger["zones"][ZONE]
    kinds = {z: v["kind"] for z, v in ledger["zones"].items()}
    built = generate_town(SEED, ZONE, zone["exits"], kinds)
    # commit() registers a stub for every door before the package is validated;
    # without it the town's own door warps look like dangling references.
    register_interiors(ledger, ZONE, built)
    return built


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
        {"id": "b1", "summary": "Arrive in the town.", "zone_hint": "Callow Ford", "kind": "town"},
        {"id": "b2", "summary": "Descend the workings.", "zone_hint": "upper mine", "kind": "dungeon"},
        {"id": "b3", "summary": "Open the deep door.", "zone_hint": "the deep door", "kind": "dungeon"},
        {"id": "b4", "summary": "Meet what waits below.", "zone_hint": "the hearth", "kind": "dungeon"},
    ],
    "obligations": [{"kind": "key_item", "name": "Ember Sigil", "gates_beat": "b4"}],
    "party_seed": [
        {"name": "Wren", "role": "blade", "voice": "clipped"},
        {"name": "Sabel", "role": "spark", "voice": "wry"},
    ],
}


class TestOutline:
    def test_writes_tone_and_beats(self, ledger):
        apply_outline(ledger, OUTLINE)
        assert ledger["outline"]["tone"] == "melancholy pastoral fantasy"
        assert [b["id"] for b in ledger["outline"]["beats"]] == ["b1", "b2", "b3", "b4"]

    def test_first_beat_is_active_and_the_rest_pending(self, ledger):
        apply_outline(ledger, OUTLINE)
        statuses = [b["status"] for b in ledger["outline"]["beats"]]
        assert statuses[0] == "active"
        assert set(statuses[1:]) == {"pending"}

    def test_turns_a_named_item_into_a_real_obligation(self, ledger):
        apply_outline(ledger, OUTLINE)
        order = list(ledger["zones"])
        obligation = ledger["obligations"][0]
        assert obligation["item_id"] == "ember_sigil"
        assert obligation["status"] == "open"
        assert obligation["placed_in"] is None
        # b4 is the fourth beat, so the door is into the fourth zone.
        assert obligation["required_by"] == order[3]

    def test_registers_the_item_so_references_resolve(self, ledger):
        apply_outline(ledger, OUTLINE)
        assert [i["id"] for i in ledger["defined_items"]] == ["ember_sigil"]

    def test_renames_the_party(self, ledger):
        apply_outline(ledger, OUTLINE)
        assert [m["name"] for m in ledger["party"]] == ["Wren", "Sabel"]

    def test_the_key_is_placed_before_the_door(self, ledger):
        """The whole point of the mechanism: never in or after the zone that
        needs it."""
        apply_outline(ledger, OUTLINE)
        order = list(ledger["zones"])
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


class TestObligations:
    """The Fire Key path through the authoring ladder."""

    def test_a_response_that_ignores_the_obligation_is_rejected(self, ledger_with_obligation):
        world = ledger_with_obligation
        zone = world["zones"][ZONE]
        kinds = {z: v["kind"] for z, v in world["zones"].items()}
        built = generate_town(SEED, ZONE, zone["exits"], kinds)
        register_interiors(world, ZONE, built)

        # A perfectly nice town that simply forgets to put the key anywhere.
        forgetful = RecordingProvider(responses=[fill_for(built), fill_for(built)])
        result = run(author_zone(world, ZONE, built,
                                 provider=forgetful, repair_provider=forgetful))
        assert result.status == "placeholder"
        assert any("obligation_unfulfilled" in note for note in result.notes), result.notes

    def test_the_template_fill_places_the_key_anyway(self, ledger_with_obligation):
        """Design doc 4.4: a failed call degrades to a boring zone, never to a
        broken gate. A template fill that dropped the key would be the broken
        gate."""
        from backend.validation.validator import validate_zone_package

        world = ledger_with_obligation
        zone = world["zones"][ZONE]
        kinds = {z: v["kind"] for z, v in world["zones"].items()}
        built = generate_town(SEED, ZONE, zone["exits"], kinds)
        register_interiors(world, ZONE, built)

        result = run(author_zone(world, ZONE, built,
                                 provider=RecordingProvider(responses=[LLMError("down")]),
                                 repair_provider=RecordingProvider(responses=[LLMError("down")])))
        assert result.status == "placeholder"
        given = {
            command["item_id"]
            for entity in result.package["entities"]
            for command in entity["script"]
            if command.get("op") == "GIVE_ITEM"
        }
        assert "deep_key" in given, "the placeholder dropped the key item"
        assert validate_zone_package(result.package, world).ok


class TestZonePlan:
    """The outline's beats are the map (design doc 4.2 + 5).

    One beat, one place, in order — which is what makes the outline a spine
    rather than a backdrop.
    """

    def test_one_zone_per_beat(self, ledger):
        apply_outline(ledger, OUTLINE)
        assert len(ledger["zones"]) == len(OUTLINE["beats"])

    def test_the_first_place_is_always_a_town(self, ledger):
        """Whatever the model says. The party has to start somewhere they can
        talk to someone."""
        outline = copy.deepcopy(OUTLINE)
        outline["beats"][0]["kind"] = "dungeon"
        apply_outline(ledger, outline)
        first = list(ledger["zones"].values())[0]
        assert first["kind"] == "town"

    def test_the_player_starts_in_the_first_place(self, ledger):
        apply_outline(ledger, OUTLINE)
        assert ledger["player_position"]["zone"] == list(ledger["zones"])[0]

    def test_consecutive_dungeons_connect_by_stairs(self, ledger):
        apply_outline(ledger, OUTLINE)
        order = list(ledger["zones"])
        upper, lower = order[1], order[2]
        assert ledger["zones"][upper]["exits"]["down"] == lower
        assert ledger["zones"][lower]["exits"]["up"] == upper

    def test_a_settlement_connects_by_road(self, ledger):
        apply_outline(ledger, OUTLINE)
        order = list(ledger["zones"])
        town, mine = order[0], order[1]
        assert ledger["zones"][town]["exits"]["north"] == mine
        assert ledger["zones"][mine]["exits"]["south"] == town

    def test_every_exit_has_a_way_back(self, ledger):
        apply_outline(ledger, OUTLINE)
        zones = ledger["zones"]
        for zone_id, zone in zones.items():
            for target in zone["exits"].values():
                assert zone_id in zones[target]["exits"].values(), \
                    f"{target} has no way back to {zone_id}"

    def test_the_plan_survives_its_own_validator(self, ledger):
        from backend.validation.validator import validate_ledger

        apply_outline(ledger, OUTLINE)
        report = validate_ledger(ledger)
        assert report.ok, str(report)

    def test_a_longer_outline_makes_a_longer_game(self, ledger):
        outline = copy.deepcopy(OUTLINE)
        outline["beats"].append(
            {"id": "b5", "summary": "Climb back out changed.", "zone_hint": "the road home", "kind": "town"}
        )
        apply_outline(ledger, outline)
        assert len(ledger["zones"]) == 5
        assert list(ledger["zones"].values())[-1]["kind"] == "town"


class TestProviderConfig:
    """Role -> provider mapping, including local endpoints (design doc 4.1)."""

    def test_an_openai_compatible_role_points_at_its_base_url(self):
        from backend.llm.config import build_provider

        provider = build_provider("r", {"r": {
            "provider": "lmstudio", "model": "some-model",
            "base_url": "http://192.168.0.9:1234/v1",
        }})
        assert provider.base_url == "http://192.168.0.9:1234/v1"
        assert provider.model == "some-model"

    def test_a_local_endpoint_needs_no_api_key(self):
        from backend.llm.config import build_provider

        provider = build_provider("r", {"r": {"provider": "lmstudio", "model": "m"}})
        assert provider.configured is True

    def test_the_environment_can_redirect_a_local_endpoint(self, monkeypatch):
        """So a server on another machine needs no file edit."""
        from backend.llm.config import role_config

        monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://172.20.10.6:1234/v1")
        spec = role_config("r", {"r": {"provider": "lmstudio", "model": "m"}})
        assert spec.base_url == "http://172.20.10.6:1234/v1"

    def test_local_roles_get_a_patient_default_timeout(self):
        """A 27B reasoning model can take minutes on one zone."""
        from backend.llm.config import role_config

        local = role_config("r", {"r": {"provider": "lmstudio", "model": "m"}})
        hosted = role_config("r", {"r": {"provider": "openrouter", "model": "m"}})
        assert local.timeout > hosted.timeout

    def test_ollama_keeps_its_own_provider(self):
        from backend.llm.config import build_provider
        from backend.llm.local import LocalProvider

        assert isinstance(build_provider("r", {"r": {"provider": "ollama", "model": "m"}}), LocalProvider)

    def test_an_unknown_provider_says_what_is_available(self):
        from backend.llm.config import build_provider

        with pytest.raises(ValueError, match="lmstudio"):
            build_provider("r", {"r": {"provider": "carrier-pigeon", "model": "m"}})

    def test_a_budget_spent_entirely_on_reasoning_is_reported_as_such(self):
        """A reasoning model that thinks up to its ceiling returns HTTP 200 and
        an empty string; 'response was not JSON' would send you looking in
        entirely the wrong place."""
        import asyncio

        from backend.llm.openai_compatible import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider("m", base_url="http://localhost:1/v1")

        class Response:
            status_code = 200
            def json(self):
                return {
                    "choices": [{"message": {"content": ""}}],
                    "usage": {"completion_tokens": 100,
                              "completion_tokens_details": {"reasoning_tokens": 100}},
                }

        async def fake_post(*_args, **_kwargs):
            return Response()

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return False
            post = staticmethod(fake_post)

        import backend.llm.openai_compatible as module
        original = module.httpx2.AsyncClient
        module.httpx2.AsyncClient = lambda **_: FakeClient()
        try:
            with pytest.raises(LLMError, match="reasoning"):
                asyncio.run(provider.complete(system="s", user="u", schema={}, max_tokens=100))
        finally:
            module.httpx2.AsyncClient = original


class TestObjectSlots:
    """The author decides what is in a chest; the engine decides that a chest
    looks like a chest."""

    def test_a_chest_is_drawn_as_a_chest_whatever_the_author_says(self):
        """Observed in play: a model filling a chest slot tagged it 'smith' --
        thinking of whose chest it was -- and the tag resolver drew a blacksmith
        standing where the chest should be."""
        from backend.packaging.assemble import assemble, slot_ids
        from backend.procgen.interior import generate as generate_interior

        layout = generate_interior(SEED, "zone_town_01_in02", {"out": "zone_town_01"}, {},
                                   role="house", return_to=(9, 14))
        fills = {
            sid: {"slot_id": sid, "display_name": "Anvil", "sprite_tags": ["human", "smith"],
                  "script": [{"op": "SHOW_TEXT", "speaker": "Anvil", "text": "hello"}]}
            for sid in slot_ids(layout)
        }
        package = assemble(layout, "zone_town_01_in02", "interior", fills=fills,
                           summary="A house with a chest in it, long enough to pass.")

        people = {"human", "elder", "adult", "child", "smith", "merchant", "miner", "farmer"}
        for entity in package["entities"]:
            tags = set(entity["sprite_tags"])
            if entity["type"] == "chest":
                assert "chest" in tags, f"chest has no chest tag: {sorted(tags)}"
                assert not (tags & people), f"chest tagged as a person: {sorted(tags)}"

    def test_a_person_still_looks_how_the_author_wanted(self):
        from backend.packaging.assemble import assemble, slot_ids
        from backend.procgen.interior import generate as generate_interior

        layout = generate_interior(SEED, "zone_town_01_in02", {"out": "zone_town_01"}, {},
                                   role="shop", return_to=(9, 14))
        fills = {
            sid: {"slot_id": sid, "display_name": "Mira", "sprite_tags": ["human", "merchant"],
                  "script": [{"op": "SHOW_TEXT", "speaker": "Mira", "text": "hello"}]}
            for sid in slot_ids(layout)
        }
        package = assemble(layout, "zone_town_01_in02", "interior", fills=fills,
                           summary="A shop with a shopkeeper in it, long enough to pass.")
        keeper = next(e for e in package["entities"] if e["type"] == "npc")
        assert "merchant" in keeper["sprite_tags"]
