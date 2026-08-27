"""Property tests for the generation layer (design doc 10).

    "every generated dungeon is fully connected; every required slot count is
    met; same seed produces identical output"

These run over a spread of seeds rather than one, because the failures worth
catching here are the ones a single lucky seed hides.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from backend.packaging.assemble import assemble
from backend.procgen import dungeon, town
from backend.procgen.layout import arrival, gateway, interior_arrival, zone_size
from backend.procgen.rng import derive
from backend.validation.validator import validate_ledger, validate_zone_package
from backend.world import new_game
from backend.world.authoring import commit, get_or_generate
from backend.world.store import WorldStore

SEEDS = [0, 1, 7, 42, 8471029, 123456789, 2**31 - 1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """These are property tests over the *generator*, run across seven seeds and
    three zones each. Authoring has no business running here: it would be slow,
    paid, and it would make the assertions depend on prose."""
    monkeypatch.setenv("RPG_MAGIC_NO_LLM", "1")


def arun(coro):
    """Committing is async now that authoring sits inside it."""
    return asyncio.run(coro)

KINDS = {"zone_town_01": "town", "zone_mine_b1": "dungeon", "zone_mine_b2": "dungeon"}
TOWN_EXITS = {"north": "zone_mine_b1"}
MINE_EXITS = {"south": "zone_town_01", "down": "zone_mine_b2"}


def _town(seed):
    return town.generate(seed, "zone_town_01", TOWN_EXITS, KINDS)


def _mine(seed):
    return dungeon.generate(seed, "zone_mine_b1", MINE_EXITS, KINDS)


def _signature(layout):
    return (
        layout.width, layout.height, layout.tileset,
        tuple(layout.ground), tuple(layout.decor), tuple(layout.collision),
        tuple((s.kind, s.x, s.y) for s in layout.slots),
        tuple(tuple(sorted(w.items())) for w in layout.warps),
        layout.spawn,
    )


# --- determinism -----------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_same_seed_produces_identical_output(seed):
    assert _signature(_town(seed)) == _signature(_town(seed))
    assert _signature(_mine(seed)) == _signature(_mine(seed))


def test_different_seeds_diverge():
    signatures = {_signature(_town(seed)) for seed in SEEDS}
    assert len(signatures) == len(SEEDS)


def test_hashing_is_stable_across_processes():
    """Python's built-in hash() is randomised per process; derive() must not be."""
    import subprocess
    import sys

    code = "from backend.procgen.rng import derive; print(derive(8471029, 'zone_town_01'))"
    root = pathlib.Path(__file__).resolve().parents[1]
    runs = {
        subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True).stdout.strip()
        for _ in range(2)
    }
    assert len(runs) == 1
    assert runs.pop() == str(derive(8471029, "zone_town_01"))


# --- connectivity ----------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_dungeon_is_fully_connected(seed):
    layout = _mine(seed)
    assert layout.is_fully_connected(), "a walkable tile is stranded from the rest"


@pytest.mark.parametrize("seed", SEEDS)
def test_town_is_fully_connected(seed):
    assert _town(seed).is_fully_connected()


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("build", [_town, _mine], ids=["town", "dungeon"])
def test_every_slot_and_warp_is_reachable_from_spawn(seed, build):
    layout = build(seed)
    reachable = layout.reachable_from(layout.spawn)
    for slot in layout.slots:
        assert (slot.x, slot.y) in reachable, f"{slot.kind} at ({slot.x},{slot.y}) is unreachable"
    for warp in layout.warps:
        assert (warp["x"], warp["y"]) in reachable, f"warp at ({warp['x']},{warp['y']}) is unreachable"


# --- slot counts -----------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_town_supplies_the_slots_a_town_needs(seed):
    """Traders moved indoors when interiors landed, so the street holds
    villagers and the shop/inn slots live behind their own doors."""
    kinds = [s.kind for s in _town(seed).slots]
    assert kinds.count("npc") >= 2
    assert kinds.count("chest") >= 1
    assert kinds.count("sign") >= 1
    assert "shop" not in kinds and "inn" not in kinds


