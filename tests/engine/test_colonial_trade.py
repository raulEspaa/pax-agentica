"""Colonial goods and their prices, the kinds of colony, silver's inflation and viceroyalties."""

from collections.abc import Callable

import pytest

from pax_agentica.engine import EventKind, GameState, view_for
from pax_agentica.engine.actions import FoundViceroyalty, SendExpedition
from pax_agentica.engine.mechanics import (
    colonial_cargo,
    colonial_trade,
    colony_share,
    expedition_cost,
    expedition_progress,
    good_price,
    nation_income,
)
from pax_agentica.engine.model import ColonialGood, Colony, ColonyKind, Region, Resources

type Play = Callable[..., GameState]

K = ColonyKind


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def test_a_good_shipped_past_what_europe_wants_falls_in_price(state: GameState) -> None:
    full = good_price(state, ColonialGood.SILVER)
    assert full == pytest.approx(3.0)
    state.nations["spain"].colonies = {Region.NEW_SPAIN: [Colony()] * 2, Region.PERU: [Colony()]}
    assert good_price(state, ColonialGood.SILVER) == pytest.approx(3.0 * (1 - 0.04 * 4))


def test_the_crown_that_ships_most_of_a_good_names_its_price(state: GameState) -> None:
    state.nations["spain"].colonies = {Region.PERU: [Colony(), Colony()]}
    trade = {t.good: t for t in colonial_trade(state, "spain")}
    assert trade[ColonialGood.SILVER].monopoly
    state.nations["england"].colonies = {Region.NEW_SPAIN: [Colony(), Colony()]}
    trade = {t.good: t for t in colonial_trade(state, "spain")}
    assert not trade[ColonialGood.SILVER].monopoly  # 8 cargoes of 14: not three in five


def test_silver_makes_every_price_rise(state: GameState, play: Play) -> None:
    state.nations["spain"].colonies = {Region.PERU: [Colony(), Colony()]}
    new = play(state)
    assert new.nations["spain"].inflation > 0
    view = view_for(new, "spain")
    assert view.me.inflation_loss > 0
    full = nation_income(new, "spain", inflated=False).ducats
    assert nation_income(new, "spain").ducats == full - view.me.inflation_loss
    assert any(line.source == "inflation" for line in view.me.ledger)
    assert play(state).nations["france"].inflation == 0


def test_each_kind_of_colony_has_its_price_and_its_pace(state: GameState, play: Play) -> None:
    rules = state.rules
    assert expedition_cost(rules, K.POST).ducats == rules.expedition_cost.ducats // 2
    brazil = Region.BRAZIL
    post = expedition_progress(state, "spain", brazil, K.POST)
    assert post == expedition_progress(state, "spain", brazil) + 10
    young, old = Colony(kind=K.SETTLEMENT, founded=1), Colony(kind=K.SETTLEMENT, founded=-20)
    assert colony_share(rules, young, 1) == 0.5
    assert colony_share(rules, old, 1) == 1.5
    state.nations["england"].resources = Resources(ducats=100, manpower=10)
    new = play(state, england=[SendExpedition(region=Region.CARIBBEAN, kind=K.POST)])
    assert new.nations["england"].expeditions[0].kind == K.POST
    assert new.nations["england"].resources.ducats > 100 - rules.expedition_cost.ducats


def test_a_viceroyalty_needs_three_colonies_and_ships_more(state: GameState, play: Play) -> None:
    me = state.nations["spain"]
    me.authority, me.resources = 50, Resources(ducats=300)
    refused = play(state, spain=[FoundViceroyalty(region=Region.CARIBBEAN)])
    assert any("needs 3 colonies" in r for r in reasons(refused))
    me.colonies = {Region.CARIBBEAN: [Colony(), Colony(), Colony()]}
    before = colonial_cargo(state, "spain")[Region.CARIBBEAN]
    new = play(state, spain=[FoundViceroyalty(region=Region.CARIBBEAN)])
    viceroy = new.nations["spain"].viceroys[Region.CARIBBEAN]
    assert viceroy.name
    assert colonial_cargo(new, "spain")[Region.CARIBBEAN] > before
    assert new.nations["spain"].authority < 50 + 10
    spain = next(n for n in view_for(new, "england").nations if n.id == "spain")
    assert spain.viceroys == {Region.CARIBBEAN: viceroy.name}


def test_a_game_saved_when_colonies_were_counted_still_loads(state: GameState) -> None:
    old = state.model_dump(mode="json")
    old["nations"]["spain"]["colonies"] = {"caribbean": 2}
    for n in old["nations"].values():
        n.pop("inflation")
        n.pop("viceroys")
    for spec in old["rules"]["regions"].values():
        for key in ("good", "cargo", "people", "natives", "plunder"):
            spec.pop(key)
    loaded = GameState.model_validate(old)
    assert [c.kind for c in loaded.nations["spain"].colonies[Region.CARIBBEAN]] == [
        K.PLANTATION
    ] * 2
    assert loaded.rules.regions[Region.PERU].good == ColonialGood.SILVER
