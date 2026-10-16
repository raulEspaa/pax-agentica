"""The merchants' cut: what a realm's trade bonuses save it on the European market."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, Resources, view_for
from pax_agentica.engine.actions import Buy, Sell
from pax_agentica.engine.mechanics import market_cut, market_total
from pax_agentica.engine.model import BuildingKind, TechBranch
from pax_agentica.engine.realm import modifiers

type Play = Callable[..., GameState]


def test_bonuses_lower_the_cut(state: GameState) -> None:
    plain = market_cut(state, "france")
    assert plain == state.rules.market_spread
    state.nations["france"].technology[TechBranch.ECONOMY] = 2
    state.provinces["paris"].buildings.append(BuildingKind.MARKETPLACE)
    state.provinces["paris"].levels[BuildingKind.MARKETPLACE] = 3
    bonus = modifiers(state, "france").trade_bonus
    assert bonus == 2 * state.rules.trade_bonus_per_economy_level + 3 * (
        state.rules.trade_bonus_per_marketplace
    )
    assert market_cut(state, "france") < plain
    assert market_cut(state, "england") < plain  # the Merchant Adventurers


def test_a_better_cut_buys_cheaper_and_sells_dearer(state: GameState, play: Play) -> None:
    state.nations["england"].resources = Resources(ducats=500, iron=50)
    state.nations["france"].resources = Resources(ducats=500, iron=50)
    england = market_total(state, "iron", 30, buying=True, nation="england")
    france = market_total(state, "iron", 30, buying=True, nation="france")
    assert england < france
    assert market_total(state, "iron", 30, buying=False, nation="england") > market_total(
        state, "iron", 30, buying=False, nation="france"
    )
    view = view_for(state, "england")
    assert view.market["iron"].buy < view_for(state, "france").market["iron"].buy
    new = play(state, england=[Buy(resource="iron", amount=30), Sell(resource="iron", amount=5)])
    paid = [e.data["ducats"] for e in new.last_events if e.kind == EventKind.MARKET_TRADE]
    assert paid == [england, market_total(state, "iron", 5, buying=False, nation="england")]
