"""The strategist: a monarch who writes a plan every second year and lets the bot carry it out."""

import asyncio
from itertools import pairwise

import pytest

from pax_agentica.agents.prompts import PlanRequest
from pax_agentica.agents.strategist import Strategist
from pax_agentica.engine import NationView, Orders, new_game, view_for
from pax_agentica.players import Player
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.players.plan import Plan
from pax_agentica.runner import run_game


class FakeModel:
    """A model that always answers the same plan, and remembers how often it was asked."""

    def __init__(self, plan: Plan | None = None) -> None:
        self.plan = plan or Plan()
        self.requests: list[PlanRequest] = []

    async def write_plan(self, request: PlanRequest) -> Plan:
        self.requests.append(request)
        return self.plan


class Recording:
    """Remembers the turns in which a ruler asked its model, by watching the model's count."""

    def __init__(self, ruler: Strategist, model: FakeModel) -> None:
        self.ruler = ruler
        self.model = model
        self.turns_asked: list[int] = []

    @property
    def name(self) -> str:
        return self.ruler.name

    async def decide(self, view: NationView) -> Orders:
        before = len(self.model.requests)
        orders = await self.ruler.decide(view)
        self.turns_asked += [view.turn] * (len(self.model.requests) - before)
        return orders


def play_years(model: FakeModel, views: list[NationView]) -> list[int]:
    """Have a strategist decide these years, and return the turns in which it asked its model."""
    ruler = Recording(Strategist(model, seed=1), model)
    for view in views:
        asyncio.run(ruler.decide(view))
    return ruler.turns_asked


def year(view: NationView, turn: int, **me: object) -> NationView:
    """The same view on another turn, with these fields of the realm changed."""
    return view.model_copy(update={"turn": turn, "me": view.me.model_copy(update=me)})


@pytest.fixture
def france() -> NationView:
    return view_for(new_game(seed=1), "france")


def test_asks_in_the_first_year_and_then_every_second_year(france: NationView) -> None:
    views = [year(france, turn) for turn in range(1, 31)]

    assert play_years(FakeModel(), views) == list(range(1, 31, 2))


def test_in_a_real_game_never_asks_twice_a_year_nor_waits_more_than_two() -> None:
    state = new_game(seed=1, max_turns=30)
    model = FakeModel()
    france = Recording(Strategist(model, seed=1), model)
    players: dict[str, Player] = {n: GreedyBot(1) for n in state.nations}
    players["france"] = france

    asyncio.run(run_game(state, players))

    asked = france.turns_asked
    assert asked[0] == 1
    assert len(asked) > 1
    assert all(1 <= later - earlier <= 2 for earlier, later in pairwise(asked))


def test_a_war_that_starts_asks_for_a_plan_at_once(france: NationView) -> None:
    views = [year(france, 1), year(france, 2, at_war_with=("spain",))]

    assert play_years(FakeModel(), views) == [1, 2]


def test_a_war_that_ends_asks_for_a_plan_at_once(france: NationView) -> None:
    views = [year(france, 1, at_war_with=("spain",)), year(france, 2, at_war_with=())]

    assert play_years(FakeModel(), views) == [1, 2]


def test_a_province_lost_asks_for_a_plan_at_once(france: NationView) -> None:
    views = [year(france, 1), year(france, 2, provinces=france.me.provinces[1:])]

    assert play_years(FakeModel(), views) == [1, 2]


def test_a_province_won_can_wait_for_the_next_plan(france: NationView) -> None:
    views = [year(france, 1), year(france, 2, provinces=(*france.me.provinces, "flanders"))]

    assert play_years(FakeModel(), views) == [1]


def test_a_new_monarch_asks_for_a_plan_at_once(france: NationView) -> None:
    assert france.me.ruler is not None
    heir = france.me.ruler.model_copy(update={"name": "Francis", "since": 2})
    views = [year(france, 1), year(france, 2, ruler=heir)]

    assert play_years(FakeModel(), views) == [1, 2]


def test_the_two_years_count_again_from_a_plan_asked_at_once(france: NationView) -> None:
    at_war = ("spain",)
    views = [
        year(france, 1),
        year(france, 2, at_war_with=at_war),
        year(france, 3, at_war_with=at_war),
        year(france, 4, at_war_with=at_war),
    ]

    assert play_years(FakeModel(), views) == [1, 2, 4]


def test_gives_exactly_the_orders_of_the_bot_with_that_plan() -> None:
    view = view_for(new_game(seed=1), "france")
    plan = Plan(economy="grow", army="build_up", note="France must grow before it fights.")

    mine = asyncio.run(Strategist(FakeModel(plan), seed=1).decide(view))
    bots = asyncio.run(GreedyBot(1, plan=plan).decide(view))

    assert mine.actions == bots.actions
    assert mine.thoughts.startswith("France must grow before it fights.")


def test_shows_the_monarch_their_own_last_plan(france: NationView) -> None:
    model = FakeModel(Plan(note="The cloth towns first."))

    play_years(model, [year(france, 1), year(france, 3)])

    assert "The cloth towns first." not in model.requests[0].user
    assert "The cloth towns first." in model.requests[1].user


def test_carries_out_the_plan_without_what_names_nothing_real(france: NationView) -> None:
    model = FakeModel(Plan(conquer=["atlantis", "flanders"], note="West."))
    ruler = Strategist(model, seed=1)

    mine = asyncio.run(ruler.decide(france))
    cleaned = Plan(conquer=["flanders"], note="West.")
    bots = asyncio.run(GreedyBot(1, plan=cleaned).decide(france))

    assert mine.actions == bots.actions
    assert mine.thoughts.startswith("West.")
    assert "conquer atlantis" in mine.thoughts


def test_says_what_was_dropped_only_in_the_year_of_the_plan(france: NationView) -> None:
    ruler = Strategist(FakeModel(Plan(conquer=["atlantis"])), seed=1)
    asyncio.run(ruler.decide(year(france, 1)))

    assert "atlantis" not in asyncio.run(ruler.decide(year(france, 2))).thoughts


def test_shows_the_monarch_the_plan_that_stood(france: NationView) -> None:
    model = FakeModel(Plan(conquer=["atlantis", "flanders"]))

    play_years(model, [year(france, 1), year(france, 3)])

    assert "flanders" in model.requests[1].user.split("THE REPORT")[0]
    assert "atlantis" not in model.requests[1].user


def test_keeps_following_the_last_plan_in_a_year_without_a_new_one() -> None:
    state = new_game(seed=1)
    plan = Plan(economy="save", army="defend", note="Save.")
    ruler = Strategist(FakeModel(plan), seed=1)
    asyncio.run(ruler.decide(view_for(state, "france")))
    next_year = view_for(state, "france").model_copy(update={"turn": 2})

    mine = asyncio.run(ruler.decide(next_year))

    # The first bot carried out a plan a year ago: compare with one in the same position.
    twin = GreedyBot(1, plan=plan)
    asyncio.run(twin.decide(view_for(state, "france")))
    assert mine.actions == asyncio.run(twin.decide(next_year)).actions
    assert mine.thoughts.startswith("Save.")