@pytest.mark.parametrize("seed", SEEDS)
def test_every_town_has_exactly_one_shop_and_one_inn_behind_its_doors(seed):
    roles = [spec["role"] for spec in _town(seed).meta.get("interiors", [])]
    assert roles.count("shop") == 1
    assert roles.count("inn") == 1
    assert len(roles) >= 3


@pytest.mark.parametrize("seed", SEEDS)
def test_every_door_leads_somewhere_and_leads_back(seed):
    """The door warp and the interior's own exit have to agree without either
    generator having run the other."""
    from backend.procgen.interior import SIZES, generate as generate_interior

    layout = _town(seed)
    specs = {spec["id"]: spec for spec in layout.meta.get("interiors", [])}
    assert specs, "a town with no interiors has no doors"

    door_warps = [w for w in layout.warps if w["to_zone"] in specs]
    assert len(door_warps) == len(specs)

    for warp in door_warps:
        spec = specs[warp["to_zone"]]
        inside = generate_interior(
            seed, warp["to_zone"], {"out": "zone_town_01"}, KINDS,
            role=spec["role"], return_to=tuple(spec["return_to"]),
        )
        # Out: the town said where to land, and it is where the room starts.
        assert (warp["to_x"], warp["to_y"]) == inside.spawn
        assert inside.walkable(*inside.spawn)
        # Back: the interior returns the player to the doorstep, not the door.
        back = inside.warps[0]
        assert back["to_zone"] == "zone_town_01"
        assert (back["to_x"], back["to_y"]) == tuple(spec["return_to"])
        assert layout.walkable(back["to_x"], back["to_y"])
        assert (back["to_x"], back["to_y"]) != (warp["x"], warp["y"]), \
            "landing on the door would bounce the player straight back inside"


@pytest.mark.parametrize("seed", SEEDS)
def test_interiors_are_walkable_and_nothing_is_furnished_shut(seed):
    from backend.procgen.interior import generate as generate_interior

    for role in ("shop", "inn", "house"):
        inside = generate_interior(seed, f"zone_town_01_in01", {"out": "zone_town_01"}, KINDS,
                                   role=role, return_to=(5, 5))
        reachable = inside.reachable_from(inside.spawn)
        for slot in inside.slots:
            assert (slot.x, slot.y) in reachable, f"{role}: {slot.kind} is furnished shut"
        for warp in inside.warps:
            assert (warp["x"], warp["y"]) in reachable, f"{role}: no way back out"


@pytest.mark.parametrize("seed", SEEDS)
def test_dungeon_supplies_chests(seed):
    kinds = [s.kind for s in _mine(seed).slots]
    assert kinds.count("chest") >= 2


# --- the lazy-generation handshake ----------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_neighbours_agree_on_the_shared_door(seed):
    """The town is committed before the mine exists, so its warp coordinates
    are computed, not looked up. The mine must honour them."""
    town_layout = _town(seed)
    warp = next(w for w in town_layout.warps if w["to_zone"] == "zone_mine_b1")
    assert (warp["x"], warp["y"]) == gateway(seed, "zone_town_01", "town", "north")
    assert (warp["to_x"], warp["to_y"]) == arrival(seed, "zone_mine_b1", "dungeon", "south")

    mine_layout = _mine(seed)
    landing = (warp["to_x"], warp["to_y"])
    assert mine_layout.walkable(*landing), "the town warps the player into solid rock"
    assert landing in mine_layout.reachable_from(mine_layout.spawn)

    back = next(w for w in mine_layout.warps if w["to_zone"] == "zone_town_01")
    assert (back["to_x"], back["to_y"]) == arrival(seed, "zone_town_01", "town", "north")
    assert town_layout.walkable(back["to_x"], back["to_y"])


