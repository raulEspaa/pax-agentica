"""The game loop survives bad rulers; the bots play sensibly."""

import asyncio

import pytest

from pax_agentica.engine import EventKind, NationView, Orders, new_game
from pax_agentica.players import Player
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.players.random_bot import RandomBot
from pax_agentica.runner import play_turn, run_game


class Crashing:
    name = "crashing"

    async def decide(self, view: NationView) -> Orders:
        raise RuntimeError("the model returned nonsense")


class Sleepy:
    name = "sleepy"

    async def decide(self, view: NationView) -> Orders:
        await asyncio.sleep(10)
        return Orders()


def test_a_crashing_ruler_forfeits_its_turn_but_the_game_goes_on() -> None:
    state = new_game(1)
    players: dict[str, Player] = {n: GreedyBot(1) for n in state.nations}
    players["france"] = Crashing()
    new, record = asyncio.run(play_turn(state, players))
    assert new.turn == 2
    assert record.errors == {"france": "RuntimeError: the model returned nonsense"}
    assert "france" not in record.orders


def test_a_slow_ruler_times_out() -> None:
    state = new_game(1)
    players: dict[str, Player] = {n: GreedyBot(1) for n in state.nations}
    players["spain"] = Sleepy()
    _, record = asyncio.run(play_turn(state, players, timeout=0.05))
    assert record.errors["spain"].startswith("timed out")


def test_every_nation_needs_a_ruler() -> None:
    state = new_game(1)
    with pytest.raises(ValueError, match="no player for"):
        asyncio.run(run_game(state, {"france": GreedyBot()}))


def test_the_greedy_bot_rarely_gives_illegal_orders() -> None:
    state = new_game(4)
    record = asyncio.run(run_game(state, {n: GreedyBot(4) for n in state.nations}))
    actions = sum(len(o.actions) for t in record.turns for o in t.orders.values())
    rejected = sum(e.kind == EventKind.ORDER_REJECTED for t in record.turns for e in t.events)
    assert actions > 100
    assert rejected / actions < 0.05


def test_the_greedy_bot_beats_random_rulers() -> None:
    wins = 0
    for seed in range(4):
        state = new_game(seed, max_turns=40)
        players: dict[str, Player] = {n: RandomBot(seed) for n in state.nations}
        players["spain"] = GreedyBot(seed)
        record = asyncio.run(run_game(state, players))
        wins += record.winner == "spain"
    assert wins >= 3


def test_the_greedy_bot_survives_losing_every_province_to_occupation() -> None:
    import asyncio

    from pax_agentica.engine import Orders, new_game, resolve_turn, view_for
    from pax_agentica.engine.actions import DeclareWar
    from pax_agentica.players.greedy_bot import GreedyBot

    state = resolve_turn(new_game(1), {"spain": Orders(actions=[DeclareWar(target="england")])})
    for pid in state.provinces_of("england"):
        state.provinces[pid].controller = "spain"
    orders = asyncio.run(GreedyBot(1).decide(view_for(state, "england")))
    assert orders is not None
