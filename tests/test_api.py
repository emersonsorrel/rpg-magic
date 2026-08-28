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


def test_registries_are_served_to_the_client(client):
    """The battle engine runs client-side but the registries stay backend-owned,
    so there is one definition of what a Potion does."""
    registries = client.get("/api/registries").json()
    for section in ("items", "skills", "encounters", "templates"):
        assert registries[section], f"{section} came back empty"
    assert "potion" in registries["items"]
    assert "mine_rats" in registries["encounters"]


def test_progress_is_persisted(client):
    ledger = client.get("/api/world").json()
    party = ledger["party"]
    party[0]["level"] += 1
    party[0]["xp"] = 7

    assert client.post("/api/world/state", json={"party": party}).status_code == 200
    saved = client.get("/api/world").json()
    assert saved["party"][0]["level"] == party[0]["level"]
    assert saved["party"][0]["xp"] == 7


def test_an_impossible_party_is_refused(client):
    """Player progress is the only part of a committed world ever rewritten, so
    it is the one place a bad write could corrupt a save."""
    ledger = client.get("/api/world").json()
    broken = [dict(ledger["party"][0], hp=9999)]

    response = client.post("/api/world/state", json={"party": broken})
    assert response.status_code == 422
    assert any(issue["code"] == "bad_party_state" for issue in response.json()["detail"])
    assert client.get("/api/world").json()["party"][0]["hp"] != 9999


def test_a_zone_package_never_references_an_encounter_that_does_not_exist(client):
    registries = client.get("/api/registries").json()
    pending = list(client.get("/api/world").json()["zones"])
    seen: set[str] = set()
    while pending:
        zone_id = pending.pop(0)
        if zone_id in seen:
            continue
        seen.add(zone_id)
        package = client.get(f"/api/zone/{zone_id}").json()
        for row in package["encounters"]["table"]:
            assert row["encounter_id"] in registries["encounters"]
        pending.extend(z for z in client.get("/api/world").json()["zones"] if z not in seen)


def test_a_world_can_be_saved_and_loaded_back(client):
    """Design doc M5: save/load via ledger serialization. The ledger is the save,
    but a world is the ledger plus its committed packages."""
    client.get("/api/world")
    assert client.post("/api/saves/before the mine").status_code == 200

    party = client.get("/api/world").json()["party"]
    party[0]["level"] += 5
    client.post("/api/world/state", json={"party": party})
    assert client.get("/api/world").json()["party"][0]["level"] == party[0]["level"]

    client.post("/api/saves/before the mine/load")
    restored = client.get("/api/world").json()["party"][0]["level"]
    assert restored == party[0]["level"] - 5


def test_a_save_keeps_its_committed_zones(client):
    """Committed is permanent, so a reload must bring back the same zones rather
    than regenerating them."""
    town = client.get("/api/zone/zone_town_01").json()
    client.post("/api/saves/snapshot")
    client.post("/api/saves/snapshot/load")
    assert client.get("/api/zone/zone_town_01").json() == town


def test_saves_are_listed_with_enough_to_choose_between_them(client):
    client.get("/api/world")
    client.post("/api/saves/one")
    saves = {s["name"]: s for s in client.get("/api/saves").json()["saves"]}
    assert "one" in saves and "default" in saves
    assert saves["default"]["active"] is True
    assert saves["one"]["party"], "a save with no party is not much use to pick between"
    assert saves["one"]["committed_zones"] >= 1


def test_a_save_name_cannot_escape_the_saves_directory(client):
    client.get("/api/world")
    for bad in ("../etc", "default", "with/slash", ""):
        assert client.post(f"/api/saves/{bad}").status_code in (400, 404, 405)


