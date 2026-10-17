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


def test_the_page_gets_the_reign_year_by_year_and_its_story() -> None:
    session = default_session("france", seed=1, max_turns=5)
    client = TestClient(create_app(session))
    client.post("/api/turn", json={"actions": [{"type": "declare_war", "target": "spain"}]})
    client.post("/api/turn", json={"actions": []})
    game = client.get("/api/game").json()
    history = game["history"]
    assert [row["year"] for row in history] == [1500, 1501, 1502]
    assert history[-1]["me"]["ruler"]
    assert set(history[-1]["me"]) >= {"development", "provinces", "income", "standing"}
    assert len(history[-1]["courts"]["spain"]) == 3  # others: only what Europe sees
    story = game["story"]
    assert any(m["kind"] == "war_declared" for m in story["milestones"])
    assert story["bonds"]["spain"]["wars"] == 1


def test_the_epilogue_lays_the_whole_game_open_only_once_it_is_over(client: TestClient) -> None:
    assert client.get("/api/game").json()["epilogue"] is None  # it would see through the fog
    for _ in range(3):
        game = client.post("/api/turn", json={"actions": []}).json()
    epilogue = game["epilogue"]
    assert epilogue["years"] == [1500, 1501, 1502, 1503]
    assert len(epilogue["owners"]) == 4
    assert len(epilogue["owners"][0]) == len(epilogue["provinces"]) == 104
    paris = epilogue["provinces"].index("paris")
    assert epilogue["owners"][0][paris] == "france"
    spain = epilogue["courts"]["spain"]
    assert len(spain["series"]["standing"]) == 4
    assert spain["series"]["provinces"][0] > 0
    gained = sum(c["gained"] for c in epilogue["courts"].values())
    changed = sum(
        a != b
        for before, after in zip(epilogue["owners"], epilogue["owners"][1:], strict=False)
        for a, b in zip(before, after, strict=True)
        if b
    )
    assert gained == changed


def test_the_press_kit_reel_follows_every_army_of_a_game_of_bots() -> None:
    from pax_agentica.press import create_press_app

    press = TestClient(create_press_app(seed=3, turns=6))
    assert "trailer" in press.get("/trailer").text.lower()
    assert press.get("/static/press.js").status_code == 200
    reel = press.get("/api/reel").json()
    assert reel["years"] == list(range(1500, 1507))
    assert len(reel["marches"]) == len(reel["headlines"]) == 6
    assert len(reel["owners"][0]) == 104
    marches = [m for year in reel["marches"] for m in year]
    assert marches  # six years of bots never stay home
    assert all(m["from"] in reel["provinces"] and m["to"] in reel["provinces"] for m in marches)
    assert press.get("/api/reel", params={"turns": 200}).status_code == 422
