"""Building interiors (design doc 5, open question 1).

Open question 1 asked whether a town is one zone or a zone plus interior
sub-zones, and recommended separate small packages "to keep individual packages
small". That is what this is: one room, one package, generated the first time
somebody opens the door.

An interior knows two things its parent decided for it — what kind of building
it is, and which tile to put the player back on when they leave. Everything else
is derived from the seed.
"""

from __future__ import annotations

from .layout import (
    BARRIER, DETAIL, DOOR, EMPTY, FEATURE, FLOOR, PATH, POST, WALL, Layout, Slot,
)

# Counters, beds and tables are all BARRIER: the tile vocabulary is shared
# across tilesets, and furniture is exactly what "barrier" means indoors. Using
# a ground index like PLANKS for decor would block the tile while drawing
# nothing — an invisible wall.
from .rng import zone_rng

TILESET = "interior_wood"

# (width, height) per role. Rooms are small on purpose: a package per building
# only stays cheap if each one is tiny.
SIZES = {
    "shop": (13, 10),
    "inn": (15, 12),
    "house": (11, 9),
}


def generate(world_seed: int, zone_id: str, exits: dict[str, str], zone_kinds: dict[str, str],
             *, role: str = "house", return_to: tuple[int, int] = (1, 1)) -> Layout:
    width, height = SIZES.get(role, SIZES["house"])
    layout = Layout(width=width, height=height, tileset=TILESET)
    layout.fill_ground(FLOOR)

    rng = zone_rng(world_seed, zone_id, "interior")

    _shell(layout)
    door_x = width // 2
    _doorway(layout, door_x, height - 1)

    if role == "shop":
        _shop(layout, rng, door_x)
    elif role == "inn":
        _inn(layout, rng, door_x)
    else:
        _house(layout, rng, door_x)

    _clutter(layout, rng)

    parent = exits.get("out")
    if parent:
        layout.warps.append({
            "x": door_x, "y": height - 1,
            "to_zone": parent, "to_x": int(return_to[0]), "to_y": int(return_to[1]),
        })
    layout.spawn = (door_x, height - 2)
    layout.meta["role"] = role

    _prune_unreachable(layout)
    return layout


# --- the room --------------------------------------------------------------

def _shell(layout: Layout) -> None:
    for x in range(layout.width):
        layout.set_decor(x, 0, WALL)
        layout.set_decor(x, layout.height - 1, WALL)
    for y in range(layout.height):
        layout.set_decor(0, y, WALL)
        layout.set_decor(layout.width - 1, y, WALL)
    # A band of rafters along the top wall reads as "indoors" at a glance.
    for x in range(1, layout.width - 1):
        layout.set_ground(x, 1, PATH)


def _doorway(layout: Layout, x: int, y: int) -> None:
    layout.set_decor(x, y, DOOR, blocks=False)
    layout.set_ground(x, y, PATH)


def _furnish(layout: Layout, x: int, y: int, tile: int) -> None:
    if layout.inside(x, y) and layout.decor[layout.index(x, y)] == EMPTY:
        layout.set_decor(x, y, tile)


# --- roles -----------------------------------------------------------------

def _shop(layout: Layout, rng, door_x: int) -> None:
    counter_y = 3
    for x in range(2, layout.width - 2):
        layout.set_decor(x, counter_y, BARRIER)

    # The shopkeeper stands in a gap in the counter — the serving hatch — so a
    # customer on the near side is directly facing them. Marooning them behind
    # an unbroken counter makes them unreachable without walking round.
    hatch = rng.randrange(3, layout.width - 3)
    layout.set_decor(hatch, counter_y, EMPTY, blocks=False)

    for x in range(2, layout.width - 2, 3):
        _furnish(layout, x, 1, POST)  # shelves against the back wall

    layout.slots.append(Slot(kind="shop", x=hatch, y=counter_y,
                             hint="standing in the gap in their own shop counter"))
    if rng.random() < 0.6:
        for _ in range(20):
            x, y = rng.randrange(2, layout.width - 2), rng.randrange(counter_y + 2, layout.height - 2)
            if layout.walkable(x, y) and not _taken(layout, x, y):
                layout.slots.append(Slot(kind="npc", x=x, y=y, hint="a customer waiting in the shop"))
                break


def _inn(layout: Layout, rng, door_x: int) -> None:
    for y in range(3, layout.height - 3, 2):
        _furnish(layout, 2, y, BARRIER)  # beds down the left wall
        _furnish(layout, 3, y, BARRIER)

    counter_x = layout.width - 4
    for y in range(2, layout.height - 4):
        layout.set_decor(counter_x, y, BARRIER)
    hatch_y = rng.randrange(2, layout.height - 4)
    layout.set_decor(counter_x, hatch_y, EMPTY, blocks=False)

    _furnish(layout, layout.width - 3, 2, FEATURE)  # hearth in the corner

    layout.slots.append(Slot(kind="inn", x=counter_x, y=hatch_y,
                             hint="standing at the gap in their own bar"))
    for _ in range(20):
        x, y = rng.randrange(4, layout.width - 5), rng.randrange(4, layout.height - 2)
        if layout.walkable(x, y) and not _taken(layout, x, y):
            layout.slots.append(Slot(kind="npc", x=x, y=y, hint="a guest sitting in the common room"))
            break


def _house(layout: Layout, rng, door_x: int) -> None:
    _furnish(layout, 2, 2, FEATURE)  # hearth
    table_x = layout.width // 2
    for dx in (-1, 0, 1):
        _furnish(layout, table_x + dx, layout.height // 2, BARRIER)

    residents = rng.randint(1, 2)
    for _ in range(residents):
        for _attempt in range(30):
            x, y = rng.randrange(1, layout.width - 1), rng.randrange(2, layout.height - 2)
            if layout.walkable(x, y) and not _taken(layout, x, y):
                layout.slots.append(Slot(kind="npc", x=x, y=y, hint="at home, indoors"))
                break
    if rng.random() < 0.45:
        for _attempt in range(30):
            x, y = rng.randrange(1, layout.width - 1), rng.randrange(2, layout.height - 2)
            if layout.walkable(x, y) and not _taken(layout, x, y):
                layout.slots.append(Slot(kind="chest", x=x, y=y, hint="a household chest"))
                break


def _taken(layout: Layout, x: int, y: int) -> bool:
    return any(s.x == x and s.y == y for s in layout.slots)


def _clutter(layout: Layout, rng) -> None:
    for _ in range(rng.randint(2, 6)):
        x, y = rng.randrange(1, layout.width - 1), rng.randrange(2, layout.height - 2)
        if layout.walkable(x, y) and not _taken(layout, x, y):
            layout.set_decor(x, y, DETAIL, blocks=False)


def _prune_unreachable(layout: Layout) -> None:
    """Furniture is placed without checking what it seals off. Anything the
    player cannot reach from the doorway gets opened back up, so a chest can
    never end up behind a table."""
    reachable = layout.reachable_from(layout.spawn)
    for slot in list(layout.slots):
        if (slot.x, slot.y) in reachable:
            continue
        # Clear whatever is blocking the way in, one ring at a time.
        for nx, ny in ((slot.x, slot.y + 1), (slot.x - 1, slot.y), (slot.x + 1, slot.y), (slot.x, slot.y - 1)):
            if layout.inside(nx, ny) and 0 < nx < layout.width - 1 and 0 < ny < layout.height - 1:
                layout.set_decor(nx, ny, EMPTY, blocks=False)
        layout.block(slot.x, slot.y, False)
        reachable = layout.reachable_from(layout.spawn)
