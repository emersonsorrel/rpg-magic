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

import asyncio
import pathlib

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from .validation.schema import schema_hash
from .world.authoring import UnknownZone, ZoneRejected, begin, get_or_generate
from .world.store import WorldStore

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SEED = 8471029

app = FastAPI(title="rpg-magic authoring service", version="0.3.0")

# Generation reads the ledger, mutates it and writes it back, and a zone commit
# refuses to overwrite an existing package. Two requests arriving together --
# which is exactly what a client prefetching neighbours will do -- must not
# interleave. One writer at a time is plenty for a single-player local service.
_writing = asyncio.Lock()


def store() -> WorldStore:
    return WorldStore("default")


@app.get("/api/schema-version")
def get_schema_version():
    """Lets the client load its generated validator by content.

    /api responses are never cached, so this is the one fingerprint a stale
    browser cache cannot lie about.
    """
    return {"schema_hash": schema_hash()}


@app.get("/api/world")
async def get_world():
    """The ledger. Created on first request so the client needs no setup step."""
    s = store()
    async with _writing:
        if not s.exists():
            return await begin(DEFAULT_SEED, s)
        return s.load_ledger()


@app.post("/api/new-game")
async def new_game_endpoint(seed: int = DEFAULT_SEED, premise: str | None = None):
    """Discards the current world and starts another. Committed zones are
    permanent within a world, not across a deliberate restart."""
    s = store()
    async with _writing:
        s.reset()
        return await begin(seed, s, premise)


@app.get("/api/zone/{zone_id}")
async def get_zone(zone_id: str):
    s = store()
    try:
        async with _writing:
            if not s.exists():
                await begin(DEFAULT_SEED, s)
            ledger = s.load_ledger()
            package = await get_or_generate(ledger, zone_id, s)
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


class NoStoreStatic(StaticFiles):
    """Serve the client without letting the browser cache it.

    The client is unbundled ES modules, and one of them -- the generated schema
    validator -- is regenerated whenever a schema changes. A browser holding a
    stale copy of that module rejects perfectly good documents and reports it as
    a validation failure, which looks exactly like a backend bug. Twice was
    enough. This is a development server; correctness beats a warm cache.
    """

    def is_not_modified(self, response_headers, request_headers) -> bool:
        return False

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response


# Mounted last so /api/* wins. The client is plain static files.
app.mount("/", NoStoreStatic(directory=str(ROOT), html=False), name="static")
