"""Playing a nation through the web server: the same view and orders an AI ruler gets."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pax_agentica.runner import GameRecord
from pax_agentica.server import Session, create_app, default_session


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(default_session("france", seed=1, max_turns=3)))


def test_the_page_and_its_assets_are_served(client: TestClient) -> None:
    assert "play.js" in client.get("/").text
    assert client.get("/static/map.js").status_code == 200
    assert client.get("/static/secret.py").status_code == 404


def test_the_static_map_describes_every_province(client: TestClient) -> None:
    static = client.get("/api/static").json()
    assert len(static["provinces"]) == 104
    assert {b["id"] for b in static["buildings"]} >= {"marketplace", "fort", "lumber_mill"}


def test_the_human_only_sees_their_own_view(client: TestClient) -> None:
    game = client.get("/api/game").json()
    view = game["view"]
    assert game["human"] == "france"
    assert view["me"]["id"] == "france"
    troops = {p["id"]: p["troops"] for p in view["provinces"]}
    assert troops["paris"] is not None
    assert troops["moscow"] is None
    assert all("resources" not in n for n in view["nations"])


def test_ending_the_year_resolves_the_orders(client: TestClient) -> None:
    before = client.get("/api/game").json()["view"]
    paris = next(p for p in before["provinces"] if p["id"] == "paris")["troops"]
    orders = {"actions": [{"type": "recruit", "province": "paris", "regiments": 2}]}
    after = client.post("/api/turn", json=orders).json()["view"]
    assert after["turn"] == before["turn"] + 1
    assert next(p for p in after["provinces"] if p["id"] == "paris")["troops"] == paris + 2


def test_malformed_orders_are_refused_before_the_engine(client: TestClient) -> None:
    bad = {"actions": [{"type": "recruit", "province": "paris", "regiments": -3}]}
    assert client.post("/api/turn", json=bad).status_code == 422
    assert client.get("/api/game").json()["view"]["turn"] == 1


def test_illegal_orders_come_back_with_a_reason(client: TestClient) -> None:
    orders = {"actions": [{"type": "develop", "province": "london"}]}
    view = client.post("/api/turn", json=orders).json()["view"]
    reasons = [
        e["data"]["reason"] for e in view["last_turn_events"] if e["kind"] == "order_rejected"
    ]
    assert reasons == ["you do not own London"]


def test_the_replay_and_the_end_of_the_game(client: TestClient) -> None:
    assert client.get("/replay").status_code == 404
    for _ in range(3):
        game = client.post("/api/turn", json={"actions": []}).json()
    assert game["finished"]
    assert game["winner"]
    assert "<svg" in client.get("/replay").text
    assert client.post("/api/turn", json={"actions": []}).status_code == 409


def test_the_page_previews_what_each_work_would_add(client: TestClient) -> None:
    previews = client.get("/api/game").json()["previews"]
    assert set(previews) == {
        "paris",
        "lyon",
        "brittany",
        "champagne",
        "gascony",
        "languedoc",
        "normandy",
        "burgundy",
    }
    paris = previews["paris"]
    assert paris["buildings"]["marketplace"]["ducats"] > 0  # it doubles the province's ducats
    assert paris["develop"]["ducats"] >= 1


def test_a_saved_game_resumes_exactly_where_it_stopped(tmp_path: Path) -> None:
    save = tmp_path / "france-1.json"
    session = default_session("france", seed=1, max_turns=5)
    session.save_to = save
    client = TestClient(create_app(session))
    orders = {"actions": [{"type": "develop", "province": "lyon"}]}
    client.post("/api/turn", json=orders)
    client.post("/api/turn", json={"actions": []})
    record = GameRecord.model_validate_json(save.read_text(encoding="utf-8"))
    resumed = Session.resume(record, "france", session.rulers)
    assert resumed.state == session.state
    assert resumed.state.provinces["lyon"].development == 4
