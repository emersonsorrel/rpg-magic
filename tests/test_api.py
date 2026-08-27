"""The authoring service's contract with the client (design doc 2).

    "It answers one primary question: give me the committed Zone Package for
    zone X, generating it if it does not yet exist."
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.validation.validator import validate_ledger, validate_zone_package


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Each test gets its own world on disk...
    monkeypatch.setenv("RPG_MAGIC_SAVES", str(tmp_path))
    # ...and none of them may call an LLM. These assert the service's contract,
    # not the model's prose.
    monkeypatch.setenv("RPG_MAGIC_NO_LLM", "1")
    # TestClient starts a non-daemon anyio portal thread on first request. Left
    # unclosed it outlives the test and hangs interpreter shutdown.
    with TestClient(app) as started:
        yield started


def test_world_is_created_on_first_request(client):
    ledger = client.get("/api/world").json()
    assert validate_ledger(ledger).ok, validate_ledger(ledger)
    assert ledger["player_position"]["zone"] == "zone_town_01"


def test_the_starting_town_is_committed_and_the_player_stands_in_it(client):
    ledger = client.get("/api/world").json()
    town = client.get("/api/zone/zone_town_01").json()
    x, y = ledger["player_position"]["x"], ledger["player_position"]["y"]
    assert ledger["zones"]["zone_town_01"]["committed"] is True
    # The spawn the generator chose, not a guess made before it ran.
    assert town["layers"]["collision"][y * town["width"] + x] == 0


def test_an_uncommitted_zone_is_generated_on_demand(client):
    ledger = client.get("/api/world").json()
    assert ledger["zones"]["zone_mine_b2"]["committed"] is False

    package = client.get("/api/zone/zone_mine_b2").json()
    assert package["id"] == "zone_mine_b2"
    assert validate_zone_package(package, client.get("/api/world").json()).ok

    assert client.get("/api/world").json()["zones"]["zone_mine_b2"]["committed"] is True


def test_a_committed_zone_comes_back_byte_identical(client):
    first = client.get("/api/zone/zone_mine_b1").json()
    second = client.get("/api/zone/zone_mine_b1").json()
    assert first == second


def test_unknown_zone_is_404(client):
    assert client.get("/api/zone/zone_atlantis").status_code == 404


def test_new_game_with_the_same_seed_rebuilds_the_same_world(client):
    first = client.post("/api/new-game?seed=4242").json()
    town_a = client.get("/api/zone/zone_town_01").json()
    second = client.post("/api/new-game?seed=4242").json()
    town_b = client.get("/api/zone/zone_town_01").json()

    assert first["seed"] == second["seed"] == 4242
    assert town_a["layers"] == town_b["layers"]
    assert town_a["entities"] == town_b["entities"]


def test_new_game_with_a_different_seed_builds_a_different_world(client):
    client.post("/api/new-game?seed=1")
    town_a = client.get("/api/zone/zone_town_01").json()
    client.post("/api/new-game?seed=2")
    town_b = client.get("/api/zone/zone_town_01").json()
    assert town_a["layers"] != town_b["layers"]


def test_every_warp_points_at_a_zone_the_ledger_knows(client):
    """Committing a town registers an interior per building, so the zone graph
    grows as it is walked; re-read the ledger rather than trusting a snapshot.

    A warp may target a compass exit or an interior behind a door — a town has
    one north road but eight front doors, which is why interiors are not in
    `exits`."""
    pending = list(client.get("/api/world").json()["zones"])
    seen: set[str] = set()

    while pending:
        zone_id = pending.pop(0)
        if zone_id in seen:
            continue
        seen.add(zone_id)

        package = client.get(f"/api/zone/{zone_id}").json()
        ledger = client.get("/api/world").json()
        zone = ledger["zones"][zone_id]
        reachable = set(zone.get("exits", {}).values()) | set(zone.get("interiors", []))

        for warp in package["warps"]:
            assert warp["to_zone"] in ledger["zones"], f"{zone_id} -> unknown {warp['to_zone']}"
            assert warp["to_zone"] in reachable, f"{zone_id} -> undeclared {warp['to_zone']}"

        pending.extend(z for z in ledger["zones"] if z not in seen)

    assert any(client.get("/api/world").json()["zones"][z]["kind"] == "interior" for z in seen)


def test_walking_through_every_warp_lands_on_open_ground(client):
    """The end-to-end version of the handshake: follow each warp into its
    target package and check the arrival tile is actually standable."""
    ledger = client.get("/api/world").json()
    packages = {zid: client.get(f"/api/zone/{zid}").json() for zid in ledger["zones"]}

    for zone_id, package in packages.items():
        for warp in package["warps"]:
            target = packages[warp["to_zone"]]
            index = warp["to_y"] * target["width"] + warp["to_x"]
            assert target["layers"]["collision"][index] == 0, (
                f"{zone_id} warps into solid ground at "
                f"({warp['to_x']},{warp['to_y']}) of {warp['to_zone']}"
            )


def test_position_survives_a_round_trip(client):
    client.get("/api/world")
    client.post("/api/world/position?zone=zone_mine_b1&x=20&y=34")
    assert client.get("/api/world").json()["player_position"] == {
        "zone": "zone_mine_b1", "x": 20, "y": 34
    }


def test_the_client_is_served_from_the_same_origin(client):
    """No CORS, one command to run the whole thing."""
    assert client.get("/client/index.html").status_code == 200