def test_a_failed_outline_still_leaves_a_valid_world(client, monkeypatch):
    """The bug that started this: a failed outline call added a top-level key
    the schema forbids, the backend saved it anyway, and the client then refused
    to load the world with no way out."""
    from unittest.mock import patch

    from backend.llm.provider import LLMError

    async def boom(*_args, **_kwargs):
        raise LLMError("max_tokens exceeded")

    with patch("backend.world.authoring.authoring_enabled", return_value=True), \
         patch("backend.world.authoring.author_outline", boom):
        ledger = client.post("/api/new-game?seed=99").json()

    assert validate_ledger(ledger).ok, validate_ledger(ledger)
    assert client.get("/api/world").status_code == 200
    assert ledger["obligations"], "an unauthored world still needs its gate"


def test_an_invalid_ledger_is_never_written(client, tmp_path):
    """The ledger is the save file. Zone packages have always been gated this
    way; the ledger was not, which is how one bad write made a world
    permanently unloadable."""
    from backend.world.store import InvalidLedger, WorldStore

    store = WorldStore("guard", root=tmp_path)
    ledger = client.get("/api/world").json()
    ledger["notes"] = None

    with pytest.raises(InvalidLedger):
        store.save_ledger(ledger)
    assert not store.exists()


def test_a_world_damaged_by_an_older_build_is_repaired_on_load(client, tmp_path, monkeypatch):
    """Saves written before that guard existed must still open."""
    import json

    client.get("/api/world")
    path = client.app  # noqa: F841  (kept for clarity about what `client` drives)

    from backend.world.store import saves_root

    ledger_path = saves_root() / "default" / "ledger.json"
    stored = json.loads(ledger_path.read_text())
    stored["notes"] = None
    ledger_path.write_text(json.dumps(stored))

    response = client.get("/api/world")
    assert response.status_code == 200
    assert "notes" not in response.json()
    assert validate_ledger(response.json()).ok


def test_rerolling_replaces_a_damaged_world(client):
    """The recovery button's server side: it must work from any state."""
    import json

    from backend.world.store import saves_root

    client.get("/api/world")
    ledger_path = saves_root() / "default" / "ledger.json"
    ledger_path.write_text(json.dumps({"totally": "broken"}))

    rerolled = client.post("/api/new-game?seed=4242").json()
    assert validate_ledger(rerolled).ok
    assert rerolled["seed"] == 4242


def test_status_reports_who_is_authoring(client, monkeypatch):
    """Which model is answering should never be a guess."""
    monkeypatch.delenv("RPG_MAGIC_NO_LLM", raising=False)
    status = client.get("/api/status").json()["authoring"]
    assert set(status["roles"]) >= {"outline", "zone_author"}
    for role in status["roles"].values():
        assert role["provider"] and role["model"]


def test_status_says_when_authoring_is_switched_off(client, monkeypatch):
    """The bug this exists for: a stray RPG_MAGIC_NO_LLM in the server's
    environment turned every zone into placeholder content, and nothing on
    screen distinguished that from a model refusing to answer."""
    monkeypatch.setenv("RPG_MAGIC_NO_LLM", "1")
    status = client.get("/api/status").json()["authoring"]
    assert status["enabled"] is False
    assert "RPG_MAGIC_NO_LLM" in status["reason"]


def test_a_local_provider_reports_its_endpoint(client, monkeypatch, tmp_path):
    """So a misconfigured base_url is visible rather than silent."""
    import yaml

    config = tmp_path / "llm.yaml"
    config.write_text(yaml.safe_dump({"llm": {
        "enabled": True,
        "zone_author": {"provider": "lmstudio", "model": "some-model",
                        "base_url": "http://192.168.0.5:1234/v1"},
    }}))
    monkeypatch.delenv("RPG_MAGIC_NO_LLM", raising=False)
    monkeypatch.setattr("backend.llm.config.CONFIG_PATH", config)

    role = client.get("/api/status").json()["authoring"]["roles"]["zone_author"]
    assert role["base_url"] == "http://192.168.0.5:1234/v1"
    assert role["model"] == "some-model"
