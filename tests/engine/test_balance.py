"""The balance of Europe: war's weariness, money that buys what is lacking, the burden of a great
realm, the hegemon all Europe fears, the free provinces that arm beside it, and revanche."""

from collections.abc import Callable

from pax_agentica.engine import EventKind, GameState, view_for
from pax_agentica.engine.actions import ProposeCoalition, ProposePeace, Respond
from pax_agentica.engine.mechanics import hegemon, lost_land, peace_cost, revanche
from pax_agentica.engine.model import UnitKind
from pax_agentica.engine.realm import modifiers

type Play = Callable[..., GameState]


def reasons(state: GameState) -> list[str]:
    return [str(e.data["reason"]) for e in state.last_events if e.kind == EventKind.ORDER_REJECTED]


def test_weariness_costs_stability_only_at_war(state: GameState, play: Play) -> None:
    state.nations["france"].war_exhaustion = 15
    stability = state.nations["france"].stability
    calm = play(state)
    assert calm.nations["france"].stability >= stability  # at peace it heals, it does not bite
    assert calm.nations["france"].war_exhaustion < 15


def test_a_great_realm_pays_the_burden_of_empire(state: GameState) -> None:
    before = modifiers(state, "spain").building_discount
    for pid in list(state.provinces)[:30]:
        state.provinces[pid].owner = "spain"
        state.provinces[pid].development = 6
    assert state.score("spain") > state.rules.burden_from
    assert modifiers(state, "spain").building_discount < before
    assert any("burden of empire" in line for line in modifiers(state, "spain").sources)


def test_the_hegemon_may_be_leagued_against_without_infamy(state: GameState, play: Play) -> None:
    assert hegemon(state) is None
    for pid in ("lisbon", "porto", "navarre", "provence", "milan", "naples", "sicily"):
        state.provinces[pid].owner = "spain"
        state.provinces[pid].development = 8
    assert hegemon(state) == "spain"
    assert view_for(state, "france").hegemon == "spain"
    assert state.nations["spain"].infamy < state.rules.coalition_infamy
    asked = play(state, france=[ProposeCoalition(target="england", against="spain")])
    assert not any("does not frighten Europe" in r for r in reasons(asked))


def test_the_free_provinces_arm_beside_a_feared_conqueror(state: GameState, play: Play) -> None:
    state.nations["spain"].infamy = state.rules.coalition_infamy + 1
    before = state.provinces["navarre"].troops
    armed = play(state)
    assert armed.provinces["navarre"].troops == before + 1
    far = state.provinces["scotland"].troops
    assert armed.provinces["scotland"].troops == far


def test_lost_land_is_won_back_with_fervour(state: GameState, play: Play) -> None:
    from pax_agentica.engine.actions import DeclareWar

    war = play(state, spain=[DeclareWar(target="france")])
    war.provinces["languedoc"].controller = "spain"
    war.provinces["languedoc"].set_army({UnitKind.INFANTRY: 3})
    offer = play(war, spain=[ProposePeace(target="france", demand=["languedoc"])])
    proposal = next(p for p in offer.proposals if p.recipient == "france")
    done = play(offer, france=[Respond(proposal_id=proposal.id, accept=True)])
    assert done.provinces["languedoc"].owner == "spain"
    assert "languedoc" in done.nations["france"].lost
    assert revanche(done, "france", "languedoc")
    assert lost_land(done, "france") == ["languedoc"]
    assert view_for(done, "france").me.lost == ("languedoc",)
    assert modifiers(done, "france").morale > modifiers(state, "france").morale
    full = peace_cost(done, "spain", provinces=["languedoc"])
    assert peace_cost(done, "spain", claimant="france", provinces=["languedoc"]) < full
    infamy = done.nations["france"].infamy
    done.provinces["languedoc"].owner = "spain"
    from pax_agentica.engine.resolve import _Resolver  # the cession, as a peace makes it

    r = _Resolver(done.model_copy(deep=True), {})
    r._cede("languedoc", "spain", "france")
    assert r.s.nations["france"].infamy == infamy  # its own, won back: no one fears it for that
    assert "languedoc" not in r.s.nations["france"].lost
