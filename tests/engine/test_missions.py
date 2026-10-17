"""Victory by ambition: a crown that fulfils every mission of its history wins its game."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState
from pax_agentica.engine.missions import missions_of

type Play = Callable[..., GameState]


def test_a_crown_that_fulfils_every_ambition_wins(state: GameState, play: Play) -> None:
    state.nations["brandenburg"].missions_done = [m.id for m in missions_of("brandenburg")]
    new = play(state)
    assert new.finished
    assert new.winner == "brandenburg"
    over = next(e for e in new.last_events if e.kind == EventKind.GAME_OVER)
    assert "every ambition" in over.summary


def test_most_ambitions_are_not_enough(state: GameState, play: Play) -> None:
    state.nations["brandenburg"].missions_done = [m.id for m in missions_of("brandenburg")][:-1]
    assert not play(state).finished
