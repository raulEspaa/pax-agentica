"""Grudges: the wrongs a court will not forget, and what they cost the wrongdoer."""

import asyncio
from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, Orders, resolve_turn, view_for
from pax_agentica.engine.actions import (
    DeclareWar,
    ProposeAlliance,
    ProposeNonAggression,
    ProposePeace,
    Respond,
)
from pax_agentica.players.greedy_bot import GreedyBot

type Play = Callable[..., GameState]


def test_a_betrayal_is_remembered_for_years(state: GameState, play: Play) -> None:
    offer = play(state, france=[ProposeNonAggression(target="spain")])
    pid = next(p.id for p in offer.proposals if p.recipient == "spain")
    pact = play(offer, spain=[Respond(proposal_id=pid, accept=True)])
    war = play(pact, france=[DeclareWar(target="spain")])
    grudge = next(g for g in war.nations["spain"].grudges if g.against == "france")
    assert "broke the non aggression" in grudge.reason
    assert grudge.until - grudge.since == war.rules.grudge_betrayal[0]
    assert EventKind.GRUDGE in [e.kind for e in war.last_events]
    seen = next(n for n in view_for(war, "france").nations if n.id == "spain")
    assert seen.remembers[0].reason == grudge.reason
    # it keeps weighing on the opinion year after year
    later = play(war)
    assert later.opinion("spain", "france") < war.opinion("spain", "france")


def test_land_taken_by_treaty_is_not_forgotten(state: GameState, play: Play) -> None:
    war = play(state, spain=[DeclareWar(target="france")])
    war.provinces["languedoc"].controller = "spain"
    offer = play(war, spain=[ProposePeace(target="france", demand=["languedoc"])])
    pid = next(p.id for p in offer.proposals if p.recipient == "france")
    done = play(offer, france=[Respond(proposal_id=pid, accept=True)])
    reasons = [g.reason for g in done.nations["france"].grudges if g.against == "spain"]
    assert "took Languedoc" in reasons


def test_a_wronged_bot_will_not_ally_and_says_why(state: GameState) -> None:
    offer = resolve_turn(state, {"france": Orders(actions=[ProposeNonAggression(target="spain")])})
    pid = next(p.id for p in offer.proposals if p.recipient == "spain")
    pact = resolve_turn(offer, {"spain": Orders(actions=[Respond(proposal_id=pid, accept=True)])})
    war = resolve_turn(pact, {"france": Orders(actions=[DeclareWar(target="spain")])})
    war.wars = []  # peace, somehow; the grudge stays
    war.opinions.setdefault("spain", {})["france"] = 50
    offer = resolve_turn(war, {"france": Orders(actions=[ProposeAlliance(target="spain")])})
    orders = asyncio.run(GreedyBot(1).decide(view_for(offer, "spain")))
    reply = next(a for a in orders.actions if isinstance(a, Respond))
    assert not reply.accept
    assert "not forgotten" in reply.note


def test_grudges_fade(state: GameState, play: Play) -> None:
    war = play(state, france=[DeclareWar(target="spain")])
    years = war.rules.grudge_war[0]
    war.turn += years
    assert not [g for g in play(war).nations["spain"].grudges if g.against == "france"]
