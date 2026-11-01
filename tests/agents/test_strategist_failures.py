"""A failing model never costs the nation its year: it retries once, then the last plan stands."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from pydantic import ValidationError

from pax_agentica.agents.prompts import PlanRequest
from pax_agentica.agents.strategist import Strategist
from pax_agentica.engine import NationView, new_game, view_for
from pax_agentica.players import Player
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.players.plan import Plan
from pax_agentica.runner import _ask, run_game

type Answer = Callable[[], Awaitable[Plan]]

GOOD = Plan(economy="save", army="defend", note="Save.")


async def good() -> Plan:
    return GOOD


async def raises() -> Plan:
    raise ConnectionError("the model is down")


async def hangs() -> Plan:
    await asyncio.sleep(60)
    return GOOD


async def invalid() -> Plan:
    return Plan.model_validate({"army": "raze"})


class Scripted:
    """A model that answers each request with the next of its answers, and the last one after."""

    def __init__(self, *answers: Answer) -> None:
        self.answers = list(answers)
        self.asked = 0

    async def write_plan(self, request: PlanRequest) -> Plan:
        answer = self.answers[min(self.asked, len(self.answers) - 1)]
        self.asked += 1
        return await answer()


@pytest.fixture
def france() -> NationView:
    return view_for(new_game(seed=1), "france")


def on_turn(view: NationView, turn: int) -> NationView:
    return view.model_copy(update={"turn": turn})


def test_an_invalid_answer_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        asyncio.run(invalid())


@pytest.mark.parametrize("failure", [raises, hangs, invalid])
def test_a_failure_is_tried_once_more(france: NationView, failure: Answer) -> None:
    model = Scripted(failure, good)
    ruler = Strategist(model, seed=1, timeout=0.01)

    orders = asyncio.run(ruler.decide(france))
    bots = asyncio.run(GreedyBot(1, plan=GOOD).decide(france))

    assert model.asked == 2
    assert orders.actions == bots.actions
    assert orders.thoughts.startswith("Save.")


@pytest.mark.parametrize(
    ("failure", "reason"),
    [(raises, "ConnectionError"), (hangs, "TimeoutError"), (invalid, "ValidationError")],
)
def test_before_any_plan_two_failures_play_the_year_with_none(
    france: NationView, failure: Answer, reason: str
) -> None:
    model = Scripted(failure)
    ruler = Strategist(model, seed=1, timeout=0.01)

    orders = asyncio.run(ruler.decide(france))

    assert model.asked == 2
    assert orders.actions == asyncio.run(GreedyBot(1).decide(france)).actions
    assert reason in orders.thoughts


def test_after_a_plan_two_failures_leave_the_last_plan_standing(france: NationView) -> None:
    ruler = Strategist(Scripted(good, raises), seed=1)
    asyncio.run(ruler.decide(on_turn(france, 1)))
    twin = GreedyBot(1, plan=GOOD)
    asyncio.run(twin.decide(on_turn(france, 1)))

    orders = asyncio.run(ruler.decide(on_turn(france, 3)))

    assert orders.actions == asyncio.run(twin.decide(on_turn(france, 3))).actions
    assert orders.thoughts.startswith("Save.")
    assert "ConnectionError" in orders.thoughts
    assert "last plan stands" in orders.thoughts


def test_a_failed_year_asks_again_the_next_year(france: NationView) -> None:
    model = Scripted(raises, raises, good)  # the first year spends two attempts
    ruler = Strategist(model, seed=1)

    asyncio.run(ruler.decide(on_turn(france, 1)))
    orders = asyncio.run(ruler.decide(on_turn(france, 2)))

    assert model.asked == 3
    assert orders.thoughts.startswith("Save.")


def test_a_broken_model_forfeits_no_year_of_a_game() -> None:
    state = new_game(seed=1, max_turns=5)
    players: dict[str, Player] = {n: GreedyBot(1) for n in state.nations}
    players["france"] = Strategist(Scripted(raises), seed=1)

    record = asyncio.run(run_game(state, players))

    assert all("france" not in turn.errors for turn in record.turns)
    assert all("ConnectionError" in turn.orders["france"].thoughts for turn in record.turns)


def test_the_runner_can_still_stop_a_ruler_that_takes_too_long(france: NationView) -> None:
    """A cancellation from outside is not a model's failure: it must not be swallowed."""
    ruler = Strategist(Scripted(hangs), seed=1, timeout=30)

    assert asyncio.run(_ask(ruler, france, timeout=0.01)) == "timed out after 0.01s"
