"""The drawn map (data/europe_1500.json) and the game's map must tell the same story."""

from pax_agentica.engine import GameState
from pax_agentica.viewer import europe_map


def test_every_province_is_drawn_inside_the_map(state: GameState) -> None:
    geo = europe_map()
    assert set(geo["provinces"]) == set(state.map.provinces)
    for shape in geo["provinces"].values():
        assert shape["d"].startswith("M")
        assert 0 < shape["x"] < geo["width"]
        assert 0 < shape["y"] < geo["height"]
        assert shape["area"] > 0


def test_provinces_that_touch_on_the_map_border_each_other_in_the_game(state: GameState) -> None:
    drawn = {
        tuple(sorted((a, b)))
        for a, b, _ in europe_map()["borders"]
        if a in state.map.provinces and b in state.map.provinces
    }
    straits = {
        tuple(sorted((a, n))) for a, p in state.map.provinces.items() for n in p.sea_neighbors
    }
    land = {tuple(sorted((a, n))) for a, p in state.map.provinces.items() for n in p.neighbors}
    assert drawn - straits == land
