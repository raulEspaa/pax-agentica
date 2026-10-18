"""Province designations, grown out of a focus, and the realm's great policies."""

from collections.abc import Callable

import pytest

from pax_agentica.engine import EventKind, GameState, view_for
from pax_agentica.engine.actions import SetFocus, SetPolicy
from pax_agentica.engine.mechanics import defense_multiplier, province_output, province_slots
from pax_agentica.engine.model import BuildingKind, Focus, PolicyAxis, Resources
from pax_agentica.engine.realm import designation, designation_name, modifiers

type Play = Callable[..., GameState]

B = BuildingKind


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def test_a_focus_grows_into_a_designation_by_its_works(state: GameState) -> None:
    p = state.provinces["seville"]
    p.focus, p.buildings = Focus.TRADE, []
    assert designation(state, "seville") == (Focus.TRADE, 1)
    assert designation_name(state, "seville") == "Trade port"  # by the sea
    slots = province_slots(state, "seville")
    p.buildings = [B.MARKETPLACE]
    assert designation(state, "seville") == (Focus.TRADE, 2)
    assert province_slots(state, "seville") == slots + 1
    p.buildings = [B.MARKETPLACE, B.BANK]
    assert designation(state, "seville") == (Focus.TRADE, 3)
    inland = state.provinces["madrid"]
    inland.focus = Focus.TRADE
    assert designation_name(state, "madrid") == "Trade town"


def test_a_great_designation_helps_its_neighbours_and_the_realm(state: GameState) -> None:
    before = province_output(state, "castile").grain
    granary = state.provinces["madrid"]
    granary.focus, granary.buildings = Focus.FARMING, [B.FARM_ESTATES, B.MARKETPLACE]
    assert province_output(state, "castile").grain >= before  # +5% next door
    assert modifiers(state, "spain").grain_upkeep_factor < 1.0
    port = state.provinces["seville"]
    port.buildings = [B.MARKETPLACE, B.BANK]
    trade = modifiers(state, "spain").trade_bonus
    port.focus = Focus.TRADE  # the same works, now a trade port of tier 3
    assert modifiers(state, "spain").trade_bonus == pytest.approx(trade + 0.05)


def test_a_great_fortress_stiffens_the_defence_next_door(state: GameState) -> None:
    before = defense_multiplier(state, "navarre", "castile")
    fortress = state.provinces["aragon"]
    fortress.focus, fortress.buildings = Focus.GARRISON, [B.FORT, B.BARRACKS]
    assert designation(state, "aragon") == (Focus.GARRISON, 3)
    assert defense_multiplier(state, "navarre", "castile") > before


def test_a_shipyard_needs_a_coast(state: GameState, play: Play) -> None:
    state.nations["spain"].resources = Resources(ducats=200)
    new = play(state, spain=[SetFocus(province="madrid", focus=Focus.SHIPYARD)])
    assert "Madrid has no coast for a shipyard" in reasons(new)
    new = play(state, spain=[SetFocus(province="valencia", focus=Focus.SHIPYARD)])
    assert new.provinces["valencia"].focus == Focus.SHIPYARD


def test_the_first_policy_is_free_and_a_change_costs_stability(
    state: GameState, play: Play
) -> None:
    stability = state.nations["france"].stability
    before = modifiers(state, "france").ducat_income
    new = play(state, france=[SetPolicy(axis=PolicyAxis.ECONOMY, side=1)])  # mercantile
    assert new.nations["france"].policies == {PolicyAxis.ECONOMY: 1}
    assert new.nations["france"].stability == stability
    assert modifiers(new, "france").ducat_income > before + 0.04
    again = play(new, france=[SetPolicy(axis=PolicyAxis.ECONOMY, side=0)])
    assert any("stands until" in r for r in reasons(again))
    new.turn += new.rules.policy_years
    changed = play(new, france=[SetPolicy(axis=PolicyAxis.ECONOMY, side=0)])
    assert changed.nations["france"].policies[PolicyAxis.ECONOMY] == 0
    assert changed.nations["france"].stability == stability - 1
    assert view_for(changed, "france").me.policies == {PolicyAxis.ECONOMY: 0}
