"""Properties that must hold for any game: reproducible, pure, and always consistent."""

import asyncio

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pax_agentica.engine import GameOverError, GameState, new_game, resolve_turn, view_for
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.players.random_bot import RandomBot
from pax_agentica.runner import GameRecord, run_game


def play_out(seed: int, bot: type[GreedyBot] | type[RandomBot], turns: int) -> GameRecord:
    state = new_game(seed, max_turns=turns)
    return asyncio.run(run_game(state, {n: bot(seed) for n in state.nations}))


def assert_consistent(state: GameState) -> None:
    alive = set(state.alive_nations())
    for p in state.provinces.values():
        assert p.owner is None or p.owner in alive
    for nation in state.nations.values():
        if nation.alive:
            assert state.provinces[nation.capital].owner == nation.id
        else:
            assert not state.provinces_of(nation.id)
    wars = [w.parties for w in state.wars]
    assert len(wars) == len(set(wars))
    for a, b in wars:
        assert a < b
        assert {a, b} <= alive
    for t in state.treaties:
        assert set(t.parties) <= alive
        assert not state.at_war(*t.parties)


def test_the_same_seed_plays_the_same_game() -> None:
    first = play_out(11, GreedyBot, turns=20)
    second = play_out(11, GreedyBot, turns=20)
    assert first.model_dump_json() == second.model_dump_json()


def test_different_seeds_play_different_games() -> None:
    assert play_out(1, GreedyBot, 15).turns[-1].after != play_out(2, GreedyBot, 15).turns[-1].after


@settings(max_examples=15, deadline=None)
@given(seed=st.integers(min_value=0, max_value=10_000))
def test_resolving_a_turn_never_mutates_its_input(seed: int) -> None:
    state = new_game(seed)
    bot = RandomBot(seed)
    for _ in range(5):
        before = state.model_dump_json()
        orders = {n: bot.plan(view_for(state, n)) for n in state.alive_nations()}
        new = resolve_turn(state, orders)
        assert state.model_dump_json() == before
        state = new


@settings(max_examples=10, deadline=None)
@given(seed=st.integers(min_value=0, max_value=10_000))
def test_chaos_never_breaks_the_rules(seed: int) -> None:
    state = new_game(seed, max_turns=30)
    bot = RandomBot(seed)
    while not state.finished:
        orders = {n: bot.plan(view_for(state, n)) for n in state.alive_nations()}
        state = resolve_turn(state, orders)
        assert_consistent(state)
    assert state.winner in state.alive_nations()


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_greedy_games_end_with_a_winner(seed: int) -> None:
    record = play_out(seed, GreedyBot, turns=50)
    assert record.winner is not None
    assert len(record.turns) <= 50


def test_a_finished_game_cannot_continue() -> None:
    state = new_game(0, max_turns=1)
    finished = resolve_turn(state, {})
    assert finished.finished
    assert finished.winner is not None
    with pytest.raises(GameOverError):
        resolve_turn(finished, {})
