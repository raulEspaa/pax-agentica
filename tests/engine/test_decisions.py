"""National decisions: great choices taken once, when their goals hold; and allies who share a
victory."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, view_for
from pax_agentica.engine.actions import TakeDecision
from pax_agentica.engine.model import Resources, Treaty, TreatyKind, pair
from pax_agentica.engine.realm import modifiers

type Play = Callable[..., GameState]


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def test_a_decision_waits_for_its_goals_then_changes_the_realm(
    state: GameState, play: Play
) -> None:
    me = state.nations["england"]
    me.authority = 60
    early = play(state, england=[TakeDecision(decision="great_britain")])
    assert any("hold Scotland and Highlands" in r for r in reasons(early))
    state.provinces["scotland"].owner = "england"
    state.provinces["highlands"].owner = "england"
    me.stability = 1
    navy = modifiers(state, "england").navy
    taken = play(state, england=[TakeDecision(decision="great_britain")])
    assert taken.nations["england"].name == "Great Britain"
    assert "great_britain" in taken.nations["england"].decisions
    assert modifiers(taken, "england").navy > navy
    assert taken.nations["england"].prestige > state.nations["england"].prestige
    assert any(e.kind == EventKind.DECISION for e in taken.last_events)
    again = play(taken, england=[TakeDecision(decision="great_britain")])
    assert any("taken already" in r for r in reasons(again))
    seen = next(n for n in view_for(taken, "france").nations if n.id == "england")
    assert seen.name == "Great Britain"
    assert seen.decisions == ("great_britain",)


def test_a_decision_of_its_time_pays_at_once(state: GameState, play: Play) -> None:
    me = state.nations["england"]
    me.authority, me.resources = 60, Resources(ducats=10)
    mine = {d.id: d for d in view_for(state, "england").me.decisions}
    assert "the year 1534" in mine["act_of_supremacy"].missing
    state.turn = 1534 - state.rules.start_year + 1
    paid = play(state, england=[TakeDecision(decision="act_of_supremacy")])
    assert paid.nations["england"].resources.ducats >= 120
    nonsense = play(state, england=[TakeDecision(decision="sack_rome")])
    assert any("no decision of your crown" in r for r in reasons(nonsense))


def test_one_crown_wins_alone_whatever_its_allies(state: GameState, play: Play) -> None:
    state.turn = state.max_turns
    alone = play(state.model_copy(deep=True))
    winner = alone.winner
    assert winner is not None
    friend = next(n for n in state.nations if n != winner)
    state.treaties.append(Treaty(kind=TreatyKind.ALLIANCE, parties=pair(winner, friend), since=1))
    over = play(state)
    assert over.winner == winner
    over_event = next(e for e in over.last_events if e.kind == EventKind.GAME_OVER)
    assert over_event.nations == (winner,)
