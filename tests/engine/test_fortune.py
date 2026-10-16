"""Events of the age, prestige and faith."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, Resources, view_for
from pax_agentica.engine.actions import ChooseOption, DeclareWar, ProposePeace, Respond
from pax_agentica.engine.fortune import EVENTS_BY_ID
from pax_agentica.engine.model import Faith, PendingEvent
from pax_agentica.engine.realm import modifiers

type Play = Callable[..., GameState]


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def pending(state: GameState, nation: str, event: str, province: str | None = None) -> int:
    """Put an event before a nation's crown, as fortune would."""
    eid = state.next_event_id
    state.next_event_id += 1
    state.nations[nation].pending_events.append(
        PendingEvent(id=eid, event=event, turn=state.turn, province=province)
    )
    return eid


# ---------------------------------------------------------------- events


def test_fortune_brings_events_and_the_view_tells_them(state: GameState, play: Play) -> None:
    state.rules = state.rules.model_copy(update={"event_chance": 1.0})
    later = play(state)
    view = view_for(later, "france")
    assert len(view.me.pending_events) == 1
    event = view.me.pending_events[0]
    assert event.title
    assert len(event.options) >= 2
    assert all(o.effects for o in event.options)


def test_the_reformation_can_turn_a_realm(state: GameState, play: Play) -> None:
    eid = pending(state, "england", "reformation")
    before = state.nations["england"].resources.ducats
    new = play(state, england=[ChooseOption(event_id=eid, option=1)])
    england = new.nations["england"]
    assert england.faith == Faith.PROTESTANT
    assert england.resources.ducats > before
    assert not england.pending_events
    decided = [e for e in new.last_events if e.kind == EventKind.EVENT_DECIDED]
    assert decided
    assert "england" in decided[0].nations


def test_an_unanswered_event_takes_its_first_option(state: GameState, play: Play) -> None:
    pending(state, "france", "harvest")
    grain = state.nations["france"].resources.grain
    first = play(state)  # the year it arrived: still waiting
    assert first.nations["france"].pending_events
    second = play(first)
    assert not second.nations["france"].pending_events
    assert second.nations["france"].resources.grain > grain  # filled the granaries


def test_a_plague_strikes_its_province(state: GameState, play: Play) -> None:
    eid = pending(state, "france", "plague", province="paris")
    dev = state.provinces["paris"].development
    new = play(state, france=[ChooseOption(event_id=eid, option=1)])
    assert new.provinces["paris"].development == dev - 1


def test_a_loan_is_repaid_year_by_year(state: GameState, play: Play) -> None:
    eid = pending(state, "spain", "fuggers")
    new = play(state, spain=[ChooseOption(event_id=eid, option=0)])
    loan = new.nations["spain"].loans[0]
    assert (loan.yearly, loan.until - new.turn + 1) == (16, 10)


def test_bad_choices_are_refused(state: GameState, play: Play) -> None:
    eid = pending(state, "france", "harvest")
    new = play(state, france=[ChooseOption(event_id=eid, option=5)])
    assert reasons(new) == ["A great harvest has 2 options"]
    none = play(state, france=[ChooseOption(event_id=999, option=0)])
    assert reasons(none) == ["no pending event #999"]


def test_every_event_reads_well(state: GameState) -> None:
    for event in EVENTS_BY_ID.values():
        assert event.options
        assert "{" not in event.title


# ---------------------------------------------------------------- prestige


def test_prestige_pays_and_counts_towards_victory(state: GameState) -> None:
    plain = modifiers(state, "france")
    state.nations["france"].prestige = 60
    proud = modifiers(state, "france")
    assert proud.ducat_income > plain.ducat_income
    assert state.standing("france") == state.score("france") + 30


def test_land_won_by_treaty_brings_prestige(state: GameState, play: Play) -> None:
    war = play(state, spain=[DeclareWar(target="france")])
    war.provinces["languedoc"].controller = "spain"
    offer = play(war, spain=[ProposePeace(target="france", demand=["languedoc"])])
    pid = next(p.id for p in offer.proposals if p.recipient == "france")
    before = offer.nations["spain"].prestige
    done = play(offer, france=[Respond(proposal_id=pid, accept=True)])
    assert done.nations["spain"].prestige > before - done.rules.prestige_decay


def test_breaking_a_treaty_costs_prestige(state: GameState, play: Play) -> None:
    state.nations["spain"].prestige = 40
    state.nations["spain"].resources = Resources(ducats=10)
    from pax_agentica.engine.actions import ProposeNonAggression

    offer = play(state, spain=[ProposeNonAggression(target="france")])
    pid = next(p.id for p in offer.proposals if p.recipient == "france")
    pact = play(offer, france=[Respond(proposal_id=pid, accept=True)])
    broken = play(pact, spain=[DeclareWar(target="france")])
    assert broken.nations["spain"].prestige < pact.nations["spain"].prestige - 5


# ---------------------------------------------------------------- faith


def test_faith_draws_courts_together_or_apart(state: GameState, play: Play) -> None:
    later = play(state)
    assert later.opinion("france", "spain") > 0  # both catholic
    assert later.opinion("france", "ottomans") < later.opinion("france", "spain")
    view = view_for(later, "france")
    assert next(n for n in view.nations if n.id == "russia").faith == Faith.ORTHODOX
