"""Dungeon floor generator (design doc 5).

    BSP rooms -> corridor connection -> guarantee connectivity
    -> chest slots in dead ends -> stairs/warps

Connectivity is not hoped for, it is enforced: after carving, any leftover
components are joined until a single one remains. A dungeon that strands its
own stairs is the exact failure the obligation machinery exists to prevent, and
it is cheap to rule out here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .layout import (
    BARRIER, DETAIL, EDGES, EMPTY, FLOOR, PATH, STAIRS_DOWN, STAIRS_UP, WALL,
    WATER, Layout, Slot, arrival, gateway, interior_anchor, interior_arrival,
    zone_size,
)
from .rng import zone_rng

TILESET = "mine_damp"
MIN_LEAF = 9
MIN_ROOM = 4


@dataclass
class Leaf:
    x: int
    y: int
    w: int
    h: int
    left: "Leaf | None" = None
    right: "Leaf | None" = None
    room: tuple[int, int, int, int] | None = None

    @property
    def is_leaf(self) -> bool:
        return self.left is None and self.right is None

    def rooms(self) -> list[tuple[int, int, int, int]]:
        if self.is_leaf:
            return [self.room] if self.room else []
        return (self.left.rooms() if self.left else []) + (self.right.rooms() if self.right else [])


def generate(world_seed: int, zone_id: str, exits: dict[str, str], zone_kinds: dict[str, str]) -> Layout:
    width, height = zone_size(world_seed, zone_id, "dungeon")
    layout = Layout(width=width, height=height, tileset=TILESET)
    layout.fill_ground(FLOOR)

    rng = zone_rng(world_seed, zone_id, "dungeon")

    # Start solid; everything below carves into it.
    for y in range(height):
        for x in range(width):
            layout.set_decor(x, y, WALL)

    root = Leaf(1, 1, width - 2, height - 2)
    _split(root, rng, 0)
    for leaf in _leaves(root):
        _carve_room(layout, leaf, rng)
    _connect(layout, root, rng)

    anchors = _stairs_and_gates(layout, world_seed, zone_id, exits, rng)
    _ensure_connected(layout, anchors)
    _decorate(layout, rng)
    _slots(layout, root, rng, anchors)
    _warps(layout, world_seed, zone_id, exits, zone_kinds)
    _spawn(layout, world_seed, zone_id, exits, anchors)

    return layout


# --- BSP -------------------------------------------------------------------

def _split(leaf: Leaf, rng, depth: int) -> None:
    if depth >= 4 or (leaf.w < MIN_LEAF * 2 and leaf.h < MIN_LEAF * 2):
        return
    horizontal = leaf.w < leaf.h
    if leaf.w > leaf.h * 1.25:
        horizontal = False
    elif leaf.h > leaf.w * 1.25:
        horizontal = True

    extent = leaf.h if horizontal else leaf.w
    if extent < MIN_LEAF * 2:
        return
    cut = rng.randint(MIN_LEAF, extent - MIN_LEAF)

    if horizontal:
        leaf.left = Leaf(leaf.x, leaf.y, leaf.w, cut)
        leaf.right = Leaf(leaf.x, leaf.y + cut, leaf.w, leaf.h - cut)
    else:
        leaf.left = Leaf(leaf.x, leaf.y, cut, leaf.h)
        leaf.right = Leaf(leaf.x + cut, leaf.y, leaf.w - cut, leaf.h)

    _split(leaf.left, rng, depth + 1)
    _split(leaf.right, rng, depth + 1)


def _leaves(node: Leaf) -> list[Leaf]:
    if node.is_leaf:
        return [node]
    return _leaves(node.left) + _leaves(node.right)


def _carve(layout: Layout, x: int, y: int, ground: int = FLOOR) -> None:
    if 0 < x < layout.width - 1 and 0 < y < layout.height - 1:
        layout.set_ground(x, y, ground)
        layout.set_decor(x, y, EMPTY, blocks=False)


def _carve_room(layout: Layout, leaf: Leaf, rng) -> None:
    max_w = min(leaf.w - 2, 10)
    max_h = min(leaf.h - 2, 8)
    if max_w < MIN_ROOM or max_h < MIN_ROOM:
        return
    w = rng.randint(MIN_ROOM, max_w)
    h = rng.randint(MIN_ROOM, max_h)
    x = leaf.x + rng.randint(1, leaf.w - w - 1)
    y = leaf.y + rng.randint(1, leaf.h - h - 1)
    leaf.room = (x, y, w, h)
    for cx, cy in layout.rect(x, y, w, h):
        _carve(layout, cx, cy)


def _centre(room: tuple[int, int, int, int]) -> tuple[int, int]:
    x, y, w, h = room
    return x + w // 2, y + h // 2


def _corridor(layout: Layout, a: tuple[int, int], b: tuple[int, int], rng) -> None:
    (ax, ay), (bx, by) = a, b
    if rng.random() < 0.5:
        for x in range(min(ax, bx), max(ax, bx) + 1):
            _carve(layout, x, ay, PATH)
        for y in range(min(ay, by), max(ay, by) + 1):
            _carve(layout, bx, y, PATH)
    else:
        for y in range(min(ay, by), max(ay, by) + 1):
            _carve(layout, ax, y, PATH)
        for x in range(min(ax, bx), max(ax, bx) + 1):
            _carve(layout, x, by, PATH)


def _connect(layout: Layout, node: Leaf, rng) -> None:
    if node.is_leaf:
        return
    _connect(layout, node.left, rng)
    _connect(layout, node.right, rng)
    left_rooms = node.left.rooms()
    right_rooms = node.right.rooms()
    if left_rooms and right_rooms:
        _corridor(layout, _centre(rng.choice(left_rooms)), _centre(rng.choice(right_rooms)), rng)


# --- stairs, gateways, and the connectivity guarantee ----------------------

def _stairs_and_gates(layout: Layout, world_seed: int, zone_id: str, exits: dict, rng) -> list[tuple[int, int]]:
    """Carve the tiles other zones have already been told about. These are
    derived, not chosen, so a neighbour committed before this floor existed
    still points at the right tile."""
    anchors: list[tuple[int, int]] = []

    for edge, _target in exits.items():
        if edge in EDGES:
            gx, gy = gateway(world_seed, zone_id, "dungeon", edge)
            ax, ay = arrival(world_seed, zone_id, "dungeon", edge)
            _carve(layout, gx, gy, PATH)
            layout.block(gx, gy, False)
            _carve(layout, ax, ay, PATH)
            # Drive a shaft inward until it breaks into carved ground.
            step = {"north": (0, 1), "south": (0, -1), "west": (1, 0), "east": (-1, 0)}[edge]
            x, y = ax, ay
            for _ in range(max(layout.width, layout.height)):
                nx, ny = x + step[0], y + step[1]
                if not (0 < nx < layout.width - 1 and 0 < ny < layout.height - 1):
                    break
                if layout.walkable(nx, ny):
                    break
                _carve(layout, nx, ny, PATH)
                x, y = nx, ny
            anchors.append((ax, ay))
            layout.meta.setdefault("gates", {})[edge] = (gx, gy)
        else:
            # up / down: a chamber around the derived anchor, stairs in it.
            cx, cy = interior_anchor(world_seed, zone_id, "dungeon", edge)
            for x, y in layout.rect(cx - 2, cy - 2, 5, 5):
                _carve(layout, x, y)
            tile = STAIRS_DOWN if edge == "down" else STAIRS_UP
            layout.set_decor(cx, cy, tile, blocks=False)
            layout.set_ground(cx, cy, PATH)
            anchors.append(interior_arrival(world_seed, zone_id, "dungeon", edge))
            layout.meta.setdefault("gates", {})[edge] = (cx, cy)

    return anchors


def _ensure_connected(layout: Layout, anchors: list[tuple[int, int]]) -> None:
    """Join every walkable component until one remains. Without this, a BSP
    corridor that happened to run along a room edge can leave a room orphaned."""
    for _ in range(64):
        components = _components(layout)
        if len(components) <= 1:
            break
        # Always grow the component holding the first anchor, so the entrance
        # stays part of the main body.
        anchor = next((a for a in anchors if layout.walkable(*a)), None)
        main = next((c for c in components if anchor in c), components[0])
        others = [c for c in components if c is not main]
        target = min(others, key=lambda c: _gap(main, c))
        a, b = _closest_pair(main, target)
        for x in range(min(a[0], b[0]), max(a[0], b[0]) + 1):
            _carve(layout, x, a[1], PATH)
        for y in range(min(a[1], b[1]), max(a[1], b[1]) + 1):
            _carve(layout, b[0], y, PATH)


def _components(layout: Layout) -> list[set]:
    remaining = layout.walkable_tiles()
    found = []
    while remaining:
        seed_tile = next(iter(remaining))
        component = layout.reachable_from(seed_tile)
        found.append(component)
        remaining -= component
    return found


def _gap(a: set, b: set) -> int:
    ax, ay = next(iter(a))
    return min(abs(ax - bx) + abs(ay - by) for bx, by in b)


def _closest_pair(a: set, b: set) -> tuple[tuple[int, int], tuple[int, int]]:
    best = None
    # Sampling keeps this cheap on big floors; exactness is not required, only
    # a short join.
    for pa in sorted(a)[:: max(1, len(a) // 60)]:
        for pb in sorted(b)[:: max(1, len(b) // 60)]:
            d = abs(pa[0] - pb[0]) + abs(pa[1] - pb[1])
            if best is None or d < best[0]:
                best = (d, pa, pb)
    return best[1], best[2]


# --- dressing and slots ----------------------------------------------------

def _decorate(layout: Layout, rng) -> None:
    for _ in range(rng.randint(8, 20)):
        x = rng.randrange(1, layout.width - 1)
        y = rng.randrange(1, layout.height - 1)
        if layout.walkable(x, y) and layout.decor[layout.index(x, y)] == EMPTY:
            if rng.random() < 0.35:
                layout.set_ground(x, y, WATER)
                layout.set_decor(x, y, DETAIL, blocks=False)
            else:
                layout.set_decor(x, y, BARRIER, blocks=False)


def _slots(layout: Layout, root: Leaf, rng, anchors: list[tuple[int, int]]) -> None:
    """Chests go in dead ends -- the rooms furthest from the entrance, which is
    where a player who explores deserves to be rewarded."""
    taken = {a for a in anchors}
    for gate in layout.meta.get("gates", {}).values():
        taken.add(tuple(gate))

    entrance = anchors[0] if anchors else (1, 1)
    rooms = root.rooms()
    ranked = sorted(
        rooms,
        key=lambda r: -(abs(_centre(r)[0] - entrance[0]) + abs(_centre(r)[1] - entrance[1])),
    )

    for room in ranked[: rng.randint(2, 3)]:
        for _ in range(30):
            x = room[0] + rng.randrange(room[2])
            y = room[1] + rng.randrange(room[3])
            if layout.walkable(x, y) and (x, y) not in taken:
                taken.add((x, y))
                layout.slots.append(Slot(kind="chest", x=x, y=y, hint="a dead end deep in the workings"))
                break

    for room in ranked[-2:]:
        for _ in range(30):
            x = room[0] + rng.randrange(room[2])
            y = room[1] + rng.randrange(room[3])
            if layout.walkable(x, y) and (x, y) not in taken:
                taken.add((x, y))
                layout.slots.append(Slot(kind="npc", x=x, y=y, hint="near the mine entrance"))
                break


def _warps(layout: Layout, world_seed: int, zone_id: str, exits: dict, zone_kinds: dict) -> None:
    opposite = {"north": "south", "south": "north", "east": "west", "west": "east",
                "up": "down", "down": "up"}
    for edge, target in exits.items():
        gx, gy = layout.meta["gates"][edge]
        target_kind = zone_kinds.get(target, "dungeon")
        back = opposite[edge]
        if edge in EDGES:
            tx, ty = arrival(world_seed, target, target_kind, back)
        else:
            tx, ty = interior_arrival(world_seed, target, target_kind, back)
        layout.warps.append({"x": gx, "y": gy, "to_zone": target, "to_x": tx, "to_y": ty})


def _spawn(layout: Layout, world_seed: int, zone_id: str, exits: dict, anchors: list) -> None:
    for candidate in anchors:
        if layout.walkable(*candidate):
            layout.spawn = candidate
            return
    layout.spawn = next(iter(sorted(layout.walkable_tiles())))
