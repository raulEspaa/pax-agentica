"""Peace terms, counter-offers, tribute, army limits and what courts think of each other."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, Resources, view_for
from pax_agentica.engine.actions import (
    DeclareWar,
    Gift,
    ProposeNonAggression,
    ProposePeace,
    ProposeTrade,
    Recruit,
    Respond,
    Terms,
)
from pax_agentica.engine.model import TreatyKind

type Play = Callable[..., GameState]


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def kinds(state: GameState) -> list[EventKind]:
    return [e.kind for e in state.last_events]


def proposal_to(state: GameState, nation: str) -> int:
    return next(p.id for p in state.proposals if p.recipient == nation)


def at_war(state: GameState, play: Play) -> GameState:
    return play(state, spain=[DeclareWar(target="france")])


# ---------------------------------------------------------------- terms


def test_a_peace_can_hand_over_provinces(state: GameState, play: Play) -> None:
    war = at_war(state, play)
    offer = play(war, spain=[ProposePeace(target="france", demand=["languedoc"], note="Yield.")])
    proposal = next(p for p in offer.proposals if p.recipient == "france")
    assert proposal.demand == ["languedoc"]
    assert proposal.note == "Yield."
    done = play(offer, france=[Respond(proposal_id=proposal.id, accept=True)])
    assert done.provinces["languedoc"].owner == "spain"
    assert done.provinces["languedoc"].unrest > 0
    assert not done.at_war("spain", "france")
    assert EventKind.PROVINCE_CEDED in kinds(done)


def test_terms_must_make_sense(state: GameState, play: Play) -> None:
    war = at_war(state, play)
    bad = play(
        war,
        spain=[
            ProposePeace(target="france", demand=["paris"]),
            ProposePeace(target="france", demand=["normandy"]),
        ],
    )
    assert reasons(bad) == [
        "Paris is a capital and cannot be handed over",
        "Normandy does not border Spain",
    ]
    chained = play(war, spain=[ProposePeace(target="france", demand=["gascony", "brittany"])])
    assert reasons(chained) == []  # Brittany borders Gascony, which Spain would get too


def test_a_tribute_is_paid_every_year(state: GameState, play: Play) -> None:
    war = at_war(state, play)
    offer = play(war, spain=[ProposePeace(target="france", ask_tribute=10)])
    done = play(offer, france=[Respond(proposal_id=proposal_to(offer, "france"), accept=True)])
    tribute = done.treaty("spain", "france", TreatyKind.TRIBUTE)
    assert tribute is not None
    assert (tribute.payer, tribute.amount) == ("france", 10)
    paid = [e for e in done.last_events if e.kind == EventKind.TRIBUTE_PAID]
    assert paid
    assert paid[0].data["ducats"] == 10


def test_an_army_limit_stops_recruiting(state: GameState, play: Play) -> None:
    war = at_war(state, play)
    offer = play(war, spain=[ProposePeace(target="france", limit_army=20)])
    done = play(offer, france=[Respond(proposal_id=proposal_to(offer, "france"), accept=True)])
    done.nations["france"].resources = Resources(ducats=500, manpower=100, iron=100)
    capped = play(done, france=[Recruit(province="paris", regiments=10)])
    assert reasons(capped) == ["the peace with Spain limits your army to 20 regiments"]


# ---------------------------------------------------------------- haggling


def test_a_peace_can_be_countered_and_the_counter_accepted(state: GameState, play: Play) -> None:
    war = at_war(state, play)
    offer = play(war, spain=[ProposePeace(target="france", demand=["languedoc", "gascony"])])
    counter = Terms(give=Resources(ducats=20), note="Gold, not land.")
    countered = play(
        offer,
        france=[Respond(proposal_id=proposal_to(offer, "france"), accept=False, counter=counter)],
    )
    assert EventKind.PROPOSAL_COUNTERED in kinds(countered)
    reply = next(p for p in countered.proposals if p.recipient == "spain")
    assert reply.sender == "france"
    assert reply.give == Resources(ducats=20)
    assert reply.reply_to is not None
    view = view_for(countered, "spain")
    assert view.proposals_to_answer[0].note == "Gold, not land."
    spain_before = countered.nations["spain"].resources.ducats
    done = play(countered, spain=[Respond(proposal_id=reply.id, accept=True)])
    assert not done.at_war("spain", "france")
    assert done.provinces["languedoc"].owner == "france"
    assert done.nations["spain"].resources.ducats >= spain_before + 20


def test_a_trade_counter_only_moves_goods(state: GameState, play: Play) -> None:
    offer = play(state, england=[ProposeTrade(target="sweden", give=Resources(ducats=20))])
    wrong = play(
        offer,
        sweden=[
            Respond(
                proposal_id=proposal_to(offer, "sweden"),
                accept=False,
                counter=Terms(demand=["york"]),
            )
        ],
    )
    assert reasons(wrong) == ["a trade's counter-offer can only give and receive"]
    assert EventKind.PROPOSAL_REJECTED in kinds(wrong)


def test_a_pact_cannot_be_countered(state: GameState, play: Play) -> None:
    offer = play(state, england=[ProposeNonAggression(target="france")])
    wrong = play(
        offer,
        france=[
            Respond(
                proposal_id=proposal_to(offer, "france"),
                accept=False,
                counter=Terms(give=Resources(ducats=5)),
            )
        ],
    )
    assert reasons(wrong) == ["a non aggression proposal cannot be countered"]


# ---------------------------------------------------------------- opinion


def test_gifts_win_hearts_and_wars_lose_them(state: GameState, play: Play) -> None:
    gift = play(state, england=[Gift(target="france", resources=Resources(ducats=40))])
    assert gift.opinion("france", "england") > 0
    war = play(gift, england=[DeclareWar(target="france")])
    assert war.opinion("france", "england") < 0


def test_breaking_a_treaty_shocks_every_court(state: GameState, play: Play) -> None:
    offer = play(state, england=[ProposeNonAggression(target="france")])
    pact = play(offer, france=[Respond(proposal_id=proposal_to(offer, "france"), accept=True)])
    assert pact.opinion("france", "england") > 0
    broken = play(pact, england=[DeclareWar(target="france")])
    assert broken.opinion("spain", "england") < 0
    assert broken.opinion("france", "england") < -40


def test_grudges_fade(state: GameState, play: Play) -> None:
    war = play(state, england=[DeclareWar(target="france")])
    first = war.opinion("france", "england")
    later = play(war)
    assert first < later.opinion("france", "england") < 0


def test_each_court_sees_what_the_others_think_of_it(state: GameState, play: Play) -> None:
    gift = play(state, england=[Gift(target="france", resources=Resources(ducats=40))])
    view = view_for(gift, "england")
    france = next(n for n in view.nations if n.id == "france")
    assert france.opinion_of_you > 0
    assert view_for(gift, "france").me.opinions["england"] > 0
