"""Town generator (design doc 5).

    road skeleton -> building footprints along roads -> slots

Deterministic and LLM-free: given (seed, zone_id, exits) it always produces the
same town. It decides how many NPCs a town supports and where they stand; it
never decides who they are.
"""

from __future__ import annotations

from .layout import (
    BLOCKER, DETAIL, DOOR, EDGES, EMPTY, FEATURE, FLOOR, PATH, ROOF, WALL,
    Layout, Slot, apply_gate, arrival, clear_blocking_slots, gateway, zone_size,
)
from .interior import SIZES as INTERIOR_SIZES
from .rng import zone_rng

TILESET = "overworld_temperate"

# (dx, dy) the door faces, i.e. the direction of the road it fronts onto.
FACINGS = {"south": (0, 1), "north": (0, -1), "east": (1, 0), "west": (-1, 0)}


def generate(world_seed: int, zone_id: str, exits: dict[str, str], zone_kinds: dict[str, str],
             *, gates: dict | None = None) -> Layout:
    width, height = zone_size(world_seed, zone_id, "town")
    layout = Layout(width=width, height=height, tileset=TILESET)
    layout.fill_ground(FLOOR)

    rng = zone_rng(world_seed, zone_id, "town")

    _treeline(layout)
    roads = _road_skeleton(layout, rng)
    _gateway_roads(layout, world_seed, zone_id, exits, roads)
    buildings = _buildings(layout, rng, roads)
    _assign_roles(buildings, rng)
    _plaza(layout, roads, rng)
    _slots(layout, rng, buildings, roads)
    _interiors(layout, zone_id, buildings)
    _warps(layout, world_seed, zone_id, exits, zone_kinds, gates)
    _spawn(layout, roads)
    clear_blocking_slots(layout, [layout.spawn], keep=doorsteps(buildings))

    return layout


# --- terrain ---------------------------------------------------------------

def _treeline(layout: Layout) -> None:
    for x in range(layout.width):
        layout.set_decor(x, 0, BLOCKER)
        layout.set_decor(x, layout.height - 1, BLOCKER)
    for y in range(layout.height):
        layout.set_decor(0, y, BLOCKER)
        layout.set_decor(layout.width - 1, y, BLOCKER)


def _pave(layout: Layout, x: int, y: int, roads: set) -> None:
    if not layout.inside(x, y):
        return
    layout.set_ground(x, y, PATH)
    layout.set_decor(x, y, EMPTY, blocks=False)
    roads.add((x, y))


def _road_skeleton(layout: Layout, rng) -> set:
    """One crossroads, two tiles wide, offset from centre so towns differ."""
    roads: set = set()
    cx = layout.width // 2 + rng.randint(-3, 3)
    cy = layout.height // 2 + rng.randint(-2, 2)
    layout.notes.append(f"crossroads at ({cx},{cy})")

    for y in range(1, layout.height - 1):
        _pave(layout, cx, y, roads)
        _pave(layout, cx + 1, y, roads)
    for x in range(1, layout.width - 1):
        _pave(layout, x, cy, roads)
        _pave(layout, x, cy + 1, roads)

    layout.meta["crossroads"] = (cx, cy)
    return roads


def _gateway_roads(layout: Layout, world_seed: int, zone_id: str, exits: dict, roads: set) -> None:
    """Carve the border gateway open and run a road inward until it meets the
    skeleton, so every exit is reachable by construction."""
    cx, cy = layout.meta["crossroads"]
    for edge in exits:
        if edge not in EDGES:
            continue
        gx, gy = gateway(world_seed, zone_id, "town", edge)
        _pave(layout, gx, gy, roads)
        if edge in ("north", "south"):
            step = 1 if edge == "north" else -1
            y = gy
            while y != cy:
                _pave(layout, gx, y, roads)
                y += step
        else:
            step = 1 if edge == "west" else -1
            x = gx
            while x != cx:
                _pave(layout, x, gy, roads)
                x += step


# --- buildings -------------------------------------------------------------

