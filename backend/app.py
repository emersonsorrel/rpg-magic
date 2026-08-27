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
import re

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from .validation.registries import load_registries
from .validation.schema import schema_hash
from .validation.validator import validate_ledger
from .world.authoring import UnknownZone, ZoneRejected, begin, get_or_generate
from .world.store import ACTIVE_SLOT, WorldStore, copy_slot, list_slots

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


@app.get("/api/registries")
def get_registries():
    """Items, skills, and the enemy bestiary.

    The battle engine runs in the client (design doc 2: the game stays playable
    with the backend offline), but the registries stay backend-owned so there is
    exactly one definition of what a Potion does. The client fetches them once.
    """
    reg = load_registries()
    return {
        "items": reg.items,
        "skills": reg.skills,
        "encounters": reg.encounters,
        "templates": reg.enemy_templates,
    }


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


@app.post("/api/world/state")
async def save_state(payload: dict = Body(...)):
    """Persist the mutable slice of the world: party, inventory, flags, position.

    Everything here is player progress, not authored content, so it is the only
    part of a committed world that is ever rewritten. The merged ledger is
    validated before it is written -- a battle that somehow produced a party
    member with more hp than max_hp should not become a save file.
    """
    s = store()
    async with _writing:
        ledger = s.load_ledger()
        merged = dict(ledger)
        for field in ("party", "inventory", "flags", "player_position", "obligations"):
            if field in payload:
                merged[field] = payload[field]

        report = validate_ledger(merged)
        if not report.ok:
            raise HTTPException(
                status_code=422,
                detail=[{"code": i.code, "path": i.path, "message": i.message} for i in report.errors],
            )
        s.save_ledger(merged)
    return {"saved": True}


SLOT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,40}$")


def _check_slot(name: str) -> str:
    """Slot names become directory names, so they are validated rather than
    trusted."""
    if not SLOT_PATTERN.match(name) or name == ACTIVE_SLOT:
        raise HTTPException(
            status_code=400,
            detail=f"'{name}' is not a usable save name (letters, digits, spaces, - and _; "
                   f"and not '{ACTIVE_SLOT}')",
        )
    return name


@app.get("/api/saves")
def get_saves():
    return {"saves": list_slots()}


@app.post("/api/saves/{name}")
async def save_to_slot(name: str):
    """Snapshot the running world under a name.

    A world is the ledger plus its committed packages: committed is permanent,
    so a save has to preserve the exact zones that world had rather than leaving
    them to be regenerated.
    """
    _check_slot(name)
    async with _writing:
        if not store().exists():
            raise HTTPException(status_code=404, detail="there is no world to save yet")
        copy_slot(ACTIVE_SLOT, name)
    return {"saved": name}


@app.post("/api/saves/{name}/load")
async def load_from_slot(name: str):
    _check_slot(name)
    async with _writing:
        try:
            copy_slot(name, ACTIVE_SLOT)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"no save named '{name}'")
        return store().load_ledger()


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
