"""The great events of the age: once a game, in their years, decided by the crowns they fall to."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState
from pax_agentica.engine.actions import ChooseOption
from pax_agentica.engine.model import Ship, UnitKind

type Play = Callable[..., GameState]


def year(state: GameState, y: int) -> GameState:
    state.turn = y - state.rules.start_year + 1
    return state


def pending(state: GameState, nation: str, event: str) -> int:
    return next(p.id for p in state.nations[nation].pending_events if p.event == event)


def test_the_burgundian_inheritance_goes_to_the_habsburgs(state: GameState, play: Play) -> None:
    new = play(year(state, 1505))
    assert "burgundy" in new.history
    chosen = play(
        new, austria=[ChooseOption(event_id=pending(new, "austria", "burgundy"), option=0)]
    )
    assert chosen.provinces["flanders"].owner == "austria"
    assert chosen.provinces["holland"].owner == "austria"
    assert any(g.against == "austria" for g in chosen.nations["france"].grudges)
    again = play(chosen)
    assert not any(p.event == "burgundy" for p in again.nations["austria"].pending_events)


def test_the_estates_may_keep_the_low_countries(state: GameState, play: Play) -> None:
    new = play(year(state, 1505))
    kept = play(new, austria=[ChooseOption(event_id=pending(new, "austria", "burgundy"), option=2)])
    assert kept.provinces["flanders"].owner is None


def test_the_field_of_the_cloth_of_gold(state: GameState, play: Play) -> None:
    new = play(year(state, 1519))
    before = new.opinion("france", "england")
    new.nations["england"].resources = new.nations["england"].resources.model_copy(
        update={"ducats": 200}
    )
    met = play(
        new, england=[ChooseOption(event_id=pending(new, "england", "cloth_of_gold"), option=0)]
    )
    assert met.opinion("france", "england") > before


def test_the_sultan_may_march_on_vienna(state: GameState, play: Play) -> None:
    state.provinces["croatia"].owner = "ottomans"  # the Sultan at the gates of Styria
    new = play(year(state, 1527))
    assert "vienna" in new.history
    marched = play(
        new, ottomans=[ChooseOption(event_id=pending(new, "ottomans", "vienna"), option=0)]
    )
    assert marched.at_war("ottomans", "austria")
    assert marched.provinces["croatia"].army()[UnitKind.ARCHERS] >= 8


def test_the_holy_league_gathers_and_fights_as_one(state: GameState, play: Play) -> None:
    new = play(year(state, 1531))
    assert "holy_league" in new.history
    assert any(p.event == "holy_league" for p in new.nations["spain"].pending_events)
    new.nations["spain"].resources = new.nations["spain"].resources.model_copy(
        update={"ducats": 300}
    )
    galleys = sum(n.get(Ship.GALLEY, 0) for n in new.nations["spain"].fleets.values())
    joined = play(
        new, spain=[ChooseOption(event_id=pending(new, "spain", "holy_league"), option=0)]
    )
    assert joined.at_war("spain", "ottomans")
    assert sum(n.get(Ship.GALLEY, 0) for n in joined.nations["spain"].fleets.values()) > galleys
    fought = play(joined)
    battle = [e for e in fought.last_events if e.kind == EventKind.NAVAL_BATTLE]
    assert battle
    assert battle[0].data["league"]
    assert "holy_league_battle" in fought.history