@pytest.mark.parametrize("seed", SEEDS)
def test_stairs_land_on_walkable_ground_on_the_next_floor(seed):
    mine = _mine(seed)
    down = next(w for w in mine.warps if w["to_zone"] == "zone_mine_b2")
    assert (down["to_x"], down["to_y"]) == interior_arrival(seed, "zone_mine_b2", "dungeon", "up")

    b2 = dungeon.generate(seed, "zone_mine_b2", {"up": "zone_mine_b1"}, KINDS)
    landing = (down["to_x"], down["to_y"])
    assert b2.walkable(*landing)
    assert landing in b2.reachable_from(b2.spawn)


def test_zone_size_is_derivable_without_generating():
    """A neighbour has to reason about a zone that does not exist yet."""
    assert zone_size(42, "zone_mine_b1", "dungeon") == zone_size(42, "zone_mine_b1", "dungeon")
    layout = _mine(42)
    assert (layout.width, layout.height) == zone_size(42, "zone_mine_b1", "dungeon")


# --- packages the validator will accept -----------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_generated_packages_pass_full_validation(seed, tmp_path):
    ledger = new_game.create(seed)
    store = WorldStore("test", root=tmp_path)
    store.save_ledger(ledger)
    assert validate_ledger(ledger).ok

    # Committing a town registers an interior stub per building, so the zone
    # graph grows while it is being walked. Drain a queue rather than iterating
    # the dict — which also means every lazily-discovered interior gets checked.
    pending = list(ledger["zones"])
    seen: set[str] = set()
    while pending:
        zone_id = pending.pop(0)
        if zone_id in seen:
            continue
        seen.add(zone_id)
        package = arun(get_or_generate(ledger, zone_id, store))
        report = validate_zone_package(package, ledger)
        assert report.ok, f"seed {seed} / {zone_id}\n{report}"
        pending.extend(z for z in ledger["zones"] if z not in seen)

    assert validate_ledger(ledger).ok, "the ledger must survive its own growth"
    kinds = {z["kind"] for z in ledger["zones"].values()}
    assert "interior" in kinds, "a town with no interiors means no doors were wired"


def test_committed_zones_are_never_rewritten(tmp_path):
    """Open question 2, made physical: committed is permanent."""
    ledger = new_game.create(8471029)
    store = WorldStore("test", root=tmp_path)
    store.save_ledger(ledger)
    arun(commit(ledger, "zone_town_01", store))
    with pytest.raises(FileExistsError):
        arun(commit(ledger, "zone_town_01", store))


def test_regenerating_a_committed_zone_returns_the_stored_bytes(tmp_path):
    ledger = new_game.create(8471029)
    store = WorldStore("test", root=tmp_path)
    store.save_ledger(ledger)
    first = arun(get_or_generate(ledger, "zone_town_01", store))
    second = arun(get_or_generate(ledger, "zone_town_01", store))
    assert first == second


def test_the_ledger_is_never_saved_half_built(tmp_path, monkeypatch):
    """A second request arriving mid-generation loads whatever is on disk.

    If `begin` writes the ledger before the starting town commits, that reader
    gets a world with an uncommitted town and no interiors registered — which
    is exactly what happened the first time a browser and a health probe hit
    the service together.
    """
    import copy

    from backend.world.authoring import begin

    store = WorldStore("half", root=tmp_path)
    snapshots = []
    real_save = store.save_ledger

    def spy(ledger):
        snapshots.append(copy.deepcopy(ledger))
        real_save(ledger)

    store.save_ledger = spy
    arun(begin(8471029, store))

    assert snapshots, "begin() never saved a ledger"
    for snapshot in snapshots:
        town = snapshot["zones"]["zone_town_01"]
        assert town["committed"], "a saved ledger had an uncommitted starting town"
        assert town.get("interiors"), "a saved ledger had a town whose doors led nowhere"
