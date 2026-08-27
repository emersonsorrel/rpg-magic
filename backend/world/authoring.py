"""The backend's one job (design doc 2): "give me the committed Zone Package for
zone X, generating it if it does not yet exist."

    proc-gen -> LLM authoring -> validate -> commit

Proc-gen decides the shape and the slots. The authoring call decides who stands
in them and what they say. The validator decides whether any of it is allowed to
become permanent.
"""

from __future__ import annotations

from ..llm.author import apply_outline, author_outline, author_zone, planned_placement
from ..llm.config import authoring_enabled
from ..llm.provider import LLMError
from ..procgen import dungeon, interior, town
from ..procgen.layout import Layout
from ..validation.validator import validate_zone_package
from .store import WorldStore

GENERATORS = {"town": town.generate, "dungeon": dungeon.generate, "interior": interior.generate}


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


def zone_order(ledger: dict) -> list[str]:
    """The traversal spine, for deciding where a key item goes.

    Interiors are deliberately excluded: they hang off a town rather than
    sitting between it and the next place, so putting a key item in one would
    make "the zone before the door" meaningless.
    """
    return [
        zone_id for zone_id, zone in ledger.get("zones", {}).items()
        if zone.get("kind") != "interior"
    ]


def generate_layout(ledger: dict, zone_id: str) -> Layout:
    zone = ledger["zones"].get(zone_id)
    if zone is None:
        raise UnknownZone(zone_id)
    generator = GENERATORS.get(zone["kind"])
    if generator is None:
        raise UnknownZone(f"no generator for kind '{zone['kind']}'")
    if zone["kind"] == "interior":
        return generator(
            ledger["seed"], zone_id, zone.get("exits", {}), zone_kinds(ledger),
            role=zone.get("role", "house"),
            return_to=tuple(zone.get("return_to") or (1, 1)),
        )
    return generator(ledger["seed"], zone_id, zone.get("exits", {}), zone_kinds(ledger))


def register_interiors(ledger: dict, zone_id: str, layout) -> list[str]:
    """Add a stub for every building this layout put a door on.

    Committing a zone can extend the zone graph. It has to happen before the
    package is validated, or the town's own door warps look like references to
    zones that do not exist.
    """
    specs = layout.meta.get("interiors") or []
    if not specs:
        return []
    ledger["zones"][zone_id]["interiors"] = [spec["id"] for spec in specs]
    for spec in specs:
        if spec["id"] in ledger["zones"]:
            continue
        ledger["zones"][spec["id"]] = {
            "id": spec["id"],
            "kind": "interior",
            "committed": False,
            "exits": {"out": zone_id},
            "role": spec["role"],
            "return_to": list(spec["return_to"]),
        }
    return [spec["id"] for spec in specs]


async def commit(ledger: dict, zone_id: str, store: WorldStore) -> dict:
    layout = generate_layout(ledger, zone_id)
    register_interiors(ledger, zone_id, layout)
    outcome = await author_zone(ledger, zone_id, layout, zone_order=zone_order(ledger))
    package = outcome.package

    # The authoring path validates before returning, but the placeholder path
    # short-circuits it, and nothing gets committed unvalidated.
    report = validate_zone_package(package, ledger)
    if not report.ok:
        raise ZoneRejected(zone_id, report)

    zone = ledger["zones"][zone_id]
    zone["committed"] = True
    zone["summary"] = package["summary"]
    zone["notable_entities"] = [e["id"] for e in package["entities"]][:32]
    zone["spawn"] = list(layout.spawn)
    zone["authored"] = outcome.status

    # An obligation this zone discharged is now physically somewhere.
    for obligation in ledger.get("obligations", []):
        if obligation["id"] in package.get("fulfills_obligations", []):
            obligation["placed_in"] = zone_id
            obligation["status"] = "placed"

    store.save_package(package)
    store.save_ledger(ledger)
    return package


async def get_or_generate(ledger: dict, zone_id: str, store: WorldStore) -> dict:
    if zone_id not in ledger.get("zones", {}):
        raise UnknownZone(zone_id)
    if store.has_package(zone_id):
        return store.load_package(zone_id)
    return await commit(ledger, zone_id, store)


async def begin(seed: int, store: WorldStore, premise: str | None = None) -> dict:
    """Start a world: outline first, because every zone authored afterwards is
    written against it."""
    from . import new_game

    ledger = new_game.create(seed, premise)

    if authoring_enabled():
        try:
            outline = await author_outline(premise)
            apply_outline(ledger, outline, zone_order(ledger))
        except LLMError as exc:
            # No outline means no obligations and a placeholder premise. The
            # game is duller, not broken.
            ledger.setdefault("notes", None)
            print(f"outline call failed, continuing unauthored: {exc}")

    # Deliberately not saved yet. commit() writes the ledger once the starting
    # town exists, so the ledger file never appears in a half-built state -- a
    # second request arriving mid-generation would otherwise load a world whose
    # town is not committed and whose interiors are not registered.
    start = ledger["player_position"]["zone"]
    await commit(ledger, start, store)
    spawn = ledger["zones"][start]["spawn"]
    ledger["player_position"] = {"zone": start, "x": spawn[0], "y": spawn[1]}
    store.save_ledger(ledger)
    return ledger
