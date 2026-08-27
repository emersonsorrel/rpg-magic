"""The grid a generator fills in, plus the tile vocabulary and the rules that
make two independently-generated zones agree on where their shared door is.

Tile indices mean the same thing in every tileset (see registries/tilesets.json),
so generators talk in terms of FLOOR and WALL, never in terms of grass or rock.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace

from .rng import derive

# Ground layer
EMPTY = 0
FLOOR = 1
PATH = 2
WATER = 3
PLANKS = 4
DRY = 5

# Decor layer (0 is empty)
BLOCKER = 16
WALL = 17
DOOR = 18
FEATURE = 19
BARRIER = 20
ROOF = 21
DETAIL = 22
POST = 23
STAIRS_UP = 24
STAIRS_DOWN = 25

OPPOSITE = {
    "north": "south", "south": "north",
    "east": "west", "west": "east",
    "up": "down", "down": "up",
    "in": "out", "out": "in",
}

EDGES = ("north", "south", "east", "west")


@dataclass(frozen=True)
class Slot:
    """A place the generator has decided something belongs, without deciding
    what. Design doc 5: proc-gen decides how many and where; the LLM decides who
    and what. At M2 these are filled with placeholders instead."""

    kind: str  # npc | chest | sign | shop | inn
    x: int
    y: int
    hint: str = ""


@dataclass
class Layout:
    width: int
    height: int
    tileset: str
    ground: list[int] = field(default_factory=list)
    decor: list[int] = field(default_factory=list)
    collision: list[int] = field(default_factory=list)
    slots: list[Slot] = field(default_factory=list)
    warps: list[dict] = field(default_factory=list)
    spawn: tuple[int, int] = (0, 0)
    notes: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        size = self.width * self.height
        if not self.ground:
            self.ground = [FLOOR] * size
        if not self.decor:
            self.decor = [EMPTY] * size
        if not self.collision:
            self.collision = [0] * size

    # --- grid access -------------------------------------------------------

    def index(self, x: int, y: int) -> int:
        return y * self.width + x

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def walkable(self, x: int, y: int) -> bool:
        return self.inside(x, y) and not self.collision[self.index(x, y)]

    def set_ground(self, x: int, y: int, tile: int) -> None:
        if self.inside(x, y):
            self.ground[self.index(x, y)] = tile

    def set_decor(self, x: int, y: int, tile: int, *, blocks: bool | None = None) -> None:
        if not self.inside(x, y):
            return
        self.decor[self.index(x, y)] = tile
        if blocks is None:
            blocks = tile in (BLOCKER, WALL, DOOR, FEATURE, BARRIER, ROOF, POST)
        self.collision[self.index(x, y)] = 1 if blocks else 0

    def block(self, x: int, y: int, blocked: bool = True) -> None:
        if self.inside(x, y):
            self.collision[self.index(x, y)] = 1 if blocked else 0

    def fill_ground(self, tile: int) -> None:
        self.ground = [tile] * (self.width * self.height)

    def rect(self, x0: int, y0: int, w: int, h: int):
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                if self.inside(x, y):
                    yield x, y

    # --- connectivity ------------------------------------------------------

    def reachable_from(self, start: tuple[int, int]) -> set[tuple[int, int]]:
        if not self.walkable(*start):
            return set()
        seen = {start}
        queue = deque([start])
        while queue:
            x, y = queue.popleft()
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (nx, ny) not in seen and self.walkable(nx, ny):
                    seen.add((nx, ny))
                    queue.append((nx, ny))
        return seen

    def walkable_tiles(self) -> set[tuple[int, int]]:
        return {
            (x, y)
            for y in range(self.height)
            for x in range(self.width)
            if not self.collision[self.index(x, y)]
        }

    def is_fully_connected(self) -> bool:
        tiles = self.walkable_tiles()
        if not tiles:
            return False
        return self.reachable_from(next(iter(tiles))) == tiles


# --- the handshake between two lazily-generated zones ----------------------
#
# Zone A is committed before zone B exists, yet A's warp has to name the exact
# tile the player lands on in B. Patching A later is not an option -- committed
# is permanent (open question 2). So the arrival tile is made a pure function of
# (seed, zone_id, edge): both zones can compute it, and B's generator treats it
# as a constraint it must leave walkable and connected.


def zone_size(world_seed: int, zone_id: str, kind: str) -> tuple[int, int]:
    """Dimensions are derived, not stored, so a neighbour can reason about a
    zone that has not been generated yet."""
    rng = derive(world_seed, zone_id, "size")
    if kind == "town":
        return 32 + (rng % 5) * 2, 24 + ((rng >> 8) % 4) * 2
    if kind == "dungeon":
        return 40 + (rng % 5) * 2, 30 + ((rng >> 8) % 4) * 2
    return 32, 24


def gateway(world_seed: int, zone_id: str, kind: str, edge: str) -> tuple[int, int]:
    """The border tile on `edge` that a neighbour warps onto."""
    width, height = zone_size(world_seed, zone_id, kind)
    rng = derive(world_seed, zone_id, "gateway", edge)
    if edge in ("north", "south"):
        x = 3 + rng % max(1, width - 6)
        return x, (0 if edge == "north" else height - 1)
    y = 3 + rng % max(1, height - 6)
    return (0 if edge == "west" else width - 1), y


def arrival(world_seed: int, zone_id: str, kind: str, edge: str) -> tuple[int, int]:
    """Where the player actually stands after coming through `edge` -- one tile
    inward, so they do not immediately re-trigger the warp they arrived on."""
    x, y = gateway(world_seed, zone_id, kind, edge)
    step = {"north": (0, 1), "south": (0, -1), "west": (1, 0), "east": (-1, 0)}[edge]
    return x + step[0], y + step[1]


def interior_anchor(world_seed: int, zone_id: str, kind: str, edge: str) -> tuple[int, int]:
    """Stairs are not on a border, so up/down connections anchor on a derived
    interior tile instead. The generator carves a room around it."""
    width, height = zone_size(world_seed, zone_id, kind)
    rng = derive(world_seed, zone_id, "anchor", edge)
    x = 6 + rng % max(1, width - 12)
    y = 6 + (rng >> 16) % max(1, height - 12)
    return x, y


def interior_arrival(world_seed: int, zone_id: str, kind: str, edge: str) -> tuple[int, int]:
    """Arrival for an up/down connection: one tile below the stairs, so the
    player is not standing on the warp they just came through."""
    x, y = interior_anchor(world_seed, zone_id, kind, edge)
    return x, y + 1


def apply_gate(warp: dict, gates: dict | None) -> dict:
    """Attach a lock to a warp if this threshold is gated.

    `obligation_id` is bookkeeping for the engine and is not part of the Zone
    Package schema, so it is dropped on the way in.
    """
    gate = (gates or {}).get(warp["to_zone"])
    if gate:
        warp["locked"] = {k: v for k, v in gate.items() if k != "obligation_id"}
    return warp


def clear_blocking_slots(layout: "Layout", starts: list[tuple[int, int]], *, keep: set | None = None) -> int:
    """Move any slot that walls something off.

    Slots become entities, and entities block the tile they stand on. A chest in
    a one-tile corridor seals everything past it; an NPC on a road seals the way
    out of town. Neither shows up in a collision-only flood fill, because the
    collision layer says those tiles are open.

    Finding the culprit needs care: it is rarely next to the thing it blocks. So
    for anything unreachable, walk the collision-only shortest path to it and
    move whichever slots are standing on that path. Returns how many moved.
    """
    keep = keep or set()
    origin = next((p for p in starts if layout.walkable(*p)), None)
    if origin is None:
        return 0
    moved = 0

    for _attempt in range(24):
        occupied = {(slot.x, slot.y) for slot in layout.slots}
        reach = _fill(layout, origin, occupied)

        def touching(x: int, y: int) -> bool:
            return (x, y) in reach or any(
                n in reach for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
            )

        stranded = [(w["x"], w["y"]) for w in layout.warps if (w["x"], w["y"]) not in reach]
        stranded += [(s.x, s.y) for s in layout.slots if not touching(s.x, s.y)]
        if not stranded:
            return moved

        culprits: set = set()
        for target in stranded:
            for step in _path(layout, origin, target):
                if step in occupied and step != target:
                    culprits.add(step)
        if not culprits:
            return moved  # blocked by terrain, not by slots: not this pass's problem

        for index, slot in enumerate(layout.slots):
            if (slot.x, slot.y) not in culprits:
                continue
            spot = _open_spot(layout, reach, occupied | keep, near=(slot.x, slot.y))
            if spot is None:
                continue
            occupied.discard((slot.x, slot.y))
            occupied.add(spot)
            # Slot is frozen -- swap in a moved copy rather than mutating.
            layout.slots[index] = replace(slot, x=spot[0], y=spot[1])
            moved += 1
            layout.notes.append(f"moved a {slot.kind} slot off a chokepoint to {spot}")

    return moved


def _fill(layout: "Layout", origin, blocked: set) -> set:
    seen = {origin}
    queue = deque([origin])
    while queue:
        x, y = queue.popleft()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n not in seen and layout.walkable(*n) and n not in blocked:
                seen.add(n)
                queue.append(n)
    return seen


def _path(layout: "Layout", origin, target) -> list:
    """Shortest walkable route ignoring slots -- whatever sits on it is what is
    doing the blocking."""
    if not layout.walkable(*target):
        return []
    previous = {origin: None}
    queue = deque([origin])
    while queue:
        current = queue.popleft()
        if current == target:
            break
        x, y = current
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n not in previous and layout.walkable(*n):
                previous[n] = current
                queue.append(n)
    if target not in previous:
        return []
    route, step = [], target
    while step is not None:
        route.append(step)
        step = previous[step]
    return route


def _open_spot(layout: "Layout", reachable: set, taken: set, near=None) -> tuple[int, int] | None:
    """A reachable tile with room around it, as close to `near` as possible.

    Room to spare means re-placing cannot create the blockage it just fixed.
    Staying close means a villager moved off a doorway is still outside that
    house, rather than exiled to the far treeline.
    """
    def distance(spot):
        return abs(spot[0] - near[0]) + abs(spot[1] - near[1]) if near else 0

    roomy, adequate = [], []
    for x, y in reachable:
        if (x, y) in taken:
            continue
        room = sum(
            1 for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
            if layout.walkable(*n) and n not in taken
        )
        if room >= 3:
            roomy.append((x, y))
        elif room >= 2:
            adequate.append((x, y))

    for candidates in (roomy, adequate):
        if candidates:
            return min(sorted(candidates), key=distance)
    return None