def _buildings(layout: Layout, rng, roads: set) -> list[dict]:
    """Footprints fronting onto a road, never touching each other or the border.

    A one-tile margin around every footprint is required, which is what keeps
    the open ground connected: a building can never seal off a pocket of grass.
    """
    placed: list[dict] = []
    building_cells: set = set()
    wanted = rng.randint(5, 8)

    candidates = sorted(roads)
    rng.shuffle(candidates)

    for road_x, road_y in candidates:
        if len(placed) >= wanted:
            break
        facing = rng.choice(list(FACINGS))
        dx, dy = FACINGS[facing]
        bw, bh = rng.randint(4, 6), rng.randint(3, 4)

        # The building sits on the far side of the road tile, one gap away, with
        # its door row/column facing back toward that road.
        if facing == "south":
            bx, by = road_x - bw // 2, road_y - bh
        elif facing == "north":
            bx, by = road_x - bw // 2, road_y + 1
        elif facing == "east":
            bx, by = road_x - bw, road_y - bh // 2
        else:
            bx, by = road_x + 1, road_y - bh // 2

        cells = list(layout.rect(bx, by, bw, bh))
        if len(cells) != bw * bh:
            continue
        # Footprint stays off the treeline and off every road.
        if any(not (1 <= x < layout.width - 1 and 1 <= y < layout.height - 1) for x, y in cells):
            continue
        if any((x, y) in roads for x, y in cells):
            continue
        # A one-tile gap from other buildings, so two footprints can never fuse
        # into a wall that seals off a pocket of open ground.
        margin = list(layout.rect(bx - 1, by - 1, bw + 2, bh + 2))
        if any((x, y) in building_cells for x, y in margin):
            continue

        for x, y in cells:
            layout.set_decor(x, y, ROOF)
        # The face is the row or column nearest the road it fronts.
        if facing == "south":
            face = [(x, by + bh - 1) for x in range(bx, bx + bw)]
        elif facing == "north":
            face = [(x, by) for x in range(bx, bx + bw)]
        elif facing == "east":
            face = [(bx + bw - 1, y) for y in range(by, by + bh)]
        else:
            face = [(bx, y) for y in range(by, by + bh)]
        for x, y in face:
            layout.set_decor(x, y, WALL)

        door = face[len(face) // 2]
        # Walkable: stepping into the doorway is what triggers the interior warp.
        layout.set_decor(*door, DOOR, blocks=False)
        step_out = (door[0] + dx, door[1] + dy)
        if step_out not in roads:
            continue

        building_cells.update(cells)
        placed.append({"rect": (bx, by, bw, bh), "door": door, "step_out": step_out, "facing": facing})

    return placed


def _assign_roles(buildings: list[dict], rng) -> None:
    """Every town gets one shop and one inn; the rest are houses. Decided here
    rather than in the slot pass, because the interior behind a door has to
    agree with what the door is."""
    order = list(range(len(buildings)))
    rng.shuffle(order)
    roles = ["shop", "inn"] + ["house"] * max(0, len(buildings) - 2)
    for role, index in zip(roles, order):
        buildings[index]["role"] = role


def _interiors(layout: Layout, zone_id: str, buildings: list[dict]) -> None:
    """One interior zone per building, warped to from its doorway.

    The interior does not exist yet and will not until somebody opens the door,
    so its entry tile is derived rather than looked up — the same trick the
    compass gateways use, for the same reason.
    """
    slug = zone_id.replace("zone_", "", 1)
    for index, building in enumerate(buildings, start=1):
        role = building.get("role", "house")
        interior_id = f"zone_{slug}_in{index:02d}"
        width, height = INTERIOR_SIZES.get(role, INTERIOR_SIZES["house"])
        door_x, door_y = building["door"]

        layout.warps.append({
            "x": door_x, "y": door_y,
            "to_zone": interior_id,
            "to_x": width // 2, "to_y": height - 2,
        })
        layout.meta.setdefault("interiors", []).append({
            "id": interior_id,
            "role": role,
            "return_to": list(building["step_out"]),
        })


def _plaza(layout: Layout, roads: set, rng) -> None:
    """A well just off the crossroads, and scattered flowers for texture."""
    cx, cy = layout.meta["crossroads"]
    for offset in ((2, 2), (-2, 2), (2, -2), (-2, -2)):
        wx, wy = cx + offset[0], cy + offset[1]
        if layout.inside(wx, wy) and (wx, wy) not in roads and layout.decor[layout.index(wx, wy)] == EMPTY:
            layout.set_decor(wx, wy, FEATURE)
            layout.notes.append(f"well at ({wx},{wy})")
            break

    for _ in range(rng.randint(6, 14)):
        x = rng.randrange(1, layout.width - 1)
        y = rng.randrange(1, layout.height - 1)
        if (x, y) not in roads and layout.decor[layout.index(x, y)] == EMPTY:
            layout.set_decor(x, y, DETAIL, blocks=False)


# --- slots -----------------------------------------------------------------

def doorsteps(buildings: list[dict]) -> set:
    """Tiles that must stay clear: every door and the one tile you can stand on
    to enter it.

    A door sits in a building's wall face, so its only approach is the tile
    directly in front. Anything blocking that tile — an NPC counts, they block
    at runtime — makes the building permanently unenterable.
    """
    keep: set = set()
    for building in buildings:
        keep.add(tuple(building["door"]))
        keep.add(tuple(building["step_out"]))
    return keep


def _slots(layout: Layout, rng, buildings: list[dict], roads: set) -> None:
    """Proc-gen decides how many and where. Two of the buildings become a shop
    and an inn; the rest get someone standing outside the door."""
    taken: set = set(doorsteps(buildings))

    # Traders are inside their own buildings now, so everyone on the street is
    # simply someone who lives here. They stand *beside* the doorstep, never on
    # it: an NPC on the one approach tile walls the building shut.
    for building in buildings:
        sx, sy = building["step_out"]
        beside = [(sx + dx, sy + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
        rng.shuffle(beside)
        for x, y in beside:
            if not layout.walkable(x, y) or (x, y) in taken:
                continue
            taken.add((x, y))
            layout.slots.append(Slot(
                kind="npc", x=x, y=y,
                hint=f"on the street beside the door of the {building.get('role', 'house')}",
            ))
            break

    cx, cy = layout.meta["crossroads"]
    for _ in range(rng.randint(2, 3)):
        for _attempt in range(40):
            x = cx + rng.randint(-4, 5)
            y = cy + rng.randint(-4, 5)
            if layout.walkable(x, y) and (x, y) not in taken:
                taken.add((x, y))
                layout.slots.append(Slot(kind="npc", x=x, y=y, hint="on the market crossroads"))
                break

    for _ in range(rng.randint(1, 3)):
        for _attempt in range(60):
            x = rng.randrange(1, layout.width - 1)
            y = rng.randrange(1, layout.height - 1)
            if layout.walkable(x, y) and (x, y) not in roads and (x, y) not in taken:
                taken.add((x, y))
                layout.slots.append(Slot(kind="chest", x=x, y=y, hint="tucked behind the buildings"))
                break


def _warps(layout: Layout, world_seed: int, zone_id: str, exits: dict, zone_kinds: dict,
           gates: dict | None = None) -> None:
    for edge, target in exits.items():
        if edge not in EDGES:
            continue
        gx, gy = gateway(world_seed, zone_id, "town", edge)
        tx, ty = arrival(world_seed, target, zone_kinds.get(target, "dungeon"), _opposite_edge(edge))
        layout.warps.append(apply_gate({"x": gx, "y": gy, "to_zone": target, "to_x": tx, "to_y": ty}, gates))

        # A signpost beside the road out, if there is room for one.
        for sx, sy in ((gx - 1, gy + 1), (gx + 1, gy + 1), (gx - 1, gy - 1), (gx + 1, gy - 1)):
            if layout.walkable(sx, sy) and not any(s.x == sx and s.y == sy for s in layout.slots):
                layout.slots.append(Slot(kind="sign", x=sx, y=sy, hint=f"beside the {edge} road out of town"))
                break


def _opposite_edge(edge: str) -> str:
    return {"north": "south", "south": "north", "east": "west", "west": "east"}[edge]


def _spawn(layout: Layout, roads: set) -> None:
    cx, cy = layout.meta["crossroads"]
    for x, y in sorted(roads, key=lambda t: abs(t[0] - cx) + abs(t[1] - cy)):
        if layout.walkable(x, y) and not any(s.x == x and s.y == y for s in layout.slots):
            layout.spawn = (x, y)
            return
    layout.spawn = (cx, cy)
