"""A province's focus: what its people turn their hands to."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, Resources, view_for
from pax_agentica.engine.actions import SetFocus
from pax_agentica.engine.mechanics import defense_multiplier, focus_bonus, province_output
from pax_agentica.engine.model import Focus
from pax_agentica.engine.realm import modifiers

type Play = Callable[..., GameState]


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def test_a_focus_grows_with_the_town(state: GameState) -> None:
    state.provinces["paris"].focus = Focus.TRADE
    state.provinces["paris"].development = 1  # a hamlet
    assert focus_bonus(state, "paris") == state.rules.focus_base
    state.provinces["paris"].development = 9  # a great city
    rules = state.rules
    assert focus_bonus(state, "paris") == rules.focus_base + 4 * rules.focus_per_settlement


def test_a_trading_town_yields_more_ducats(state: GameState, play: Play) -> None:
    before = province_output(state, "paris")
    state.nations["france"].resources = Resources(ducats=200)
    new = play(state, france=[SetFocus(province="paris", focus=Focus.TRADE)])
    assert new.provinces["paris"].focus == Focus.TRADE
    after = province_output(new, "paris")
    assert after.ducats == int(before.ducats * (1 + focus_bonus(new, "paris")))
    assert after.grain == before.grain


def test_a_focus_is_kept_for_years(state: GameState, play: Play) -> None:
    state.nations["france"].resources = Resources(ducats=500)
    new = play(state, france=[SetFocus(province="lyon", focus=Focus.MINING)])
    again = play(new, france=[SetFocus(province="lyon", focus=Focus.TRADE)])
    assert again.provinces["lyon"].focus == Focus.MINING
    assert any("keeps its focus on mining" in r for r in reasons(again))


def test_a_garrison_town_is_defended_harder(state: GameState) -> None:
    before = defense_multiplier(state, "lyon", "paris")
    state.provinces["paris"].focus = Focus.GARRISON
    assert defense_multiplier(state, "lyon", "paris") > before


def test_learning_makes_developing_and_research_cheaper(state: GameState) -> None:
    before_dev = view_for(state, "france").provinces
    paris_cost = next(p for p in before_dev if p.id == "paris").develop_cost.ducats
    before_research = modifiers(state, "france").research_discount
    state.provinces["paris"].focus = Focus.LEARNING
    after = next(p for p in view_for(state, "france").provinces if p.id == "paris")
    assert after.develop_cost.ducats < paris_cost
    assert modifiers(state, "france").research_discount > before_research
