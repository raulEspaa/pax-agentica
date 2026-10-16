"""Several players at one table: seats, waiting for everyone, clocks and saved tables."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pax_agentica.multiplayer import create_lobby_app

RECRUIT = {"actions": [{"type": "recruit", "province": "paris", "regiments": 1}]}


@pytest.fixture
def lobby(tmp_path: Path) -> TestClient:
    return TestClient(create_lobby_app(tmp_path, invite_code=""))


def open_table(client: TestClient, nation: str = "france", **extra: object) -> tuple[str, str]:
    body = {"name": "Anne", "nation": nation, "seed": 3, "years": 10} | extra
    r = client.post("/api/tables", json=body)
    assert r.status_code == 200, r.text
    return r.json()["table"], r.json()["token"]


def test_a_table_waits_for_every_player(lobby: TestClient) -> None:
    table, anne = open_table(lobby)
    r = lobby.post(f"/api/t/{table}/join", json={"name": "Pedro", "nation": "spain"})
    pedro = r.json()["token"]
    first = lobby.post(f"/api/t/{table}/turn", json=RECRUIT, headers={"X-Seat": anne}).json()
    assert first["view"]["turn"] == 1
    assert first["submitted"] is True
    assert first["waiting_for"] == ["spain"]
    second = lobby.post(f"/api/t/{table}/turn", json={"actions": []}, headers={"X-Seat": pedro})
    assert second.json()["view"]["turn"] == 2
    assert second.json()["view"]["me"]["id"] == "spain"
    mine = lobby.get(f"/api/t/{table}/game", headers={"X-Seat": anne}).json()
    assert mine["view"]["me"]["id"] == "france"
    assert mine["humans"] == {"france": "Anne", "spain": "Pedro"}


def test_a_seat_needs_its_token(lobby: TestClient) -> None:
    table, _ = open_table(lobby)
    assert lobby.get(f"/api/t/{table}/game").status_code == 403
    assert lobby.get(f"/api/t/{table}/game", headers={"X-Seat": "guess"}).status_code == 403
    taken = lobby.post(f"/api/t/{table}/join", json={"name": "Eve", "nation": "france"})
    assert taken.status_code == 409


def test_the_lobby_lists_tables_and_their_seats(lobby: TestClient) -> None:
    table, _ = open_table(lobby, title="The Italian Wars")
    listed = lobby.get("/api/lobby").json()
    assert listed["tables"][0]["title"] == "The Italian Wars"
    france = next(n for n in listed["tables"][0]["nations"] if n["id"] == "france")
    assert france["player"] == "Anne"
    assert lobby.get(f"/t/{table}").status_code == 200
    assert f'PAX_TABLE = "{table}"' in lobby.get(f"/t/{table}").text


def test_tables_survive_a_restart(tmp_path: Path) -> None:
    first = TestClient(create_lobby_app(tmp_path, invite_code=""))
    table, anne = open_table(first)
    first.post(f"/api/t/{table}/turn", json=RECRUIT, headers={"X-Seat": anne})
    again = TestClient(create_lobby_app(tmp_path, invite_code=""))
    game = again.get(f"/api/t/{table}/game", headers={"X-Seat": anne}).json()
    assert game["view"]["turn"] == 2


def test_an_invitation_code_keeps_strangers_out(tmp_path: Path) -> None:
    client = TestClient(create_lobby_app(tmp_path, invite_code="pikes"))
    body = {"name": "Anne", "nation": "france"}
    assert client.post("/api/tables", json=body).status_code == 403
    assert client.post("/api/tables", json=body | {"code": "pikes"}).status_code == 200


def test_the_clock_ends_the_year_for_those_who_dawdle(
    lobby: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    table, anne = open_table(lobby, turn_minutes=1)
    now = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: now + 61)
    status = lobby.get(f"/api/t/{table}/status", headers={"X-Seat": anne}).json()
    assert status["turn"] == 2


def test_the_replay_waits_for_the_end(lobby: TestClient) -> None:
    table, anne = open_table(lobby)
    lobby.post(f"/api/t/{table}/turn", json=RECRUIT, headers={"X-Seat": anne})
    assert lobby.get(f"/t/{table}/replay").status_code == 403


def test_a_table_written_by_another_server_is_read_again(tmp_path: Path) -> None:
    old = TestClient(create_lobby_app(tmp_path, invite_code=""))
    new = TestClient(create_lobby_app(tmp_path, invite_code=""))  # a deploy: both run at once
    table, anne = open_table(old)
    old.post(f"/api/t/{table}/turn", json=RECRUIT, headers={"X-Seat": anne})
    game = new.get(f"/api/t/{table}/game", headers={"X-Seat": anne}).json()
    assert game["view"]["turn"] == 2
