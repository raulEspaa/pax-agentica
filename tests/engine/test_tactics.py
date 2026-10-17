"""Battle tactics, garrison postures, veterancy and morale."""

from collections.abc import Callable

import pytest

from pax_agentica.engine import EventKind, GameState, view_for
from pax_agentica.engine.actions import Attack, HireMercenaries, Move, Recruit, SetPosture
from pax_agentica.engine.mechanics import morale, tactic_factor, veteran
from pax_agentica.engine.model import Posture, Resources, Tactic, Terrain, UnitKind

type Play = Callable[..., GameState]

PIKES = {UnitKind.INFANTRY: 10}
HORSE = {UnitKind.INFANTRY: 6, UnitKind.CAVALRY: 4}
SHOT = {UnitKind.INFANTRY: 6, UnitKind.ARCHERS: 4}
GUNS = {UnitKind.INFANTRY: 8, UnitKind.ARTILLERY: 2}


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def test_each_tactic_beats_one_posture_and_loses_to_another(state: GameState) -> None:
    rules, plain = state.rules, Terrain.PLAINS
    edge = rules.tactic_edge
    # carried in full on both sides: the whole edge, one way or the other
    assert tactic_factor(rules, Tactic.ASSAULT, Posture.SKIRMISH, PIKES, SHOT, plain) == (
        pytest.approx(1 + edge)
    )
    assert tactic_factor(rules, Tactic.ASSAULT, Posture.HOLD, PIKES, PIKES, plain) == (
        pytest.approx(1 - edge)
    )
    assert tactic_factor(rules, Tactic.FLANK, Posture.HOLD, HORSE, PIKES, plain) > 1
    assert tactic_factor(rules, Tactic.FLANK, Posture.SALLY, HORSE, HORSE, plain) < 1
    assert tactic_factor(rules, Tactic.BOMBARD, Posture.SALLY, GUNS, HORSE, plain) > 1
    assert tactic_factor(rules, Tactic.BOMBARD, Posture.SKIRMISH, GUNS, SHOT, plain) < 1


def test_a_way_of_fighting_is_only_as_good_as_the_regiments_that_carry_it(
    state: GameState,
) -> None:
    rules, plain = state.rules, Terrain.PLAINS
    # guns without guns: the bombardment is a feeble thing
    no_guns = tactic_factor(rules, Tactic.BOMBARD, Posture.SALLY, PIKES, HORSE, plain)
    guns = tactic_factor(rules, Tactic.BOMBARD, Posture.SALLY, GUNS, HORSE, plain)
    assert no_guns < 1 < guns
    # a sally with no horse to sally is caught out, whatever comes
    caught = tactic_factor(rules, Tactic.ASSAULT, Posture.SALLY, PIKES, PIKES, plain)
    assert caught > 1


def test_horse_cannot_ride_round_an_enemy_in_the_mountains(state: GameState) -> None:
    rules = state.rules
    plains = tactic_factor(rules, Tactic.FLANK, Posture.HOLD, HORSE, PIKES, Terrain.PLAINS)
    hills = tactic_factor(rules, Tactic.FLANK, Posture.HOLD, HORSE, PIKES, Terrain.MOUNTAINS)
    assert 1 < hills < plains


def test_morale_follows_stability_and_war_exhaustion(state: GameState) -> None:
    spain = state.nations["spain"]
    spain.stability, spain.war_exhaustion = 0, 0.0
    assert morale(state, "spain") == 1.0
    spain.stability = 3
    steady = morale(state, "spain")
    spain.war_exhaustion = 12.0
    assert morale(state, "spain") < steady
    assert morale(state, None) == 1.0
    assert veteran(state.rules, 1.0) == pytest.approx(1 + state.rules.veterancy_bonus)


def test_a_garrison_takes_up_a_posture(state: GameState, play: Play) -> None:
    new = play(
        state,
        spain=[
            SetPosture(province="castile", posture=Posture.SALLY),
            SetPosture(province="paris", posture=Posture.SKIRMISH),
        ],
    )
    assert new.provinces["castile"].posture == Posture.SALLY
    assert new.provinces["paris"].posture == Posture.HOLD
    assert "you do not hold Paris" in reasons(new)


def test_a_posture_is_seen_only_where_the_troops_are(state: GameState) -> None:
    state.provinces["moscow"].posture = Posture.SKIRMISH
    state.provinces["moscow"].veterancy = 0.5
    english = {p.id: p for p in view_for(state, "england").provinces}
    assert english["moscow"].posture is None
    assert english["moscow"].veterancy is None
    russian = {p.id: p for p in view_for(state, "russia").provinces}
    assert russian["moscow"].posture == Posture.SKIRMISH
    assert russian["moscow"].veterancy == 0.5


def test_victors_come_out_veterans(state: GameState, play: Play) -> None:
    state.provinces["aragon"].set_army({UnitKind.INFANTRY: 24})
    state.provinces["navarre"].set_army({UnitKind.INFANTRY: 6})
    new = play(state, spain=[Attack(origin="aragon", target="navarre", regiments=24)])
    assert new.provinces["navarre"].owner == "spain"
    gained = new.provinces["navarre"].veterancy
    # six levies beaten by two dozen: a lesson, not a war
    per_win = state.rules.veterancy_per_victory
    assert 0 < gained < per_win
    battle = next(e for e in new.last_events if e.kind == EventKind.BATTLE)
    assert battle.data["tactic"] == "assault"
    assert battle.data["posture"] == "hold"


def test_a_garrison_that_throws_an_attack_back_is_seasoned(state: GameState, play: Play) -> None:
    state.provinces["aragon"].set_army({UnitKind.INFANTRY: 6})
    state.provinces["navarre"].set_army({UnitKind.INFANTRY: 20})
    new = play(state, spain=[Attack(origin="aragon", target="navarre", regiments=6)])
    assert new.provinces["navarre"].owner is None
    assert new.provinces["navarre"].veterancy > 0


def test_veterans_march_with_their_regiments(state: GameState, play: Play) -> None:
    state.provinces["aragon"].set_army({UnitKind.INFANTRY: 6}, veterancy=0.8)
    state.provinces["castile"].set_army({})
    new = play(state, spain=[Move(origin="aragon", target="castile", regiments=6)])
    assert new.provinces["aragon"].veterancy == 0  # nobody left
    decay = state.rules.veterancy_decay
    assert new.provinces["castile"].veterancy == pytest.approx(0.8 - decay)


def test_raw_recruits_dilute_the_veterans_and_hirelings_come_seasoned(
    state: GameState, play: Play
) -> None:
    rules = state.rules
    state.nations["spain"].resources = Resources(ducats=999, grain=99, iron=99, manpower=99)
    state.provinces["castile"].set_army({UnitKind.INFANTRY: 4}, veterancy=1.0)
    state.provinces["aragon"].set_army({})
    new = play(
        state,
        spain=[
            Recruit(province="castile", regiments=4, unit=UnitKind.INFANTRY),
            HireMercenaries(province="aragon", regiments=2),
        ],
    )
    decay = rules.veterancy_decay
    assert new.provinces["castile"].veterancy == pytest.approx(0.5 - decay)
    assert new.provinces["aragon"].veterancy == pytest.approx(rules.mercenary_veterancy - decay)


def test_veterans_grow_old_and_go_home(state: GameState, play: Play) -> None:
    state.provinces["castile"].veterancy = 0.01
    new = play(state)
    assert new.provinces["castile"].veterancy == 0
