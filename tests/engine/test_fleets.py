"""Fleets: ships in the three waters, straits, sea battles and blockades."""

from collections.abc import Callable

import pytest

from pax_agentica.engine import EventKind, GameState, view_for
from pax_agentica.engine.actions import (
    Attack,
    BuildShips,
    DeclareWar,
    SailFleet,
    ScrapShips,
    SeekBattle,
)
from pax_agentica.engine.mechanics import (
    blockaded,
    defense_multiplier,
    nation_income,
    nation_upkeep,
    naval_power,
    sea_command,
)
from pax_agentica.engine.model import Resources, Ship, UnitKind, Water
from pax_agentica.engine.scenario import COASTS, europe_map
from pax_agentica.tools import battle_odds

type Play = Callable[..., GameState]

A, B, M = Water.ATLANTIC, Water.BALTIC, Water.MEDITERRANEAN


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def at_war(state: GameState, a: str, b: str, play: Play) -> GameState:
    return play(state, **{a: [DeclareWar(target=b)]})


def test_every_coast_and_strait_is_on_the_map() -> None:
    game_map = europe_map()
    assert set(COASTS) <= set(game_map.provinces)
    for pid, p in game_map.provinces.items():
        for q in p.sea_neighbors:
            assert game_map.strait_water(pid, q) is not None
    assert game_map.strait_water("london", "normandy") == A
    assert game_map.strait_water("naples", "sicily") == M
    assert game_map.strait_water("scania", "zealand") == B


def test_galleys_rule_calm_seas_and_galleons_the_ocean(state: GameState) -> None:
    spain = state.nations["spain"]
    spain.fleets = {A: {Ship.GALLEY: 4}, M: {Ship.GALLEY: 4}}
    assert naval_power(state, "spain", M) > naval_power(state, "spain", A)
    spain.fleets = {A: {Ship.GALLEON: 2}}
    assert naval_power(state, "spain", A) == pytest.approx(5.0)
    # England's Navy Royal sails a quarter better
    state.nations["england"].fleets = {A: {Ship.GALLEON: 2}}
    assert naval_power(state, "england", A) == pytest.approx(6.25)


def test_a_port_launches_ships_into_its_water(state: GameState, play: Play) -> None:
    state.nations["spain"].resources = Resources(
        ducats=500, timber=99, iron=99, goods=9, manpower=9
    )
    before = state.nations["spain"].ships(M)[Ship.GALLEY]
    new = play(
        state,
        spain=[
            BuildShips(province="valencia", ship=Ship.GALLEY, count=3),
            BuildShips(province="madrid", ship=Ship.GALLEY, count=1),  # inland
            BuildShips(province="seville", ship=Ship.GALLEON, count=2, water=A),
            BuildShips(province="seville", ship=Ship.GALLEON, count=20, water=A),  # too many
        ],
    )
    spain = new.nations["spain"]
    assert spain.ships(M)[Ship.GALLEY] == before + 3
    assert spain.ships(A)[Ship.GALLEON] == state.nations["spain"].ships(A)[Ship.GALLEON] + 2
    why = reasons(new)
    assert "Madrid has no port on the sea" in why
    assert any("can launch only" in r for r in why)


def test_crews_are_pressed_only_for_war(state: GameState, play: Play) -> None:
    rules = state.rules
    paid = {k: v.model_copy(update={"pay": 1.0}) for k, v in rules.ships.items()}
    state.rules = rules.model_copy(update={"ships": paid})
    state.nations["spain"].fleets[A] = {Ship.GALLEON: 10}
    at_peace = nation_upkeep(state, "spain").ducats
    new = at_war(state, "spain", "france", play)
    assert nation_upkeep(new, "spain").ducats >= at_peace + 10
    # by default the crews cost nothing a year: the ships' price is paid when they are built
    assert all(spec.pay == 0 for spec in rules.ships.values())


def test_a_fleet_sails_to_another_water_by_the_end_of_the_year(
    state: GameState, play: Play
) -> None:
    state.nations["spain"].fleets = {M: {Ship.GALLEY: 6}}
    new = play(
        state,
        spain=[SailFleet(origin=M, target=A, ships={Ship.GALLEY: 4})],
        austria=[SailFleet(origin=M, target=B, ships={Ship.GALLEY: 1})],  # no Baltic port
    )
    assert new.nations["spain"].ships(M)[Ship.GALLEY] == 2
    assert new.nations["spain"].ships(A)[Ship.GALLEY] == 4
    assert "you hold no port on the Baltic" in reasons(new)


