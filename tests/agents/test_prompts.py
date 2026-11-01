"""The request for a plan: who the monarch is, what they know, and how little it costs to say."""

import asyncio
import json

import pytest

from pax_agentica.agents.prompts import PlanRequest, build_request
from pax_agentica.engine import GameState, NationView, new_game, view_for
from pax_agentica.engine.model import Ruler, Trait
from pax_agentica.players import Player
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.players.plan import Plan
from pax_agentica.runner import TurnRecord, run_game

MAX_CHARACTERS = 20_000


@pytest.fixture
def france() -> NationView:
    return view_for(new_game(seed=1), "france")


def with_ruler(view: NationView, ruler: Ruler | None) -> NationView:
    return view.model_copy(update={"me": view.me.model_copy(update={"ruler": ruler})})


def test_tells_the_model_who_it_is(france: NationView) -> None:
    system = build_request(france).system

    assert "France" in system
    assert "King Louis XII" in system
    assert "age 43" in system
    assert "administration 3" in system
    assert "diplomacy 3" in system
    assert "military 1" in system
    assert "thrifty" in system
    assert "charming" in system
    assert "Father of the People" in system


def test_names_the_ambition_of_the_reign_when_there_is_one(france: NationView) -> None:
    assert "no ambition" in build_request(france).system

    ambition = france.me.agenda_offers[0]
    view = france.model_copy(update={"me": france.me.model_copy(update={"agenda": ambition})})

    assert ambition.name in build_request(view).system
    assert ambition.text in build_request(view).system


def test_after_a_succession_the_request_names_the_new_monarch(france: NationView) -> None:
    assert france.me.ruler is not None
    heir = france.me.ruler.model_copy(
        update={"title": "Queen", "name": "Anne", "traits": [Trait.CUNNING]}
    )

    system = build_request(with_ruler(france, heir)).system

    assert "Queen Anne" in system
    assert "cunning" in system
    assert "Louis" not in system


def test_a_throne_without_a_monarch_still_makes_a_request(france: NationView) -> None:
    assert "France" in build_request(with_ruler(france, None)).system


def test_the_report_is_the_compact_view_and_the_last_plan(france: NationView) -> None:
    last = Plan(conquer=["flanders"], note="The cloth towns first.")

    assert "## courts" in build_request(france).user
    assert "first plan" in build_request(france).user
    assert "The cloth towns first." in build_request(france, last).user


def test_tells_what_never_changes_before_what_does(france: NationView) -> None:
    """Providers cache a shared opening, so the rules come first, identical for every crown."""
    spain = view_for(new_game(seed=1), "spain")
    mine, theirs = build_request(france).system, build_request(spain).system

    assert mine.split("WHO YOU ARE")[0] == theirs.split("WHO YOU ARE")[0]


def size(request: PlanRequest) -> int:
    schema = json.dumps(Plan.model_json_schema())
    return len(request.system) + len(request.user) + len(schema)


def test_every_request_of_a_long_game_stays_under_the_limit() -> None:
    state = new_game(seed=2, max_turns=40)
    players: dict[str, Player] = {n: GreedyBot(2) for n in state.nations}
    longest = Plan(
        conquer=["flanders"] * 5,
        peace_with=["spain"] * 8,
        befriend=["austria"] * 3,
        note="x" * 300,
    )
    sizes: list[int] = []

    def measure(_: TurnRecord, now: GameState) -> None:
        sizes.extend(size(build_request(view_for(now, n), longest)) for n in now.alive_nations())

    asyncio.run(run_game(state, players, on_turn=measure))

    assert max(sizes) < MAX_CHARACTERS
