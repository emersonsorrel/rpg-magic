"""The obligation integrity harness (design doc 10).

    "a fuzz harness that generates N full games headlessly (no rendering,
    scripted traversal) and asserts no run is softlocked. Run this in CI; it is
    the cheapest guard against the failure mode that would most damage the
    experience."

This is the test M5 exists for. Everything else checks that a piece behaves;
this checks that a whole generated world can actually be finished.

The traversal is deliberately literal: it opens a locked door only when the key
is genuinely in hand, having been picked up in a zone it had already walked to.
No shortcuts, no assuming an obligation was honoured because the ledger says so.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from backend.world.authoring import (
    UnknownZone, ZoneRejected, begin, get_or_generate, zone_order,
)
from backend.world.store import WorldStore

SEEDS = [0, 1, 7, 42, 8471029, 123456789, 2**31 - 1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No model. The point is the engine's guarantee, which must hold whether or
    not anything was authored — and a paid call per zone per seed is not a test."""
    monkeypatch.setenv("RPG_MAGIC_NO_LLM", "1")


def items_given(package: dict) -> set[str]:
    """Every item the player could walk out of this zone holding.

    Optimistic about branches: an item behind an IF_FLAG counts as obtainable,
    since the player can talk to everyone and open everything. That bias makes
    reachability *easier* to claim, so this harness proves the ordering is sound
    rather than proving the content is generous — the validator's stricter
    per-zone checks are what stop an item being placed somewhere unreachable in
    the first place.
    """
    found: set[str] = set()

    def walk(script):
        for command in script or []:
            if not isinstance(command, dict):
                continue
            if command.get("op") == "GIVE_ITEM":
                found.add(command["item_id"])
            for branch in ("then", "else", "on_win", "on_lose"):
                walk(command.get(branch))
            for option in command.get("options") or []:
                walk(option.get("script"))

    for entity in package.get("entities", []):
        walk(entity.get("script"))
    return found


@dataclass
class Run:
    seed: int
    ledger: dict
    reached: set[str] = field(default_factory=set)
    inventory: set[str] = field(default_factory=set)
    blocked: list[tuple[str, str, str]] = field(default_factory=list)

    def explain(self) -> str:
        lines = [f"seed {self.seed}", f"  reached: {sorted(self.reached)}",
                 f"  inventory: {sorted(self.inventory)}"]
        for zone, target, item in self.blocked:
            lines.append(f"  stuck: {zone} -> {target} needs '{item}'")
        for obligation in self.ledger.get("obligations", []):
            lines.append(
                f"  obligation {obligation['id']}: item={obligation.get('item_id')} "
                f"placed_in={obligation.get('placed_in')} status={obligation['status']} "
                f"required_by={obligation.get('required_by')}"
            )
        return "\n".join(lines)


def play(seed: int, root) -> Run:
    """Walk a whole generated world to a fixed point."""
    store = WorldStore(f"fuzz_{seed}", root=root)
    ledger = asyncio.run(begin(seed, store))
    run = Run(seed=seed, ledger=ledger)
    run.inventory = {stack["item_id"] for stack in ledger.get("inventory", [])}

    frontier = {ledger["player_position"]["zone"]}
    packages: dict[str, dict] = {}

    progressed = True
    while progressed:
        progressed = False
        run.blocked = []

        for zone_id in sorted(frontier - run.reached):
            try:
                packages[zone_id] = asyncio.run(get_or_generate(ledger, zone_id, store))
            except ZoneRejected as rejected:
                pytest.fail(f"seed {seed}: {zone_id} was refused\n{rejected.report}")
            except UnknownZone:
                pytest.fail(f"seed {seed}: {zone_id} is warped to but not in the ledger")
            run.reached.add(zone_id)
            run.inventory |= items_given(packages[zone_id])
            progressed = True

        # Re-test every door now that the pack may be carrying more.
        for zone_id in sorted(run.reached):
            for warp in packages[zone_id].get("warps", []):
                lock = warp.get("locked") or {}
                needed = lock.get("requires_item")
                if needed and needed not in run.inventory:
                    run.blocked.append((zone_id, warp["to_zone"], needed))
                    continue
                if warp["to_zone"] not in frontier:
                    frontier.add(warp["to_zone"])
                    progressed = True

    return run


@pytest.mark.parametrize("seed", SEEDS)
def test_a_generated_world_can_be_finished(seed, tmp_path):
    """Every zone on the spine is reachable by a player who only ever opens a
    door they hold the key for."""
    run = play(seed, tmp_path)
    spine = set(zone_order(run.ledger))
    unreachable = spine - run.reached
    assert not unreachable, f"unreachable zones {sorted(unreachable)}\n{run.explain()}"


@pytest.mark.parametrize("seed", SEEDS)
def test_no_door_is_left_permanently_shut(seed, tmp_path):
    run = play(seed, tmp_path)
    assert not run.blocked, f"a locked door was never opened\n{run.explain()}"


@pytest.mark.parametrize("seed", SEEDS)
def test_every_obligation_is_discharged_and_its_door_is_passed(seed, tmp_path):
    run = play(seed, tmp_path)
    for obligation in run.ledger.get("obligations", []):
        assert obligation["status"] in ("placed", "consumed"), \
            f"{obligation['id']} was never placed\n{run.explain()}"
        assert obligation["placed_in"] in run.reached, \
            f"{obligation['id']} was placed somewhere unreachable\n{run.explain()}"
        assert obligation["item_id"] in run.inventory, \
            f"{obligation['id']}'s key was never obtainable\n{run.explain()}"
        assert obligation["required_by"] in run.reached, \
            f"{obligation['id']} gates {obligation['required_by']}, never reached\n{run.explain()}"


