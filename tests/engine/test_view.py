"""Fog of war: a nation sees its own world, its borders and its friends, nothing more."""

from collections.abc import Callable

from pax_agentica.engine import GameState, NationView, view_for
from pax_agentica.engine.actions import ProposeAlliance, Recruit, Respond
from pax_agentica.engine.mechanics import nation_income
from pax_agentica.engine.view import NationSummary

type Play = Callable[..., GameState]


def troops(view: NationView, province: str) -> int | None:
    return next(p.troops for p in view.provinces if p.id == province)


def test_you_see_troops_at_home_and_across_the_border(state: GameState) -> None:
    view = view_for(state, "france")
    assert troops(view, "paris") == state.provinces["paris"].troops
    assert troops(view, "aragon") == state.provinces["aragon"].troops  # borders Languedoc
    assert troops(view, "london") == state.provinces["london"].troops  # across the Channel
    assert troops(view, "moscow") is None


def test_allies_share_their_vision(state: GameState, play: Play) -> None:
    offered = play(state, france=[ProposeAlliance(target="russia")])
    pid = view_for(offered, "russia").proposals_to_answer[0].id
    allied = play(offered, russia=[Respond(proposal_id=pid, accept=True)])
    assert troops(view_for(allied, "france"), "moscow") == allied.provinces["moscow"].troops


def test_other_nations_treasuries_are_secret() -> None:
    assert "resources" not in NationSummary.model_fields


def test_you_only_see_the_events_you_could_witness(state: GameState, play: Play) -> None:
    new = play(state, england=[Recruit(province="york", regiments=1)])
    assert any(e.data.get("regiments") == 1 for e in view_for(new, "england").last_turn_events)
    assert not view_for(new, "france").last_turn_events


def test_the_view_reports_your_economy(state: GameState) -> None:
    me = view_for(state, "spain").me
    assert me.income_per_turn == nation_income(state, "spain")
    assert me.army_upkeep_per_turn.grain == state.troops_of("spain")
    assert me.manpower_cap > me.resources.manpower
    assert me.provinces == tuple(state.provinces_of("spain"))
    assert {n.id for n in view_for(state, "spain").nations} == set(state.nations) - {"spain"}


def test_a_view_round_trips_through_json(state: GameState) -> None:
    view = view_for(state, "ottomans")
    assert NationView.model_validate_json(view.model_dump_json()) == view
