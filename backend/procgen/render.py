"""ASCII view of a Layout. Debugging and test-failure output only -- the client
never sees this."""

from __future__ import annotations

from .layout import (
    BARRIER, BLOCKER, DETAIL, DOOR, FEATURE, PATH, PLANKS, POST, ROOF,
    STAIRS_DOWN, STAIRS_UP, WALL, WATER, Layout,
)

DECOR_CHARS = {
    BLOCKER: "T", WALL: "#", DOOR: "+", FEATURE: "o", BARRIER: "f",
    ROOF: "^", DETAIL: "*", POST: "i", STAIRS_UP: "<", STAIRS_DOWN: ">",
}
GROUND_CHARS = {PATH: ",", WATER: "~", PLANKS: "=" }
SLOT_CHARS = {"npc": "n", "chest": "c", "sign": "s", "shop": "$", "inn": "I"}


def to_ascii(layout: Layout, *, slots: bool = True, warps: bool = True) -> str:
    grid = []
    for y in range(layout.height):
        row = []
        for x in range(layout.width):
            i = layout.index(x, y)
            decor = layout.decor[i]
            if decor in DECOR_CHARS:
                row.append(DECOR_CHARS[decor])
            else:
                row.append(GROUND_CHARS.get(layout.ground[i], "."))
        grid.append(row)

    if slots:
        for slot in layout.slots:
            grid[slot.y][slot.x] = SLOT_CHARS.get(slot.kind, "?")
    if warps:
        for warp in layout.warps:
            grid[warp["y"]][warp["x"]] = "W"
    sx, sy = layout.spawn
    if layout.inside(sx, sy):
        grid[sy][sx] = "@"

    header = f"{layout.width}x{layout.height} {layout.tileset}  spawn={layout.spawn}"
    return header + "\n" + "\n".join("".join(row) for row in grid)
