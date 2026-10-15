"""Shared fixtures. `play` resolves one turn from keyword orders: play(state, france=[...])."""

from collections.abc import Callable

import pytest

from pax_agentica.engine import Action, GameState, Orders, new_game, resolve_turn

type Play = Callable[..., GameState]


@pytest.fixture
def state() -> GameState:
    """A fresh game whose rulers are young and middling, so no death or diplomatic gift
    surprises a test."""
    game = new_game(seed=7)
    for nation in game.nations.values():
        assert nation.ruler is not None
        nation.ruler.age = 20
        nation.ruler.administration = nation.ruler.diplomacy = nation.ruler.military = 3
    return game


@pytest.fixture
def play() -> Play:
    def _play(state: GameState, **orders: list[Action]) -> GameState:
        return resolve_turn(state, {n: Orders(actions=a) for n, a in orders.items()})

    return _play
