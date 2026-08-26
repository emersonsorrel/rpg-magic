"""FastAPI authoring service (design doc 2).

    "The backend is an authoring service, not a game loop. It has no notion of
    frames, input, or animation. It answers one primary question: give me the
    committed Zone Package for zone X, generating it if it does not yet exist."

It also serves the client's static files, so the whole thing runs from one
origin and one command.

    uvicorn backend.app:app --port 8000
    open http://127.0.0.1:8000/client/index.html
"""

from __future__ import annotations

import pathlib

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .world.authoring import UnknownZone, ZoneRejected, begin, get_or_generate
from .world.store import WorldStore

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SEED = 8471029

app = FastAPI(title="rpg-magic authoring service", version="0.2.0")


def store() -> WorldStore:
    return WorldStore("default")


@app.get("/api/world")
def get_world():
    """The ledger. Created on first request so the client needs no setup step."""
    s = store()
    if not s.exists():
        return begin(DEFAULT_SEED, s)
    return s.load_ledger()


@app.post("/api/new-game")
def new_game_endpoint(seed: int = DEFAULT_SEED, premise: str | None = None):
    """Discards the current world and starts another. Committed zones are
    permanent within a world, not across a deliberate restart."""
    s = store()
    s.reset()
    return begin(seed, s, premise)


@app.get("/api/zone/{zone_id}")
def get_zone(zone_id: str):
    s = store()
    if not s.exists():
        begin(DEFAULT_SEED, s)
    ledger = s.load_ledger()
    try:
        package = get_or_generate(ledger, zone_id, s)
    except UnknownZone:
        raise HTTPException(status_code=404, detail=f"no zone '{zone_id}' in the ledger")
    except ZoneRejected as rejected:
        # The generator produced something the validator refused. Never commit
        # it, and say exactly what was wrong.
        return JSONResponse(
            status_code=500,
            content={
                "error": "zone_rejected",
                "zone_id": rejected.zone_id,
                "issues": [
                    {"code": i.code, "path": i.path, "message": i.message}
                    for i in rejected.report.errors
                ],
            },
        )
    return package


@app.post("/api/world/position")
def set_position(zone: str, x: int, y: int):
    """Persist where the player is standing, so a reload resumes in place."""
    s = store()
    ledger = s.load_ledger()
    if zone not in ledger["zones"]:
        raise HTTPException(status_code=404, detail=f"no zone '{zone}'")
    ledger["player_position"] = {"zone": zone, "x": x, "y": y}
    s.save_ledger(ledger)
    return ledger["player_position"]


# Mounted last so /api/* wins. The client is plain static files.
app.mount("/", StaticFiles(directory=str(ROOT), html=False), name="static")
