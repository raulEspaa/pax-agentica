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
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 61)
    status = lobby.get(f"/api/t/{table}/status", headers={"X-Seat": anne}).json()
    assert status["turn"] == 2


def test_unsent_orders_are_carried_out_when_the_clock_runs_out(
    lobby: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    table, anne = open_table(lobby, turn_minutes=1)
    before = lobby.get(f"/api/t/{table}/game", headers={"X-Seat": anne}).json()
    paris = next(p for p in before["view"]["provinces"] if p["id"] == "paris")["troops"]
    r = lobby.post(f"/api/t/{table}/draft", json=RECRUIT, headers={"X-Seat": anne})
    assert r.json() == {"ok": True}
    assert lobby.post(f"/api/t/{table}/draft", json=RECRUIT).status_code in (401, 403)
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 61)
    after = lobby.get(f"/api/t/{table}/game", headers={"X-Seat": anne}).json()
    assert after["view"]["turn"] == 2
    assert next(p for p in after["view"]["provinces"] if p["id"] == "paris")["troops"] == paris + 1


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


def test_the_server_says_it_is_alive(lobby: TestClient) -> None:
    assert lobby.get("/api/health").json() == {"status": "ok"}


# ---------------------------------------------------------------- tables that end


def join(client: TestClient, table: str, nation: str, name: str = "Pedro") -> str:
    r = client.post(f"/api/t/{table}/join", json={"name": name, "nation": nation})
    assert r.status_code == 200, r.text
    return str(r.json()["token"])


def test_the_last_player_to_leave_closes_the_table(lobby: TestClient) -> None:
    table, anne = open_table(lobby)
    pedro = join(lobby, table, "spain")
    assert lobby.post(f"/api/t/{table}/leave", headers={"X-Seat": pedro}).json()["closed"] is None
    left = lobby.post(f"/api/t/{table}/leave", headers={"X-Seat": anne}).json()
    assert left["closed"] == "everyone left"
    assert (
        lobby.post(f"/api/t/{table}/join", json={"name": "Eve", "nation": "england"}).status_code
        == 410
    )
    listed = lobby.get("/api/lobby").json()["tables"][0]
    assert listed["closed"] == "everyone left"


def test_leaving_lets_the_others_go_on(lobby: TestClient) -> None:
    table, anne = open_table(lobby)
    pedro = join(lobby, table, "spain")
    lobby.post(f"/api/t/{table}/turn", json=RECRUIT, headers={"X-Seat": anne})
    lobby.post(f"/api/t/{table}/leave", headers={"X-Seat": pedro})  # Anne was waiting for him
    game = lobby.get(f"/api/t/{table}/game", headers={"X-Seat": anne}).json()
    assert game["view"]["turn"] == 2
    assert game["rulers"]["spain"] == "greedy"


def test_patience_runs_out_for_the_absent(
    lobby: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    table, anne = open_table(lobby)
    join(lobby, table, "spain")
    lobby.post(f"/api/t/{table}/turn", json=RECRUIT, headers={"X-Seat": anne})
    assert lobby.post(f"/api/t/{table}/force", headers={"X-Seat": anne}).status_code == 409
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 601)
    assert lobby.get(f"/api/t/{table}/status", headers={"X-Seat": anne}).json()["force_in"] == 0
    forced = lobby.post(f"/api/t/{table}/force", headers={"X-Seat": anne}).json()
    assert forced["view"]["turn"] == 2


def test_abandoned_and_finished_tables_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = TestClient(create_lobby_app(tmp_path, invite_code=""))
    table, _ = open_table(client)
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 4 * 24 * 3600)
    lobby = client.app.state.lobby  # type: ignore[attr-defined]
    lobby.sweep(force=True)
    assert lobby.summaries[table]["closed"] == "abandoned"
    monkeypatch.setattr(time, "time", lambda: now + 12 * 24 * 3600)
    lobby.sweep(force=True)
    assert table not in lobby.summaries  # a week after closing, gone
    assert not (tmp_path / f"{table}.json").exists()


def test_tables_load_when_opened_and_keep_answers_across_restarts(tmp_path: Path) -> None:
    first = TestClient(create_lobby_app(tmp_path, invite_code=""))
    table, anne = open_table(first)
    join(first, table, "spain")
    first.post(f"/api/t/{table}/turn", json=RECRUIT, headers={"X-Seat": anne})
    again = TestClient(create_lobby_app(tmp_path, invite_code=""))
    lobby = again.app.state.lobby  # type: ignore[attr-defined]
    assert table in lobby.summaries
    assert table not in lobby.tables  # nothing read yet
    status = again.get(f"/api/t/{table}/status", headers={"X-Seat": anne}).json()
    assert status["submitted"] is True  # Anne's answer survived the restart
    assert status["waiting_for"] == ["spain"]


def test_views_travel_compressed(lobby: TestClient) -> None:
    table, anne = open_table(lobby)
    r = lobby.get(f"/api/t/{table}/game", headers={"X-Seat": anne, "Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"


def test_testers_can_leave_a_note(lobby: TestClient, tmp_path: Path) -> None:
    r = lobby.post(
        "/api/feedback", json={"text": "The map is lovely.", "nation": "france", "year": 1503}
    )
    assert r.status_code == 200
    notes = list((tmp_path / "feedback").glob("*.json"))
    assert len(notes) == 1
    assert "lovely" in notes[0].read_text()
    assert lobby.post("/api/feedback", json={"text": ""}).status_code == 422


def test_an_invitation_code_forgives_case_spaces_and_a_stray_percent(tmp_path: Path) -> None:
    client = TestClient(create_lobby_app(tmp_path, invite_code="pikes42\n"))
    body = {"name": "Anne", "nation": "france"}
    for typed in ("pikes42", " PIKES42 ", "pikes 42", "pikes42%"):
        assert client.post("/api/tables", json=body | {"code": typed}).status_code == 200, typed
    assert client.post("/api/tables", json=body | {"code": "pikes43"}).status_code == 403


def test_a_table_removed_by_hand_is_forgotten(tmp_path: Path) -> None:
    client = TestClient(create_lobby_app(tmp_path, invite_code=""))
    table, _ = open_table(client)
    for path in tmp_path.glob(f"{table}*.json"):
        path.unlink()
    client.app.state.lobby.sweep(force=True)  # type: ignore[attr-defined]
    assert client.get("/api/lobby").json()["tables"] == []


def test_the_lobby_can_check_a_code_as_it_is_typed(tmp_path: Path) -> None:
    client = TestClient(create_lobby_app(tmp_path, invite_code="pikes42"))
    assert client.post("/api/code", json={"code": "PIKES42"}).json() == {"ok": True}
    assert client.post("/api/code", json={"code": "nope"}).json() == {"ok": False}
