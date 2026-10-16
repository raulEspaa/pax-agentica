"""Royal marriages, infamy and coalitions, and the letter book every court keeps."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, view_for
from pax_agentica.engine.actions import (
    Attack,
    DeclareWar,
    ProposeAlliance,
    ProposeCoalition,
    ProposeMarriage,
    Respond,
    SendMessage,
)
from pax_agentica.engine.model import TreatyKind

type Play = Callable[..., GameState]


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def answer(state: GameState, play: Play, who: str, accept: bool = True) -> GameState:
    pid = next(p.id for p in state.proposals if p.recipient == who)
    return play(state, **{who: [Respond(proposal_id=pid, accept=accept)]})


# ---------------------------------------------------------------- marriages


def test_a_royal_marriage_warms_two_courts_every_year(state: GameState, play: Play) -> None:
    offer = play(state, england=[ProposeMarriage(target="spain", note="Catherine for Arthur.")])
    assert offer.proposals[0].note == "Catherine for Arthur."
    wed = answer(offer, play, "spain")
    assert wed.treaty("england", "spain", TreatyKind.MARRIAGE) is not None
    later = play(wed)
    assert later.opinion("spain", "england") > wed.opinion("spain", "england") - 2
    again = play(later, england=[ProposeMarriage(target="spain")])
    assert reasons(again) == ["the houses are already joined"]


# ---------------------------------------------------------------- infamy


def test_conquest_breeds_infamy_and_alarm_next_door(state: GameState, play: Play) -> None:
    state.provinces["castile"].troops = 40
    new = play(state, spain=[Attack(origin="castile", target="navarre", regiments=40)])
    assert new.provinces["navarre"].owner == "spain"
    assert new.nations["spain"].infamy > 0
    assert new.opinion("france", "spain") < 0  # France borders Navarre
    view = view_for(new, "france")
    assert next(n for n in view.nations if n.id == "spain").infamy > 0


# ---------------------------------------------------------------- coalitions


def leagued(state: GameState, play: Play) -> GameState:
    state.nations["france"].infamy = 30
    offer = play(
        state,
        austria=[ProposeCoalition(target="spain", against="france", note="Together, or alone.")],
    )
    return answer(offer, play, "spain")


def test_a_league_needs_a_conqueror_to_fear(state: GameState, play: Play) -> None:
    new = play(state, austria=[ProposeCoalition(target="spain", against="france")])
    assert reasons(new)[0].startswith("France's infamy (0) does not frighten Europe yet")


def test_attack_one_member_and_fight_the_league(state: GameState, play: Play) -> None:
    league = leagued(state, play)
    treaty = league.treaty("austria", "spain", TreatyKind.COALITION)
    assert treaty is not None
    assert treaty.against == "france"
    assert EventKind.COALITION_JOINED in [e.kind for e in league.last_events]
    war = play(league, france=[DeclareWar(target="spain")])
    assert war.at_war("france", "spain")
    assert war.at_war("austria", "france")  # without being asked
    view = view_for(war, "spain")
    assert next(n for n in view.nations if n.id == "austria").leagued_against == ("france",)


def test_a_league_dissolves_when_the_fear_fades(state: GameState, play: Play) -> None:
    league = leagued(state, play)
    league.nations["france"].infamy = league.rules.coalition_dissolves  # about to fade below
    calm = play(league)
    assert calm.treaty("austria", "spain", TreatyKind.COALITION) is None
    assert EventKind.COALITION_DISSOLVED in [e.kind for e in calm.last_events]


# ---------------------------------------------------------------- the letter book


def test_each_court_keeps_its_correspondence(state: GameState, play: Play) -> None:
    wrote = play(
        state,
        england=[
            SendMessage(target="france", text="Calais is ours by right."),
            ProposeAlliance(target="france", note="Or friends, if you prefer."),
        ],
    )
    refused = answer(wrote, play, "france", accept=False)
    france = next(n for n in view_for(refused, "england").nations if n.id == "france")
    kinds = [e.kind for e in france.correspondence]
    assert kinds[:3] == [
        EventKind.MESSAGE,
        EventKind.PROPOSAL_MADE,
        EventKind.PROPOSAL_REJECTED,
    ]
    assert france.correspondence[1].data["note"] == "Or friends, if you prefer."
    spain = next(n for n in view_for(refused, "spain").nations if n.id == "france")
    assert not [e for e in spain.correspondence if e.kind == EventKind.MESSAGE]


def test_an_answer_can_carry_words(state: GameState, play: Play) -> None:
    offer = play(state, england=[ProposeAlliance(target="france")])
    pid = next(p.id for p in offer.proposals if p.recipient == "france")
    no = play(
        offer, france=[Respond(proposal_id=pid, accept=False, note="Not while you hold Calais.")]
    )
    england = next(n for n in view_for(no, "france").nations if n.id == "england")
    letters = [e for e in england.correspondence if e.kind == EventKind.MESSAGE]
    assert letters[-1].data["text"] == "Not while you hold Calais."
