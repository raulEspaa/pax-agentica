"""How the greedy bot answers a peace: by the war's state, never by a coin toss."""

import asyncio

from pax_agentica.engine import GameState, Orders, resolve_turn, view_for
from pax_agentica.engine.actions import DeclareWar, ProposePeace, Respond
from pax_agentica.players.greedy_bot import GreedyBot


def offer(state: GameState) -> GameState:
    """France at war with Spain offers a white peace."""
    war = resolve_turn(state, {"france": Orders(actions=[DeclareWar(target="spain")])})
    return resolve_turn(war, {"france": Orders(actions=[ProposePeace(target="spain")])})


def answer(state: GameState, seed: int) -> Respond:
    orders = asyncio.run(GreedyBot(seed).decide(view_for(state, "spain")))
    return next(a for a in orders.actions if isinstance(a, Respond))


def test_an_even_war_ends_with_a_white_peace_every_time(state: GameState) -> None:
    offered = offer(state)
    assert all(answer(offered, seed).accept for seed in range(8))


def test_a_court_a_little_ahead_waits_three_years_and_says_so(state: GameState) -> None:
    offered = offer(state)
    offered.wars[0].battles["spain"] = 3  # Spain is a little ahead: three battles won
    first = [answer(offered, seed) for seed in range(6)]
    assert not any(a.accept for a in first)
    assert all("three years" in a.note for a in first if a.counter is None)
    for war in offered.wars:
        war.since = offered.turn - 3
    assert all(answer(offered, seed).accept for seed in range(6))


def test_a_winner_names_its_price(state: GameState) -> None:
    offered = offer(state)
    offered.provinces["gascony"].controller = "spain"
    offered.provinces["languedoc"].controller = "spain"
    reply = answer(offered, 1)
    assert not reply.accept
    assert reply.counter is not None
    assert reply.counter.demand or not reply.counter.receive.is_empty()
