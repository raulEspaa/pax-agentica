"""The New World: expeditions, colonies, their dues, and taking them at war."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, view_for
from pax_agentica.engine.actions import DeclareWar, SeizeColony, SendExpedition
from pax_agentica.engine.mechanics import (
    colonial_dues,
    expedition_error,
    expedition_progress,
    nation_income,
)
from pax_agentica.engine.model import Expedition, Region, Resources, Ship, Water

type Play = Callable[..., GameState]

A = Water.ATLANTIC


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def test_spain_starts_with_hispaniola(state: GameState) -> None:
    assert state.nations["spain"].colonies == {Region.CARIBBEAN: 1}
    assert colonial_dues(state, "spain").ducats == 4
    caribbean = next(r for r in view_for(state, "france").new_world if r.id == Region.CARIBBEAN)
    assert caribbean.held == {"spain": 1}


def test_an_expedition_needs_a_port_an_escort_and_an_open_way(state: GameState) -> None:
    assert expedition_error(state, "austria", Region.CARIBBEAN) == (
        "you hold no port on the Atlantic or the Baltic"
    )
    assert "not known before 1532" in str(expedition_error(state, "spain", Region.PERU))
    state.nations["france"].fleets = {}
    assert "escort" in str(expedition_error(state, "france", Region.BRAZIL))
    assert expedition_error(state, "spain", Region.BRAZIL) is None


def test_an_expedition_founds_a_colony_in_a_few_years(state: GameState, play: Play) -> None:
    state.nations["england"].resources = Resources(ducats=200, manpower=20)
    new = play(state, england=[SendExpedition(region=Region.NORTH_AMERICA)])
    assert "not known before 1534" in reasons(new)[0]
    new = play(state, england=[SendExpedition(region=Region.CARIBBEAN)])
    assert len(new.nations["england"].expeditions) == 1
    for _ in range(6):
        if new.nations["england"].colonies:
            break
        new = play(new)
    assert new.nations["england"].colonies == {Region.CARIBBEAN: 1}
    assert nation_income(new, "england").ducats > nation_income(state, "england").ducats


def test_a_full_region_turns_expeditions_back(state: GameState, play: Play) -> None:
    state.nations["spain"].colonies = {Region.PERU: 1}
    state.nations["england"].colonies = {Region.PERU: 1}
    state.nations["france"].expeditions = [Expedition(region=Region.PERU, since=1, progress=90)]
    new = play(state)
    assert new.nations["france"].expeditions == []
    assert any(e.kind == EventKind.EXPEDITION_LOST for e in new.last_events)
    new.turn = 40  # 1539: the way to Peru is known
    assert "is full" in str(expedition_error(new, "spain", Region.PERU))


def test_crowns_sail_in_their_own_way(state: GameState) -> None:
    na = Region.NORTH_AMERICA
    assert expedition_progress(state, "france", na) > expedition_progress(state, "spain", na)
    state.nations["spain"].colonies = {Region.PERU: 1}
    state.nations["england"].colonies = {Region.PERU: 1}
    assert colonial_dues(state, "spain").ducats > colonial_dues(state, "england").ducats


def test_a_blockade_of_the_atlantic_stops_the_treasure_fleets(state: GameState, play: Play) -> None:
    new = play(state, england=[DeclareWar(target="spain")])
    before = colonial_dues(new, "spain").ducats
    new.nations["england"].fleets = {A: {Ship.GALLEON: 10}}
    new.nations["spain"].fleets = {A: {Ship.GALLEON: 1}}
    assert colonial_dues(new, "spain").ducats < before


def test_a_fleet_that_rules_the_ocean_takes_colonies(state: GameState, play: Play) -> None:
    new = play(state, england=[DeclareWar(target="spain")])
    new.nations["england"].fleets = {A: {Ship.GALLEON: 5}}
    new.nations["spain"].fleets = {A: {Ship.GALLEON: 3}}  # 12.5 against 7.5 x 1.5: enough
    taken = play(new, england=[SeizeColony(region=Region.CARIBBEAN, enemy="spain")])
    assert taken.nations["england"].colonies == {Region.CARIBBEAN: 1}
    assert taken.nations["spain"].colonies == {}
    new.nations["england"].fleets = {A: {Ship.GALLEON: 3}}
    kept = play(new, england=[SeizeColony(region=Region.CARIBBEAN, enemy="spain")])
    assert kept.nations["spain"].colonies == {Region.CARIBBEAN: 1}
    assert any("must be 1.5 times" in r for r in reasons(kept))
