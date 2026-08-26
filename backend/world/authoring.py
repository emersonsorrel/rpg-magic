"""The backend's one job (design doc 2): "give me the committed Zone Package for
zone X, generating it if it does not yet exist."

    proc-gen -> assemble -> validate -> commit

Nothing is committed that the validator rejects. At M2 there is no LLM in this
path at all; M3 inserts the authoring call between assemble and validate.
"""

from __future__ import annotations

from ..packaging.assemble import assemble
from ..procgen import dungeon, town
from ..procgen.layout import Layout
from ..validation.validator import validate_zone_package
from .store import WorldStore

GENERATORS = {"town": town.generate, "dungeon": dungeon.generate}


class ZoneRejected(Exception):
    """A generated package failed validation. It is never committed."""

    def __init__(self, zone_id: str, report):
        super().__init__(f"{zone_id} failed validation:\n{report}")
        self.zone_id = zone_id
        self.report = report


class UnknownZone(Exception):
    pass


def zone_kinds(ledger: dict) -> dict[str, str]:
    return {zid: zone.get("kind", "dungeon") for zid, zone in ledger.get("zones", {}).items()}


def generate_layout(ledger: dict, zone_id: str) -> Layout:
    zone = ledger["zones"].get(zone_id)
    if zone is None:
        raise UnknownZone(zone_id)
    generator = GENERATORS.get(zone["kind"])
    if generator is None:
        raise UnknownZone(f"no generator for kind '{zone['kind']}'")
    return generator(ledger["seed"], zone_id, zone.get("exits", {}), zone_kinds(ledger))


def build_package(ledger: dict, zone_id: str) -> dict:
    """Generate and assemble, without committing. Used by tests and by the
    commit path below."""
    zone = ledger["zones"][zone_id]
    layout = generate_layout(ledger, zone_id)
    fulfills = [
        o["id"]
        for o in ledger.get("obligations", [])
        if o.get("placed_in") == zone_id or o.get("must_place_before") == zone_id
    ]
    return assemble(layout, zone_id, zone["kind"], fulfills=fulfills), layout


def commit(ledger: dict, zone_id: str, store: WorldStore) -> dict:
    package, layout = build_package(ledger, zone_id)

    report = validate_zone_package(package, ledger)
    if not report.ok:
        raise ZoneRejected(zone_id, report)

    zone = ledger["zones"][zone_id]
    zone["committed"] = True
    zone["summary"] = package["summary"]
    zone["notable_entities"] = [e["id"] for e in package["entities"]][:32]
    zone["spawn"] = list(layout.spawn)

    store.save_package(package)
    store.save_ledger(ledger)
    return package


def get_or_generate(ledger: dict, zone_id: str, store: WorldStore) -> dict:
    if zone_id not in ledger.get("zones", {}):
        raise UnknownZone(zone_id)
    if store.has_package(zone_id):
        return store.load_package(zone_id)
    return commit(ledger, zone_id, store)


def begin(seed: int, store: WorldStore, premise: str | None = None) -> dict:
    """Start a world: write the ledger, commit the starting town, then move the
    player onto the tile that town actually chose for its spawn."""
    from . import new_game

    ledger = new_game.create(seed, premise)
    store.save_ledger(ledger)

    start = ledger["player_position"]["zone"]
    commit(ledger, start, store)
    spawn = ledger["zones"][start]["spawn"]
    ledger["player_position"] = {"zone": start, "x": spawn[0], "y": spawn[1]}
    store.save_ledger(ledger)
    return ledger
