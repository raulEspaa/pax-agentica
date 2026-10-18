"""Kings: authority from the ruler's skills, royal acts that spend it, and a reign's ambition."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, view_for
from pax_agentica.engine.actions import ChooseAgenda, RoyalAction
from pax_agentica.engine.model import RoyalAct
from pax_agentica.engine.realm import agenda_offers, authority_per_year

type Play = Callable[..., GameState]


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def test_authority_gathers_by_the_rulers_skills(state: GameState, play: Play) -> None:
    me = state.nations["france"]
    assert authority_per_year(state, "france") == 9  # three skills of 3
    before = me.authority
    new = play(state)
    assert new.nations["france"].authority == before + 9
    me.authority = 98
    assert play(state).nations["france"].authority == state.rules.authority_max


def test_royal_acts_spend_authority(state: GameState, play: Play) -> None:
    me = state.nations["france"]
    me.authority = 60
    ducats = me.resources.ducats
    new = play(state, france=[RoyalAction(act=RoyalAct.LEVY)])
    assert new.nations["france"].resources.ducats >= ducats + 60 - 5  # 30 + 10 x 3, less upkeep
    assert new.nations["france"].authority == 60 - 30 + 9
    embassy = play(state, france=[RoyalAction(act=RoyalAct.EMBASSY, target="spain")])
    assert embassy.opinion("spain", "france") > state.opinion("spain", "france")
    me.authority = 10
    poor = play(state, france=[RoyalAction(act=RoyalAct.PROGRESS)])
    assert any("needs 40 authority" in r for r in reasons(poor))


def test_the_ruler_at_the_head_of_the_army_for_a_year(state: GameState, play: Play) -> None:
    state.nations["france"].authority = 40
    new = play(state, france=[RoyalAction(act=RoyalAct.PRESENCE)])
    assert any(e.kind == EventKind.ROYAL_ACT for e in new.last_events)
    assert "royal_presence" not in new.nations["france"].flags  # back at court at the year's end


def test_a_reign_takes_an_ambition_and_fulfils_it(state: GameState, play: Play) -> None:
    offers = agenda_offers(state, "france")
    assert len(offers) == 3
    assert [a.id for a in view_for(state, "france").me.agenda_offers] == offers
    new = play(state, france=[ChooseAgenda(agenda=offers[0])])
    ruler = new.nations["france"].ruler
    assert ruler is not None
    assert ruler.agenda == offers[0]
    spec = new.rules.agendas[offers[0]]
    prestige = new.nations["france"].prestige
    new.nations["france"].deeds[spec.deed] = ruler.agenda_start + spec.target
    done = play(new)
    assert done.nations["france"].ruler is not None
    assert done.nations["france"].ruler.agenda is None
    assert done.nations["france"].ruler.agendas_done == 1
    assert done.nations["france"].prestige > prestige
    wrong = play(state, france=[ChooseAgenda(agenda="nonsense")])
    assert any("not among" in r for r in reasons(wrong))


def test_deeds_are_counted_as_they_happen(state: GameState, play: Play) -> None:
    from pax_agentica.engine.actions import Develop
    from pax_agentica.engine.model import Resources

    rich = Resources(ducats=999, timber=99, iron=99, grain=99, goods=99)
    state.nations["france"].resources = rich
    new = play(state, france=[Develop(province="paris")])
    assert new.nations["france"].deeds.get("development") == 1
