"""The small, manually-run live suite (design doc 10).

Skipped unless you ask for it, because it costs money and depends on a third
party being up:

    RPG_MAGIC_LIVE=1 .venv/bin/python -m pytest tests/test_live_llm.py -v

What it is actually guarding is the thing mocks cannot: that the models named in
llm.yaml still honour `strict` json_schema. When a provider silently stops
enforcing a schema, every zone quietly degrades to placeholders and nothing else
in the suite notices.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from backend.llm.config import build_provider
from backend.llm.schemas import outline_schema, zone_author_schema
from backend.packaging.assemble import slot_ids
from backend.procgen.town import generate as generate_town
from backend.validation.registries import load_registries
from backend.world import new_game

live = pytest.mark.skipif(
    not os.environ.get("RPG_MAGIC_LIVE"),
    reason="set RPG_MAGIC_LIVE=1 to run the live suite (makes paid API calls)",
)

SEED = 8471029


def run(coro):
    return asyncio.run(coro)


@live
def test_the_outline_model_still_enforces_the_schema():
    provider = build_provider("outline")
    completion = run(provider.complete(
        system="You are a story architect. Reply only with JSON matching the schema.",
        user="Premise: a river town whose mine flooded and the water came back warm.",
        schema=outline_schema(),
        max_tokens=2000,
    ))
    # The provider raises LLMError if the response ignored the schema, so
    # getting here at all is most of the assertion.
    assert completion.data["tone"]
    assert len(completion.data["beats"]) >= 3
    assert completion.data["obligations"], "an outline with no key item gates nothing"


@live
def test_the_zone_author_model_still_enforces_the_nested_command_schema():
    """The one that broke: Anthropic models accept this schema, return 200, and
    ignore it. If the configured model starts doing that, catch it here."""
    ledger = new_game.create(SEED)
    layout = generate_town(SEED, "zone_town_01", {"north": "zone_mine_b1"},
                           {z: v["kind"] for z, v in ledger["zones"].items()})
    registries = load_registries()

    provider = build_provider("zone_author")
    completion = run(provider.complete(
        system="You write NPC dialogue for a 16-bit JRPG. Reply only with JSON matching the schema.",
        user="Fill every slot for a river town whose mine has flooded.\nSlots: "
             + ", ".join(slot_ids(layout)),
        schema=zone_author_schema(
            slot_ids=slot_ids(layout),
            sprite_tags=sorted(registries.sprite_tags),
            items=sorted(registries.item_ids(ledger)),
            flags=[],
        ),
        max_tokens=4000,
    ))
    filled = {f["slot_id"] for f in completion.data["fills"]}
    assert filled == set(slot_ids(layout)), "every slot must come back filled"
    for fill in completion.data["fills"]:
        for tag in fill["sprite_tags"]:
            assert tag in registries.sprite_tags, f"invented sprite tag {tag!r}"


@live
def test_a_whole_world_authors_without_falling_back():
    """End to end, against the real service. A `placeholder` here means the
    repair ladder ran out -- worth knowing before a player finds it."""
    import shutil
    import tempfile

    from backend.world.authoring import begin, get_or_generate
    from backend.world.store import WorldStore

    tmp = tempfile.mkdtemp()
    try:
        store = WorldStore("live", root=__import__("pathlib").Path(tmp))
        ledger = run(begin(SEED, store, "A river town's mine floods and the water comes back warm."))
        for zone_id in ledger["zones"]:
            run(get_or_generate(ledger, zone_id, store))
        statuses = {z: ledger["zones"][z].get("authored") for z in ledger["zones"]}
        assert "placeholder" not in statuses.values(), statuses
        assert all(o["status"] == "placed" for o in ledger["obligations"]), ledger["obligations"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
