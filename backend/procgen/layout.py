"""The grid a generator fills in, plus the tile vocabulary and the rules that
make two independently-generated zones agree on where their shared door is.

Tile indices mean the same thing in every tileset (see registries/tilesets.json),
so generators talk in terms of FLOOR and WALL, never in terms of grass or rock.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

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
