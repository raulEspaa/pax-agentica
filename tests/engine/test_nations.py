"""What makes each crown itself: its own regiments and its spirits."""

from pax_agentica.engine import GameState
from pax_agentica.engine.mechanics import army_strength, nation_income, unit_cost
from pax_agentica.engine.model import Terrain, UnitKind
from pax_agentica.engine.realm import TRADITIONS, modifiers


def test_every_great_power_has_its_own_regiments_and_two_spirits(state: GameState) -> None:
    for nation in state.nations:
        assert nation in state.rules.national_units, nation
        assert len(TRADITIONS[nation]) == 2, nation
    assert state.rules.national_units["spain"].name == "Tercios"
    assert state.rules.national_units["poland"].kind == UnitKind.CAVALRY


def test_tercios_fight_harder_than_anyone_elses_pikemen(state: GameState) -> None:
    army = {UnitKind.INFANTRY: 10}
    spanish = army_strength(state.rules, army, Terrain.PLAINS, attacking=True, nation="spain")
    french = army_strength(state.rules, army, Terrain.PLAINS, attacking=True, nation="france")
    assert spanish == french * 1.15


def test_winged_hussars_rule_the_plains(state: GameState) -> None:
    horse = {UnitKind.CAVALRY: 10}
    polish = army_strength(state.rules, horse, Terrain.PLAINS, attacking=True, nation="poland")
    russian = army_strength(state.rules, horse, Terrain.PLAINS, attacking=True, nation="russia")
    assert polish > russian * 1.5


def test_longbowmen_come_cheaper_to_england(state: GameState) -> None:
    english = unit_cost(state.rules, UnitKind.ARCHERS, "england")
    french = unit_cost(state.rules, UnitKind.ARCHERS, "france")
    assert english.ducats < french.ducats
    assert unit_cost(state.rules, UnitKind.INFANTRY, "england") == unit_cost(
        state.rules, UnitKind.INFANTRY, "france"
    )


def test_the_spirits_shape_the_realm(state: GameState) -> None:
    russia = modifiers(state, "russia")
    assert russia.manpower_income == 0.25
    assert any(s.startswith("The lands of Rus'") for s in russia.sources)
    before = nation_income(state, "russia").manpower
    assert before > 0
    poland = modifiers(state, "poland")
    assert poland.grain_income >= 0.20