@pytest.mark.parametrize("seed", SEEDS)
def test_the_key_is_found_before_the_door_it_opens(seed, tmp_path):
    """The ordering guarantee stated positively: the zone holding the key must
    be reachable without ever passing the door that key unlocks."""
    run = play(seed, tmp_path)
    order = zone_order(run.ledger)
    for obligation in run.ledger.get("obligations", []):
        key_zone = obligation["placed_in"]
        gated = obligation["required_by"]
        assert key_zone in order, f"{obligation['id']} placed off the spine in {key_zone}"
        assert order.index(key_zone) < order.index(gated), (
            f"{obligation['id']}: key sits in {key_zone}, at or past the door into "
            f"{gated}\n{run.explain()}"
        )


def test_a_world_whose_key_was_never_placed_is_caught(tmp_path):
    """The harness has to be able to fail. Sabotage the placement and confirm
    the engine refuses rather than quietly shipping an unwinnable run."""
    store = WorldStore("sabotage", root=tmp_path)
    ledger = asyncio.run(begin(8471029, store))

    # Pretend the town never placed the key, then generate the zone that locks
    # the way on behind it.
    for obligation in ledger["obligations"]:
        obligation["placed_in"] = None
        obligation["status"] = "open"

    with pytest.raises(ZoneRejected) as caught:
        asyncio.run(get_or_generate(ledger, "zone_mine_b1", store))
    assert "gate_before_key" in {issue.code for issue in caught.value.report.errors}


# --- worlds shaped by an outline ------------------------------------------
#
# The stub plan above is three zones with one gate. A world built from a real
# outline is four to six zones with up to three, which is where an ordering bug
# would actually live. These synthesise outlines rather than calling a model, so
# the shapes are varied, reproducible and free.

import random



def synthetic_outline(seed: int) -> dict:
    rng = random.Random(seed)
    count = rng.randint(4, 6)
    beats = [
        {
            "id": f"b{i + 1}",
            "summary": f"Beat {i + 1} happens.",
            "zone_hint": f"place {i + 1}",
            "kind": "town" if i == 0 else rng.choice(["town", "dungeon"]),
        }
        for i in range(count)
    ]
    # Gate somewhere past the opening, which is where a key can meaningfully sit.
    gates = rng.sample([b["id"] for b in beats[1:]], k=rng.randint(1, min(3, count - 1)))
    return {
        "tone": "test",
        "premise": "A synthetic world.",
        "antagonist": {"name": "The Fixture", "motive": "To be traversed."},
        "beats": beats,
        "obligations": [
            {"kind": "key_item", "name": f"Key {chr(65 + i)}", "gates_beat": beat_id}
            for i, beat_id in enumerate(gates)
        ],
        "party_seed": [
            {"name": "Ay", "role": "blade", "voice": "flat"},
            {"name": "Bee", "role": "spark", "voice": "flat"},
        ],
    }


def play_outlined(seed: int, root) -> Run:
    """Same traversal, but on a world whose shape came from an outline."""
    store = WorldStore(f"outlined_{seed}", root=root)
    # The outline has to land before anything is committed, since it replaces
    # the zone plan; begin() takes one directly for exactly this.
    ledger = asyncio.run(begin(seed, store, outline=synthetic_outline(seed)))

    run = Run(seed=seed, ledger=ledger)
    run.inventory = {stack["item_id"] for stack in ledger.get("inventory", [])}
    frontier = {ledger["player_position"]["zone"]}
    packages: dict[str, dict] = {}

    progressed = True
    while progressed:
        progressed = False
        run.blocked = []
        for zone_id in sorted(frontier - run.reached):
            try:
                packages[zone_id] = asyncio.run(get_or_generate(ledger, zone_id, store))
            except ZoneRejected as rejected:
                pytest.fail(f"seed {seed}: {zone_id} was refused\n{rejected.report}")
            run.reached.add(zone_id)
            run.inventory |= items_given(packages[zone_id])
            progressed = True
        for zone_id in sorted(run.reached):
            for warp in packages[zone_id].get("warps", []):
                needed = (warp.get("locked") or {}).get("requires_item")
                if needed and needed not in run.inventory:
                    run.blocked.append((zone_id, warp["to_zone"], needed))
                    continue
                if warp["to_zone"] not in frontier:
                    frontier.add(warp["to_zone"])
                    progressed = True
    return run


@pytest.mark.parametrize("seed", SEEDS)
def test_an_outlined_world_can_be_finished(seed, tmp_path):
    run = play_outlined(seed, tmp_path)
    spine = set(zone_order(run.ledger))
    assert not spine - run.reached, f"unreachable\n{run.explain()}"
    assert not run.blocked, f"a door was never opened\n{run.explain()}"


@pytest.mark.parametrize("seed", SEEDS)
def test_every_gate_in_an_outlined_world_opens(seed, tmp_path):
    run = play_outlined(seed, tmp_path)
    order = zone_order(run.ledger)
    assert run.ledger["obligations"], "an outline with no obligation gates nothing"
    for obligation in run.ledger["obligations"]:
        assert obligation["status"] in ("placed", "consumed"), run.explain()
        assert obligation["item_id"] in run.inventory, run.explain()
        assert order.index(obligation["placed_in"]) < order.index(obligation["required_by"]), \
            f"{obligation['id']} placed at or past its own door\n{run.explain()}"


@pytest.mark.parametrize("seed", SEEDS)
def test_a_threshold_is_never_gated_twice(seed, tmp_path):
    """`locked` holds one item, so two keys for one doorway would leave the
    second opening nothing."""
    run = play_outlined(seed, tmp_path)
    gated = [o["required_by"] for o in run.ledger["obligations"]]
    assert len(gated) == len(set(gated)), f"two obligations share a threshold: {gated}"
