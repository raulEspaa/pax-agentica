"""Buildings with levels: an upgrade does more and eats more, and forts gain walls."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, Resources, view_for
from pax_agentica.engine.actions import Build, UpgradeBuilding
from pax_agentica.engine.mechanics import (
    building_consumes,
    inputs_upkeep,
    output_with,
    province_output,
    upgrade_cost,
)
from pax_agentica.engine.model import BuildingKind

type Play = Callable[..., GameState]
M = BuildingKind.MARKETPLACE


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def rich(state: GameState) -> GameState:
    state.nations["england"].resources = Resources(
        ducats=2000, timber=200, iron=200, goods=50, grain=200, manpower=50
    )
    return state


def test_an_upgrade_does_more_and_eats_more(state: GameState, play: Play) -> None:
    built = play(rich(state), england=[Build(province="london", building=M)])
    one = province_output(built, "london").ducats
    up = play(built, england=[UpgradeBuilding(province="london", building=M)])
    london = up.provinces["london"]
    assert london.level(M) == 2
    assert province_output(up, "london").ducats > one
    assert building_consumes(up.rules, M, 2).goods > building_consumes(up.rules, M, 1).goods
    assert inputs_upkeep(up, "england").goods == building_consumes(up.rules, M, 2).goods
    view = view_for(up, "england")
    assert next(p for p in view.provinces if p.id == "london").building_levels[M] == 2


def test_an_upgrade_costs_and_has_limits(state: GameState, play: Play) -> None:
    rules = state.rules
    assert upgrade_cost(rules, M, 3).ducats > upgrade_cost(rules, M, 2).ducats
    built = play(rich(state), england=[Build(province="london", building=M)])
    twice = play(
        built,
        england=[
            UpgradeBuilding(province="london", building=M),
            UpgradeBuilding(province="london", building=M),
            UpgradeBuilding(province="london", building=BuildingKind.STABLES),
        ],
    )
    assert twice.provinces["london"].level(M) == 2
    assert reasons(twice) == [
        "the marketplace of London is already being upgraded this year",
        "London has no stables to upgrade",
    ]
    idle_year = play(built)
    assert twice.nations["england"].resources.ducats < idle_year.nations["england"].resources.ducats
    top = play(twice, england=[UpgradeBuilding(province="london", building=M)])
    again = play(top, england=[UpgradeBuilding(province="london", building=M)])
    assert reasons(again) == ["the marketplace of London is at its highest level (3)"]


def test_the_preview_matches_the_engine(state: GameState, play: Play) -> None:
    built = play(rich(state), england=[Build(province="london", building=M)])
    expected = output_with(built, "london", upgrade=M)
    up = play(built, england=[UpgradeBuilding(province="london", building=M)])
    assert output_with(up, "london") == expected


def test_a_stronger_fort_is_another_wall(state: GameState, play: Play) -> None:
    vienna = state.provinces["vienna"]
    assert vienna.fort == 1
    state.nations["austria"].resources = Resources(ducats=500, iron=100, timber=100)
    up = play(state, austria=[UpgradeBuilding(province="vienna", building=BuildingKind.FORT)])
    assert up.provinces["vienna"].fort == 2
