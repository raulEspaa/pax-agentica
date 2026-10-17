"""Goods, buildings that consume, and the European market."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, Resources, view_for
from pax_agentica.engine.actions import Build, Buy, Develop, Recruit, Sell
from pax_agentica.engine.mechanics import (
    develop_cost,
    land_yield,
    market_price,
    market_total,
    province_output,
)
from pax_agentica.engine.model import BuildingKind, Good, UnitKind

type Play = Callable[..., GameState]

RICH = Resources(ducats=2000, manpower=200, iron=200, grain=500, timber=500, goods=50)


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


# ---------------------------------------------------------------- goods


def test_cloth_provinces_weave_goods(state: GameState) -> None:
    assert land_yield(state.rules, Good.CLOTH, 4).goods == 4
    assert province_output(state, "york").goods > 0  # the wool of England
    assert province_output(state, "paris").goods == 0


def test_workshops_turn_iron_and_timber_into_goods(state: GameState, play: Play) -> None:
    state.nations["france"].resources = RICH
    new = play(state, france=[Build(province="paris", building=BuildingKind.WORKSHOP)])
    assert province_output(new, "paris").goods == 2 + new.provinces["paris"].development // 3
    after = play(new)
    assert after.nations["france"].resources.goods > new.nations["france"].resources.goods


def test_new_townsfolk_must_be_fed(state: GameState) -> None:
    assert develop_cost(state.rules, 3).grain == 4 + 3
    assert develop_cost(state.rules, 10).grain > develop_cost(state.rules, 3).grain


def test_high_development_and_fine_troops_need_goods(state: GameState, play: Play) -> None:
    assert develop_cost(state.rules, 4).goods == 0
    assert develop_cost(state.rules, 9).goods == 3
    state.nations["france"].resources = Resources(ducats=500, manpower=50, iron=50, timber=50)
    new = play(
        state,
        france=[
            Develop(province="paris"),  # development 5: wants a bale of goods
            Recruit(province="paris", regiments=1, unit=UnitKind.ARCHERS),
        ],
    )
    assert len(reasons(new)) == 2


# ---------------------------------------------------------------- inputs


def test_a_building_without_its_inputs_stands_idle(state: GameState, play: Play) -> None:
    state.provinces["stockholm"].buildings.append(BuildingKind.MARKETPLACE)
    state.nations["sweden"].resources = Resources(ducats=100)  # Sweden makes no goods
    new = play(state)
    assert BuildingKind.MARKETPLACE in new.provinces["stockholm"].idle
    assert EventKind.BUILDINGS_IDLE in [e.kind for e in new.last_events]
    view = view_for(new, "sweden")
    stockholm = next(p for p in view.provinces if p.id == "stockholm")
    assert BuildingKind.MARKETPLACE in stockholm.idle
    working = new.model_copy(deep=True)
    working.provinces["stockholm"].idle = []
    ducats = province_output(working, "stockholm").ducats
    assert ducats > province_output(new, "stockholm").ducats


def test_inputs_are_paid_every_year(state: GameState, play: Play) -> None:
    state.provinces["paris"].buildings.append(BuildingKind.BARRACKS)  # eats 2 grain
    view = view_for(state, "france")
    assert view.me.inputs_per_turn.grain == 2
    new = play(state)
    assert not new.provinces["paris"].idle


# ---------------------------------------------------------------- the market


def test_buying_and_selling_at_a_cut(state: GameState, play: Play) -> None:
    state.nations["france"].resources = Resources(ducats=300, grain=100)
    price = market_price(state, "iron")
    new = play(state, france=[Buy(resource="iron", amount=10), Sell(resource="grain", amount=50)])
    france = new.nations["france"]
    assert france.resources.iron >= 10
    assert market_total(state, "iron", 10, buying=True) > 10 * price
    assert market_total(state, "grain", 50, buying=False) < 50 * market_price(state, "grain")
    assert [e for e in new.last_events if e.kind == EventKind.MARKET_TRADE]


def test_you_cannot_sell_what_you_lack(state: GameState, play: Play) -> None:
    new = play(state, france=[Sell(resource="goods", amount=50)])
    assert reasons(new) == ["you have only 8 goods"]


def test_prices_follow_demand(state: GameState, play: Play) -> None:
    for nation in ("france", "spain", "england"):
        state.nations[nation].resources = Resources(ducats=1000)
    before = market_price(state, "iron")
    new = play(
        state,
        france=[Buy(resource="iron", amount=60)],
        spain=[Buy(resource="iron", amount=60)],
        england=[Buy(resource="iron", amount=60)],
    )
    assert market_price(new, "iron") > before
    view = view_for(new, "france")
    assert view.market["iron"].buy > view.market["iron"].sell
