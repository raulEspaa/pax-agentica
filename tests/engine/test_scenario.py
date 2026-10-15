"""The Europe 1500 map: a consistent graph and a fair-ish start."""

from collections import deque

from pax_agentica.engine import GameState, new_game
from pax_agentica.engine.scenario import EXTRA_GARRISON


def test_the_map_has_68_provinces_and_seven_great_powers(state: GameState) -> None:
    assert len(state.provinces) == 68
    assert sorted(state.nations) == [
        "austria",
        "england",
        "france",
        "ottomans",
        "russia",
        "spain",
        "sweden",
    ]


def test_borders_are_symmetric_and_never_both_land_and_sea(state: GameState) -> None:
    provinces = state.map.provinces
    for pid, p in provinces.items():
        assert pid not in p.neighbors + p.sea_neighbors
        assert not set(p.neighbors) & set(p.sea_neighbors)
        for n in p.neighbors:
            assert pid in provinces[n].neighbors, f"{pid}-{n}"
        for n in p.sea_neighbors:
            assert pid in provinces[n].sea_neighbors, f"{pid}~{n}"


def test_every_province_can_be_reached_from_any_other(state: GameState) -> None:
    start = next(iter(state.map.provinces))
    seen, queue = {start}, deque([start])
    while queue:
        for n in state.map.all_neighbors(queue.popleft()):
            if n not in seen:
                seen.add(n)
                queue.append(n)
    assert seen == set(state.map.provinces)


def test_every_nation_starts_with_its_capital_and_the_same_treasury(state: GameState) -> None:
    treasuries = {n.resources for n in state.nations.values()}
    assert len(treasuries) == 1
    for nation in state.nations.values():
        assert state.provinces[nation.capital].owner == nation.id


def test_no_great_power_starts_twice_as_developed_as_another(state: GameState) -> None:
    scores = [state.score(n) for n in state.nations]
    assert max(scores) <= 2 * min(scores)


def test_independent_minors_defend_themselves(state: GameState) -> None:
    for pid, p in state.provinces.items():
        if p.owner is None:
            assert p.troops == p.development + EXTRA_GARRISON.get(pid, 0)
    assert state.provinces["krakow"].troops > state.provinces["krakow"].development


def test_the_habsburgs_start_behind_walls(state: GameState) -> None:
    assert state.provinces["vienna"].fort == 1
    assert state.provinces["buda"].fort == 1


def test_a_new_game_is_the_same_for_the_same_seed() -> None:
    assert new_game(3) == new_game(3)
    assert new_game(3).seed != new_game(4).seed
