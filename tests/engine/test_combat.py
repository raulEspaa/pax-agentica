"""Attacks, battles, conquest and the end of nations."""

import random
from collections.abc import Callable

import pytest

from pax_agentica.engine import EventKind, GameState
from pax_agentica.engine.actions import Attack, DeclareWar, Move, ProposePeace, Respond
from pax_agentica.engine.mechanics import defense_multiplier, fight
from pax_agentica.engine.model import BuildingKind, UnitKind

type Play = Callable[..., GameState]


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def at_war(state: GameState, a: str, b: str, play: Play) -> GameState:
    """Declare war and let the armies mobilise for a turn."""
    return play(state, **{a: [DeclareWar(target=b)]})


def test_defence_multiplies_terrain_forts_capitals_and_straits(state: GameState) -> None:
    advantage = state.rules.defender_advantage
    assert defense_multiplier(state, "lisbon", "galicia") == pytest.approx(advantage * 1.25)
    assert defense_multiplier(state, "normandy", "paris") == pytest.approx(advantage * 1.25)
    state.provinces["paris"].buildings = [BuildingKind.FORT, BuildingKind.CITADEL]
    assert defense_multiplier(state, "normandy", "paris") == pytest.approx(advantage * 1.75)
    assert defense_multiplier(state, "normandy", "london") == pytest.approx(advantage * 1.5)


def test_the_loser_of_a_battle_loses_everything_and_the_winner_keeps_one(
    state: GameState,
) -> None:
    rng = random.Random(1)
    crushing = fight(state.rules, attackers=100, defenders=1, multiplier=1.0, rng=rng)
    assert crushing.attacker_won
    assert crushing.defender_losses == 1
    assert 0 < crushing.attacker_losses < 5
    pyrrhic = fight(state.rules, attackers=2, defenders=200, multiplier=1.0, rng=rng)
    assert not pyrrhic.attacker_won
    assert pyrrhic.attacker_losses == 2
    assert pyrrhic.defender_losses <= 199


def test_battles_depend_only_on_the_seed(state: GameState) -> None:
    a = fight(state.rules, 10, 8, 1.2, random.Random("x"))
    b = fight(state.rules, 10, 8, 1.2, random.Random("x"))
    assert a == b


def test_conquering_an_independent_province(state: GameState, play: Play) -> None:
    state.provinces["seville"].troops = 30
    new = play(state, spain=[Attack(origin="seville", target="lisbon", regiments=30)])
    lisbon = new.provinces["lisbon"]
    assert lisbon.owner == "spain"
    assert 0 < lisbon.troops <= 30
    assert lisbon.unrest == state.rules.unrest_turns - 1  # one turn of unrest already passed
    assert new.provinces["seville"].troops == 0
    kinds = [e.kind for e in new.last_events]
    assert EventKind.BATTLE in kinds
    assert EventKind.PROVINCE_CAPTURED in kinds


def test_an_empty_province_falls_without_a_battle(state: GameState, play: Play) -> None:
    state.provinces["lisbon"].troops = 0
    new = play(state, spain=[Attack(origin="seville", target="lisbon", regiments=1)])
    assert new.provinces["lisbon"].owner == "spain"
    assert EventKind.BATTLE not in [e.kind for e in new.last_events]


def test_attacking_a_nation_requires_a_war(state: GameState, play: Play) -> None:
    new = play(state, spain=[Attack(origin="aragon", target="languedoc", regiments=2)])
    assert new.provinces["languedoc"].owner == "france"
    assert reasons(new) == ["you are not at war with France: declare war first"]


def test_armies_cannot_attack_in_the_turn_war_is_declared(state: GameState, play: Play) -> None:
    new = play(
        state,
        spain=[
            DeclareWar(target="france"),
            Attack(origin="aragon", target="languedoc", regiments=2),
        ],
    )
    assert reasons(new) == ["your armies are still mobilising: attack from turn 2"]
    new.provinces["aragon"].troops = 40
    later = play(new, spain=[Attack(origin="aragon", target="languedoc", regiments=40)])
    assert later.provinces["languedoc"].holder == "spain"  # occupied: the peace decides


def test_you_can_only_attack_bordering_provinces(state: GameState, play: Play) -> None:
    new = play(state, spain=[Attack(origin="madrid", target="morocco", regiments=1)])
    assert reasons(new) == ["Madrid and Morocco do not border"]


def test_straits_can_be_crossed(state: GameState, play: Play) -> None:
    state.provinces["andalusia"].troops = 30
    new = play(state, spain=[Attack(origin="andalusia", target="morocco", regiments=30)])
    assert new.provinces["morocco"].owner == "spain"


def test_moves_only_between_your_own_bordering_provinces(state: GameState, play: Play) -> None:
    new = play(
        state,
        spain=[
            Move(origin="madrid", target="aragon", regiments=4),
            Move(origin="madrid", target="lisbon", regiments=1),
            Move(origin="madrid", target="aragon", regiments=50),
        ],
    )
    assert new.provinces["aragon"].troops == 6
    assert reasons(new) == ["you do not hold Lisbon", "only 2 regiments in Madrid"]


def test_an_occupied_capital_costs_stability_and_stays_a_capital(
    state: GameState, play: Play
) -> None:
    war = at_war(state, "spain", "england", play)
    war.provinces["normandy"].owner = "spain"
    war.provinces["normandy"].troops = 200
    war.provinces["london"].troops = 1
    new = play(war, spain=[Attack(origin="normandy", target="london", regiments=200)])
    england = new.nations["england"]
    assert new.provinces["london"].owner == "england"
    assert new.provinces["london"].controller == "spain"
    assert england.capital == "london"
    assert england.stability == war.nations["england"].stability - 1


def test_a_peace_that_takes_the_last_province_ends_a_nation(state: GameState, play: Play) -> None:
    war = at_war(state, "spain", "england", play)
    for lost in ("york", "wales", "east_anglia", "devon"):
        war.provinces[lost].owner = "spain"
    war.provinces["london"].controller = "spain"  # Spain holds the capital
    offer = play(war, spain=[ProposePeace(target="england", demand=["london"])])
    assert reasons(offer) == []
    proposal = next(p.id for p in offer.proposals if p.recipient == "england")
    new = play(offer, england=[Respond(proposal_id=proposal, accept=True)])
    assert not new.nations["england"].alive
    assert not new.enemies_of("spain")
    assert EventKind.NATION_ELIMINATED in [e.kind for e in new.last_events]


def test_guns_enough_breach_walls_at_the_first_assault(state: GameState, play: Play) -> None:
    war = at_war(state, "france", "austria", play)  # Vienna has a fort
    war.provinces["bavaria"].owner = "france"
    war.provinces["bavaria"].set_army({UnitKind.INFANTRY: 50, UnitKind.ARTILLERY: 10})
    war.provinces["vienna"].troops = 1
    breached = play(war, france=[Attack(origin="bavaria", target="vienna", regiments=60)])
    assert breached.provinces["vienna"].controller == "france"  # a sixth of guns: no siege


def test_a_province_can_be_won_back(state: GameState, play: Play) -> None:
    war = at_war(state, "spain", "france", play)
    war.provinces["languedoc"].controller = "spain"
    war.provinces["languedoc"].troops = 1
    war.provinces["gascony"].troops = 30
    back = play(war, france=[Attack(origin="gascony", target="languedoc", regiments=30)])
    assert back.provinces["languedoc"].controller is None
    assert EventKind.PROVINCE_LIBERATED in [e.kind for e in back.last_events]