def test_a_stronger_fleet_closes_a_strait(state: GameState, play: Play) -> None:
    state.nations["england"].fleets = {A: {Ship.GALLEON: 6}}
    state.nations["france"].fleets = {A: {Ship.GALLEON: 1}}
    assert sea_command(state, "france", "england", A) == "closed"
    state.provinces["normandy"].set_army({UnitKind.INFANTRY: 20})
    new = at_war(state, "france", "england", play)
    new = play(new, france=[Attack(origin="normandy", target="london", regiments=20)])
    assert any("commands the Atlantic" in r for r in reasons(new))
    assert new.provinces["london"].owner == "england"
    view = view_for(new, "france")
    assert battle_odds(view, "normandy", "london") == 0.0


def test_holding_the_water_takes_away_the_straits_bonus(state: GameState) -> None:
    contested = defense_multiplier(state, "normandy", "london")
    state.nations["france"].fleets = {A: {Ship.GALLEON: 9}}
    assert sea_command(state, "france", "england", A) == "ours"
    assert defense_multiplier(state, "normandy", "london") < contested


def test_fleets_that_seek_battle_fight_and_the_beaten_lose_half(
    state: GameState, play: Play
) -> None:
    state.nations["spain"].fleets = {M: {Ship.GALLEY: 20}}
    state.nations["ottomans"].fleets = {M: {Ship.GALLEY: 8}}
    new = at_war(state, "spain", "ottomans", play)
    new = play(new, spain=[SeekBattle(water=M, enemy="ottomans")])
    battle = next(e for e in new.last_events if e.kind == EventKind.NAVAL_BATTLE)
    assert battle.data["attacker_won"]
    assert new.nations["ottomans"].ships(M)[Ship.GALLEY] == 4
    assert new.nations["spain"].ships(M)[Ship.GALLEY] >= 16
    war = new.war("spain", "ottomans")
    assert war is not None
    assert war.battles.get("spain") == 1


def test_a_skirmish_of_boats_does_not_count_in_the_war(state: GameState, play: Play) -> None:
    state.nations["spain"].fleets = {M: {Ship.GALLEY: 20}}
    state.nations["ottomans"].fleets = {M: {Ship.GALLEY: 2}}
    new = at_war(state, "spain", "ottomans", play)
    new = play(new, spain=[SeekBattle(water=M, enemy="ottomans")])
    assert any(e.kind == EventKind.NAVAL_BATTLE for e in new.last_events)
    war = new.war("spain", "ottomans")
    assert war is not None
    assert not war.battles


def test_no_battle_without_a_war_or_an_enemy_fleet(state: GameState, play: Play) -> None:
    new = play(state, spain=[SeekBattle(water=M, enemy="ottomans")])
    assert any("not at war" in r for r in reasons(new))
    state.nations["ottomans"].fleets = {}
    new = at_war(state, "spain", "ottomans", play)
    new = play(new, spain=[SeekBattle(water=M, enemy="ottomans")])
    assert any("no fleet in the Mediterranean" in r for r in reasons(new))


def test_a_blockade_chokes_the_ports_trade(state: GameState, play: Play) -> None:
    new = at_war(state, "spain", "england", play)
    before = nation_income(new, "england").ducats
    new.nations["spain"].fleets = {A: {Ship.GALLEON: 10}}
    new.nations["england"].fleets = {A: {Ship.GALLEON: 1}}
    assert blockaded(new, "england") == {A}
    assert nation_income(new, "england").ducats < before
    assert view_for(new, "england").me.blockaded == (A,)


def test_ships_can_be_laid_up(state: GameState, play: Play) -> None:
    state.nations["spain"].fleets = {M: {Ship.GALLEY: 6}}
    new = play(state, spain=[ScrapShips(water=M, ship=Ship.GALLEY, count=6)])
    assert new.nations["spain"].fleets == {}
    assert view_for(new, "france").nations
