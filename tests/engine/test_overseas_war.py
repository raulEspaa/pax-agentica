"""War beyond the sea: garrisons and forts, storming colonies, the peoples of the land, and the
treasure fleets an enemy may fall on."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, view_for
from pax_agentica.engine.actions import (
    BuildColonialFort,
    ConquerNatives,
    DeclareWar,
    SeizeColony,
    ShipTroops,
)
from pax_agentica.engine.mechanics import (
    colonial_defence,
    nation_upkeep,
    native_resistance,
    natives_left,
)
from pax_agentica.engine.model import Colony, Region, Resources, Ship, UnitKind

type Play = Callable[..., GameState]

NS, CAR = Region.NEW_SPAIN, Region.CARIBBEAN


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def test_the_peoples_deny_their_dues_until_soldiers_hold_the_land(
    state: GameState, play: Play
) -> None:
    state.nations["spain"].colonies = {NS: [Colony(), Colony()]}
    angry = native_resistance(state, "spain", NS)
    assert 0.4 < angry <= 0.5  # the Mexica, and two plantations
    state.provinces["seville"].set_army({UnitKind.INFANTRY: 6})
    new = play(state, spain=[ShipTroops(region=NS, port="seville", regiments=4)])
    assert new.nations["spain"].garrisons == {NS: 4}
    assert new.provinces["seville"].troops == 2
    assert native_resistance(new, "spain", NS) < angry / 1.9
    ledger = {line.source: line.amount for line in view_for(new, "spain").me.ledger}
    assert ledger["garrisons overseas"] == {"ducats": 4 * new.rules.garrison_pay}
    assert nation_upkeep(new, "spain").ducats >= 4
    home = play(new, spain=[ShipTroops(region=NS, port="seville", regiments=4, home=True)])
    assert home.nations["spain"].garrisons == {}
    assert home.provinces["seville"].troops == 6


def test_conquistadors_break_a_people_and_carry_off_its_gold(state: GameState, play: Play) -> None:
    no_base = play(state, spain=[ConquerNatives(region=Region.PERU, port="seville", regiments=2)])
    assert any("need a colony" in r for r in reasons(no_base))
    state.provinces["seville"].set_army({UnitKind.INFANTRY: 12})
    ducats, prestige = state.nations["spain"].resources.ducats, state.nations["spain"].prestige
    new = play(state, spain=[ConquerNatives(region=CAR, port="seville", regiments=6)])
    for _ in range(4):
        if not natives_left(new, CAR):
            break
        new = play(new, spain=[ConquerNatives(region=CAR)])  # the garrison marches again
    assert natives_left(new, CAR) == 0
    assert new.nations["spain"].prestige > prestige
    assert native_resistance(new, "spain", CAR) == 0
    assert new.nations["spain"].garrisons.get(CAR, 0) > 0
    assert new.nations["spain"].resources.ducats != ducats


def test_a_garrisoned_colony_must_be_stormed(state: GameState, play: Play) -> None:
    new = play(state, england=[DeclareWar(target="spain")])
    new.nations["england"].fleets = {"channel": {Ship.GALLEON: 5}}
    new.nations["spain"].fleets = {"atlantic": {Ship.GALLEON: 3}}
    new.nations["spain"].garrisons = {CAR: 3}
    by_sea = play(new, england=[SeizeColony(region=CAR, enemy="spain")])
    assert any("send regiments" in r for r in reasons(by_sea))
    assert by_sea.nations["spain"].colony_count(CAR) == 1
    new.provinces["london"].set_army({UnitKind.INFANTRY: 12})
    stormed = play(
        new, england=[SeizeColony(region=CAR, enemy="spain", regiments=10, port="london")]
    )
    battle = next(e for e in stormed.last_events if e.kind == EventKind.COLONIAL_BATTLE)
    assert battle.data["attacker_won"]
    assert stormed.nations["england"].colony_count(CAR) == 1
    assert stormed.nations["spain"].garrisons == {}
    assert 5 <= stormed.nations["england"].garrisons[CAR] < 10


def test_a_fort_stiffens_the_colonies(state: GameState, play: Play) -> None:
    me = state.nations["spain"]
    me.garrisons, me.resources = {CAR: 2}, Resources(ducats=300, iron=30)
    before = colonial_defence(state, "spain", CAR)
    new = play(state, spain=[BuildColonialFort(region=CAR)])
    assert new.nations["spain"].colonial_forts == {CAR: 1}
    assert colonial_defence(new, "spain", CAR) > before * 1.4
    view = next(r for r in view_for(new, "england").new_world if r.id == CAR)
    assert view.forts == {"spain": 1}
    assert view.garrisons == {"spain": 2}


def test_an_enemy_fleet_on_the_ocean_falls_on_the_treasure_fleets(
    state: GameState, play: Play
) -> None:
    state.nations["spain"].colonies = {Region.PERU: [Colony(), Colony()]}
    new = play(state, england=[DeclareWar(target="spain")])
    new.nations["england"].fleets = {"channel": {Ship.GALLEON: 20}}
    new.nations["spain"].fleets = {}
    taken = []
    for _ in range(6):
        new = play(new)
        taken += [e for e in new.last_events if e.kind == EventKind.TREASURE_TAKEN]
    assert taken
    assert taken[0].data["attacker"] == "england"
    assert int(taken[0].data["ducats"]) > 0
