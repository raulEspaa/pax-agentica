"""The great troubles of the age: one per game, announced, answered, and felt."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, view_for
from pax_agentica.engine.actions import ChooseOption
from pax_agentica.engine.fortune import CRISES
from pax_agentica.engine.model import Crisis
from pax_agentica.engine.realm import modifiers

type Play = Callable[..., GameState]


def test_one_crisis_is_drawn_for_the_middle_of_the_game(state: GameState, play: Play) -> None:
    new = play(state)
    c = new.crisis
    assert c is not None
    assert c.kind in CRISES
    lo, hi = state.rules.crisis_window
    assert lo <= c.start <= hi
    assert c.end - c.start == CRISES[c.kind].years
    assert play(state).crisis == c  # the same seed draws the same trouble


def test_every_crown_must_answer_when_it_begins(state: GameState, play: Play) -> None:
    state.crisis = Crisis(kind="plague", start=state.turn + 1, end=state.turn + 4)
    new = play(state)
    assert any(e.kind == EventKind.CRISIS and e.data["begins"] for e in new.last_events)
    pending = new.nations["france"].pending_events
    assert [p.event for p in pending] == ["great_plague"]
    view = view_for(new, "france")
    assert view.me.pending_events[0].options[0].effects.endswith("ducats -15% while it lasts")


def test_closed_towns_lose_fewer_people(state: GameState, play: Play) -> None:
    state.crisis = Crisis(kind="plague", start=state.turn + 1, end=state.turn + 30)
    begun = play(state)
    pid = begun.nations["france"].pending_events[0].id
    for nation in begun.nations.values():  # everyone else keeps trading
        if nation.id != "france":
            nation.pending_events = []
    closed = play(begun, france=[ChooseOption(event_id=pid, option=0)])
    assert "quarantine" in closed.nations["france"].flags
    assert modifiers(closed, "france").ducat_income < modifiers(closed, "spain").ducat_income + 0.2
    dev = {
        n: sum(closed.provinces[p].development for p in closed.provinces_of(n))
        for n in ("france", "spain", "austria", "england")
    }
    later = closed
    for _ in range(8):
        later = play(later)
    lost = {
        n: dev[n] - sum(later.provinces[p].development for p in later.provinces_of(n)) for n in dev
    }
    assert any(e.kind == EventKind.PLAGUE for e in later.last_events) or sum(lost.values()) > 0
    assert lost["france"] <= max(lost["spain"], lost["austria"], lost["england"])


def test_the_ice_age_starves_the_fields_and_lifts_bread(state: GameState, play: Play) -> None:
    before = modifiers(state, "france").grain_income
    state.crisis = Crisis(kind="ice_age", start=state.turn, end=state.turn + 5)
    assert modifiers(state, "france").grain_income == before - 0.35
    later = play(play(state))
    assert later.market["grain"] > state.rules.market_prices["grain"]


def test_a_crisis_passes(state: GameState, play: Play) -> None:
    state.crisis = Crisis(kind="price_revolution", start=1, end=state.turn + 1)
    new = play(state)
    assert any(e.kind == EventKind.CRISIS and not e.data["begins"] for e in new.last_events)
    assert new.crisis_now() is None
