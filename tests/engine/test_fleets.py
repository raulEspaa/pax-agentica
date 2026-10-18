"""Fleets on the sea zones: ships, straits, landings, sea battles and blockades."""

from collections.abc import Callable

import pytest

from pax_agentica.engine import EventKind, GameState, view_for
from pax_agentica.engine.actions import (
    Attack,
    BuildShips,
    DeclareWar,
    Move,
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
from pax_agentica.engine.scenario import europe_map
from pax_agentica.tools import battle_odds, targets

type Play = Callable[..., GameState]

GALLEONS = {Ship.GALLEON: 6}


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def at_war(state: GameState, a: str, b: str, play: Play) -> GameState:
    return play(state, **{a: [DeclareWar(target=b)]})


def test_the_seas_are_charted() -> None:
    game_map = europe_map()
    assert len(game_map.seas) == 14
    for zid, zone in game_map.seas.items():
        for other in zone.neighbors:
            assert zid in game_map.seas[other].neighbors  # both ways
        for pid in zone.coasts:
            assert zid in game_map.provinces[pid].seas
    for pid, p in game_map.provinces.items():
        for q in p.sea_neighbors:
            sea = game_map.strait_sea(pid, q)
            assert sea is not None
            assert sea in p.seas
            assert sea in game_map.provinces[q].seas
    assert game_map.strait_sea("london", "normandy") == "channel"
    assert game_map.seas["western_med"].water == Water.MEDITERRANEAN


def test_galleys_rule_calm_seas_and_galleons_the_ocean(state: GameState) -> None:
    spain = state.nations["spain"]
    spain.fleets = {"atlantic": {Ship.GALLEY: 4}, "western_med": {Ship.GALLEY: 4}}
    assert naval_power(state, "spain", "western_med") > naval_power(state, "spain", "atlantic")
    spain.fleets = {"atlantic": {Ship.GALLEON: 2}}
    assert naval_power(state, "spain", "atlantic") == pytest.approx(5.0)
    # England's Navy Royal sails a quarter better
    state.nations["england"].fleets = {"channel": {Ship.GALLEON: 2}}
    assert naval_power(state, "england", "channel") == pytest.approx(6.25)


def test_a_port_launches_ships_into_its_sea(state: GameState, play: Play) -> None:
    rich = Resources(ducats=500, timber=99, iron=99, goods=9, manpower=9)
    state.nations["spain"].resources = rich
    before = state.nations["spain"].ships("western_med")[Ship.GALLEY]
    galleons = state.nations["spain"].ships("atlantic")[Ship.GALLEON]
    new = play(
        state,
        spain=[
            BuildShips(province="valencia", ship=Ship.GALLEY, count=3),
            BuildShips(province="madrid", ship=Ship.GALLEY, count=1),  # inland
            BuildShips(province="seville", ship=Ship.GALLEON, count=2, sea="atlantic"),
            BuildShips(province="seville", ship=Ship.GALLEON, count=20, sea="atlantic"),
        ],
    )
    spain = new.nations["spain"]
    assert spain.ships("western_med")[Ship.GALLEY] == before + 3
    assert spain.ships("atlantic")[Ship.GALLEON] == galleons + 2
    why = reasons(new)
    assert "Madrid has no port on the sea" in why
    assert any("can launch only" in r for r in why)


def test_crews_are_pressed_only_for_war(state: GameState, play: Play) -> None:
    rules = state.rules
    paid = {k: v.model_copy(update={"pay": 1.0}) for k, v in rules.ships.items()}
    state.rules = rules.model_copy(update={"ships": paid})
    state.nations["spain"].fleets["atlantic"] = {Ship.GALLEON: 10}
    at_peace = nation_upkeep(state, "spain").ducats
    new = at_war(state, "spain", "france", play)
    assert nation_upkeep(new, "spain").ducats >= at_peace + 10
    # by default the crews cost nothing a year: the ships' price is paid when they are built
    assert all(spec.pay == 0 for spec in rules.ships.values())


def test_a_fleet_sails_a_zone_a_year(state: GameState, play: Play) -> None:
    state.nations["spain"].fleets = {"western_med": {Ship.GALLEY: 6}}
    new = play(
        state,
        spain=[
            SailFleet(origin="western_med", target="atlantic", ships={Ship.GALLEY: 4}),
            SailFleet(origin="western_med", target="channel", ships={Ship.GALLEY: 2}),
        ],
    )
    assert new.nations["spain"].ships("western_med")[Ship.GALLEY] == 2
    assert new.nations["spain"].ships("atlantic")[Ship.GALLEY] == 4
    assert "the Mediterranean Sea does not open onto the English Channel" in reasons(new)


def test_a_stronger_fleet_closes_a_strait(state: GameState, play: Play) -> None:
    state.nations["england"].fleets = {"channel": {Ship.GALLEON: 6}}
    state.nations["france"].fleets = {"channel": {Ship.GALLEON: 1}}
    assert sea_command(state, "france", "england", "channel") == "closed"
    state.provinces["normandy"].set_army({UnitKind.INFANTRY: 20})
    new = at_war(state, "france", "england", play)
    new = play(new, france=[Attack(origin="normandy", target="london", regiments=20)])
    assert any("commands the English Channel" in r for r in reasons(new))
    assert new.provinces["london"].owner == "england"
    assert battle_odds(view_for(new, "france"), "normandy", "london") == 0.0


def test_holding_the_sea_takes_away_the_straits_bonus(state: GameState) -> None:
    contested = defense_multiplier(state, "normandy", "london")
    state.nations["france"].fleets = {"channel": {Ship.GALLEON: 9}}
    assert sea_command(state, "france", "england", "channel") == "ours"
    assert defense_multiplier(state, "normandy", "london") < contested


def test_a_fleet_lands_an_army_on_any_shore_of_its_sea(state: GameState, play: Play) -> None:
    state.provinces["normandy"].set_army({UnitKind.INFANTRY: 10})
    state.nations["england"].fleets = {}
    new = at_war(state, "france", "england", play)
    # no fleet in the Channel: no landing in East Anglia
    new.nations["france"].fleets = {}
    stuck = play(new, france=[Attack(origin="normandy", target="east_anglia", regiments=10)])
    assert any("no fleet of yours holds the English Channel" in r for r in reasons(stuck))
    # three galleons carry six regiments, not ten
    new.nations["france"].fleets = {"channel": {Ship.GALLEON: 3}}
    small = play(new, france=[Attack(origin="normandy", target="east_anglia", regiments=10)])
    assert any("can carry only 6 regiments" in r for r in reasons(small))
    new.nations["france"].fleets = {"channel": GALLEONS}
    landed = play(new, france=[Attack(origin="normandy", target="east_anglia", regiments=10)])
    assert any(e.kind == EventKind.BATTLE for e in landed.last_events)
    # the beach is defended harder than a strait
    strait = defense_multiplier(new, "normandy", "london")
    assert defense_multiplier(new, "normandy", "east_anglia") > strait
    shores = {t["province"]: t for t in targets(view_for(new, "france"), "normandy")}
    assert shores["east_anglia"]["landing"] == 12


def test_an_army_sails_between_its_own_ports(state: GameState, play: Play) -> None:
    state.provinces["seville"].set_army({UnitKind.INFANTRY: 6})
    state.nations["spain"].fleets = {"western_med": {Ship.GALLEY: 6}}
    before = state.provinces["valencia"].troops
    new = play(state, spain=[Move(origin="seville", target="valencia", regiments=4)])
    assert new.provinces["valencia"].troops == before + 4


def test_fleets_that_seek_battle_fight_and_the_beaten_lose_half(
    state: GameState, play: Play
) -> None:
    state.nations["spain"].fleets = {"western_med": {Ship.GALLEY: 20}}
    state.nations["ottomans"].fleets = {"western_med": {Ship.GALLEY: 8}}
    new = at_war(state, "spain", "ottomans", play)
    new = play(new, spain=[SeekBattle(sea="western_med", enemy="ottomans")])
    battle = next(e for e in new.last_events if e.kind == EventKind.NAVAL_BATTLE)
    assert battle.data["attacker_won"]
    assert new.nations["ottomans"].ships("western_med")[Ship.GALLEY] == 4
    assert new.nations["spain"].ships("western_med")[Ship.GALLEY] >= 16
    war = new.war("spain", "ottomans")
    assert war is not None
    assert war.battles.get("spain") == 1


def test_a_fleet_sails_and_fights_in_one_year(state: GameState, play: Play) -> None:
    state.nations["spain"].fleets = {"western_med": {Ship.GALLEY: 20}}
    state.nations["ottomans"].fleets = {"ionian": {Ship.GALLEY: 8}}
    new = at_war(state, "spain", "ottomans", play)
    new = play(
        new,
        spain=[
            SailFleet(origin="western_med", target="ionian", ships={Ship.GALLEY: 20}),
            SeekBattle(sea="ionian", enemy="ottomans"),
        ],
    )
    assert any(e.kind == EventKind.NAVAL_BATTLE for e in new.last_events)


def test_a_skirmish_of_boats_does_not_count_in_the_war(state: GameState, play: Play) -> None:
    state.nations["spain"].fleets = {"western_med": {Ship.GALLEY: 20}}
    state.nations["ottomans"].fleets = {"western_med": {Ship.GALLEY: 2}}
    new = at_war(state, "spain", "ottomans", play)
    new = play(new, spain=[SeekBattle(sea="western_med", enemy="ottomans")])
    assert any(e.kind == EventKind.NAVAL_BATTLE for e in new.last_events)
    war = new.war("spain", "ottomans")
    assert war is not None
    assert not war.battles


def test_no_battle_without_a_war_or_an_enemy_fleet(state: GameState, play: Play) -> None:
    new = play(state, spain=[SeekBattle(sea="western_med", enemy="ottomans")])
    assert any("not at war" in r for r in reasons(new))
    new = at_war(state, "spain", "ottomans", play)
    new = play(new, spain=[SeekBattle(sea="western_med", enemy="ottomans")])
    assert any("no fleet in the Mediterranean Sea" in r for r in reasons(new))


def test_a_blockade_chokes_the_ports_trade(state: GameState, play: Play) -> None:
    new = at_war(state, "spain", "england", play)
    before = nation_income(new, "england").ducats
    new.nations["spain"].fleets = {"channel": {Ship.GALLEON: 10}}
    new.nations["england"].fleets = {"channel": {Ship.GALLEON: 1}}
    assert "channel" in blockaded(new, "england")
    assert nation_income(new, "england").ducats < before
    assert "channel" in view_for(new, "england").me.blockaded


def test_ships_can_be_laid_up(state: GameState, play: Play) -> None:
    state.nations["spain"].fleets = {"western_med": {Ship.GALLEY: 6}}
    new = play(state, spain=[ScrapShips(sea="western_med", ship=Ship.GALLEY, count=6)])
    assert new.nations["spain"].fleets == {}


def test_every_fleet_is_public(state: GameState) -> None:
    seas = {z.id: z for z in view_for(state, "france").seas}
    assert seas["aegean"].fleets["ottomans"] == {Ship.GALLEY: 7, Ship.GALLEON: 1}
    assert seas["aegean"].power["ottomans"] == pytest.approx(12.0)
    assert seas["black_sea"].fleets["ottomans"] == {Ship.GALLEY: 3}


def test_a_game_saved_before_the_sea_zones_gets_them(state: GameState) -> None:
    old = state.model_dump(mode="json")
    old["map"].pop("seas")
    old["map"]["straits"] = dict.fromkeys(old["map"]["straits"], "atlantic")
    for p in old["map"]["provinces"].values():
        p.pop("seas")
    old["nations"]["ottomans"]["fleets"] = {"mediterranean": {"galley": 10}}
    old["nations"]["england"]["fleets"] = {"atlantic": {"galleon": 4}}
    loaded = GameState.model_validate(old)
    assert loaded.map.strait_sea("london", "normandy") == "channel"
    assert loaded.nations["ottomans"].fleets == {"aegean": {Ship.GALLEY: 10}}
    assert loaded.nations["england"].fleets == {"channel": {Ship.GALLEON: 4}}


def test_a_game_saved_before_the_fleets_gets_the_fleets_of_1500(state: GameState) -> None:
    old = state.model_dump(mode="json")
    old["map"].pop("seas")
    old["map"].pop("straits")
    for p in old["map"]["provinces"].values():
        p.pop("seas")
        p.pop("coasts")
    for n in old["nations"].values():
        n.pop("fleets")
    loaded = GameState.model_validate(old)
    assert loaded.nations["ottomans"].ships("aegean")[Ship.GALLEY] == 7


def test_rules_saved_before_a_ship_field_still_load(state: GameState) -> None:
    old = state.model_dump(mode="json")
    for spec in old["rules"]["ships"].values():
        spec.pop("carries")
    loaded = GameState.model_validate(old)
    assert loaded.rules.ships[Ship.GALLEON].carries == 2
