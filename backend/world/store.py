"""Ledger and committed-package persistence.

JSON on disk (design doc 3.1: "Persisted as JSON (v1) -- Postgres/SQLite later
if needed"). A committed package is written once and never rewritten, which is
open question 2's answer made physical.
"""

from __future__ import annotations

import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def saves_root() -> pathlib.Path:
    """Overridable so tests never write into a real world."""
    return pathlib.Path(os.environ.get("RPG_MAGIC_SAVES", ROOT / "saves"))


class WorldStore:
    def __init__(self, slot: str = "default", root: pathlib.Path | None = None):
        self.dir = (root or saves_root()) / slot
        self.zones_dir = self.dir / "zones"

    # --- ledger ------------------------------------------------------------

    @property
    def ledger_path(self) -> pathlib.Path:
        return self.dir / "ledger.json"

    def exists(self) -> bool:
        return self.ledger_path.exists()

    def load_ledger(self) -> dict:
        return json.loads(self.ledger_path.read_text())

    def save_ledger(self, ledger: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path.write_text(json.dumps(ledger, indent=2) + "\n")

    # --- packages ----------------------------------------------------------

    def package_path(self, zone_id: str) -> pathlib.Path:
        return self.zones_dir / f"{zone_id}.json"

    def has_package(self, zone_id: str) -> bool:
        return self.package_path(zone_id).exists()

    def load_package(self, zone_id: str) -> dict:
        return json.loads(self.package_path(zone_id).read_text())

    def save_package(self, package: dict) -> None:
        self.zones_dir.mkdir(parents=True, exist_ok=True)
        path = self.package_path(package["id"])
        if path.exists():
            raise FileExistsError(
                f"{package['id']} is already committed; committed zones are never re-authored"
            )
        path.write_text(json.dumps(package, indent=2) + "\n")

    def reset(self) -> None:
        import shutil

        if self.dir.exists():
            shutil.rmtree(self.dir)


# --- named saves -----------------------------------------------------------
#
# The ledger is the save file (design doc 3.1), but a world is the ledger *plus*
# its committed packages: committed is permanent, so reloading a save has to
# bring back the exact zones that world had, not regenerate them.

ACTIVE_SLOT = "default"


def list_slots(root: pathlib.Path | None = None) -> list[dict]:
    base = root or saves_root()
    if not base.exists():
        return []
    slots = []
    for entry in sorted(base.iterdir()):
        ledger_path = entry / "ledger.json"
        if not entry.is_dir() or not ledger_path.exists():
            continue
        try:
            ledger = json.loads(ledger_path.read_text())
        except json.JSONDecodeError:
            continue
        slots.append({
            "name": entry.name,
            "active": entry.name == ACTIVE_SLOT,
            "seed": ledger.get("seed"),
            "premise": (ledger.get("premise") or "")[:160],
            "zone": ledger.get("player_position", {}).get("zone"),
            "party": [
                {"name": m.get("name"), "level": m.get("level")}
                for m in ledger.get("party", [])
            ],
            "committed_zones": sum(
                1 for z in ledger.get("zones", {}).values() if z.get("committed")
            ),
            "updated": ledger_path.stat().st_mtime,
        })
    return slots


def copy_slot(source: str, target: str, root: pathlib.Path | None = None) -> None:
    """Duplicate a whole world -- ledger and every committed package."""
    import shutil

    base = root or saves_root()
    src, dst = base / source, base / target
    if not (src / "ledger.json").exists():
        raise FileNotFoundError(f"no save named '{source}'")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
