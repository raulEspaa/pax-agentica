"""Attacks, battles, conquest and the end of nations."""

import random
from collections.abc import Callable

import pytest

from pax_agentica.engine import EventKind, GameState
from pax_agentica.engine.actions import Attack, DeclareWar, Move
from pax_agentica.engine.mechanics import defense_multiplier, fight
from pax_agentica.engine.model import BuildingKind

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
    state.provinces["madrid"].troops = 30
    new = play(state, spain=[Attack(origin="madrid", target="lisbon", regiments=30)])
    lisbon = new.provinces["lisbon"]
    assert lisbon.owner == "spain"
    assert 0 < lisbon.troops <= 30
    assert lisbon.unrest == state.rules.unrest_turns - 1  # one turn of unrest already passed
    assert new.provinces["madrid"].troops == 0
    kinds = [e.kind for e in new.last_events]
    assert EventKind.BATTLE in kinds
    assert EventKind.PROVINCE_CAPTURED in kinds


def test_an_empty_province_falls_without_a_battle(state: GameState, play: Play) -> None:
    state.provinces["lisbon"].troops = 0
    new = play(state, spain=[Attack(origin="madrid", target="lisbon", regiments=1)])
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
    assert later.provinces["languedoc"].owner == "spain"


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
    assert reasons(new) == ["you do not own Lisbon", "only 2 regiments in Madrid"]


def test_losing_the_capital_moves_it_and_costs_stability(state: GameState, play: Play) -> None:
    war = at_war(state, "spain", "england", play)
    war.provinces["normandy"].owner = "spain"
    war.provinces["normandy"].troops = 200
    war.provinces["london"].troops = 1
    new = play(war, spain=[Attack(origin="normandy", target="london", regiments=200)])
    england = new.nations["england"]
    assert new.provinces["london"].owner == "spain"
    assert england.capital == "york"  # the most developed province left
    assert england.stability == war.nations["england"].stability - 1


def test_a_nation_without_provinces_is_eliminated(state: GameState, play: Play) -> None:
    war = at_war(state, "spain", "england", play)
    for pid in ("york", "wales"):
        war.provinces[pid].owner = "spain"
    war.provinces["normandy"].owner = "spain"
    war.provinces["normandy"].troops = 200
    war.provinces["london"].troops = 1
    new = play(war, spain=[Attack(origin="normandy", target="london", regiments=200)])
    assert not new.nations["england"].alive
    assert not new.enemies_of("spain")
    assert EventKind.NATION_ELIMINATED in [e.kind for e in new.last_events]
