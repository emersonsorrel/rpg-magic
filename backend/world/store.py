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
