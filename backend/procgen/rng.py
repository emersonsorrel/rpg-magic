"""Deterministic seeding.

Design doc 5: "Given (seed, zone_id, kind, constraints) it always produces the
same layout." That only holds if every random draw traces back to a stable hash
-- Python's built-in hash() is randomised per process, so it must never be used
here.
"""

from __future__ import annotations

import hashlib
import random


def derive(*parts: object) -> int:
    """A stable 64-bit integer from any combination of seed and string parts."""
    joined = "\x1f".join(str(part) for part in parts)
    digest = hashlib.blake2b(joined.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def zone_rng(world_seed: int, zone_id: str, purpose: str = "layout") -> random.Random:
    """A generator private to one (zone, purpose).

    Separate purposes get separate streams, so adding a draw to slot placement
    cannot shift the tiles that were already laid down.
    """
    return random.Random(derive(world_seed, zone_id, purpose))
