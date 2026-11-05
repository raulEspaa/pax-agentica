"""The offline evaluation: situations rebuilt from a seed, and rules that score a plan."""

import asyncio
from typing import Any

import pytest

from pax_agentica.agents import evals
from pax_agentica.agents.evals import Situation, items, score, views
from pax_agentica.agents.prompts import PlanRequest
from pax_agentica.cli import main
from pax_agentica.engine import NationView, new_game, view_for
from pax_agentica.engine.contract import CONTRACT_VERSION
from pax_agentica.engine.model import TreatyKind
from pax_agentica.engine.view import TreatyView
from pax_agentica.players.plan import Plan


@pytest.fixture(scope="module")
def france() -> NationView:
    return view_for(new_game(seed=1), "france")


def scores(plan: Plan | None, view: NationView) -> dict[str, float]:
    return {s.name: s.value for s in score(plan, view)}


def across_the_border(view: NationView) -> str:
    """A province the realm does not own that borders one it does."""
    mine = set(view.me.provinces)
    return next(p.id for p in view.provinces if p.id not in mine and mine & set(p.neighbors))


def far_from(view: NationView) -> str:
    """A province that borders nothing the realm holds."""
    held = set(view.me.held) | set(view.me.provinces)
    return next(
        p.id
        for p in view.provinces
        if p.id not in held and not held & {*p.neighbors, *p.sea_neighbors}
    )


def test_a_situation_is_the_view_of_that_year_in_a_game_of_bots(france: NationView) -> None:
    first, later = Situation(1, 1, "france"), Situation(1, 3, "france")

    seen = views([first, later])

    assert seen[first] == france
    assert seen[later].turn == 3
    assert seen[later].max_turns == france.max_turns  # the game is not cut short


def test_the_same_seed_gives_the_same_situations() -> None:
    some = [Situation(2, 2, "spain"), Situation(2, 2, "poland")]

    assert views(some) == views(some)


def test_an_item_keeps_three_numbers_and_the_contract() -> None:
    [item] = items([Situation(1, 8, "spain")])

    assert item == {
        "id": "seed1-turn8-spain",
        "input": {"seed": 1, "turn": 8, "nation": "spain"},
        "metadata": {"contract": CONTRACT_VERSION},
    }


def test_the_dataset_has_twenty_different_situations() -> None:
    assert len({s.id for s in evals.SITUATIONS}) == 20


def test_no_plan_is_not_valid_and_scores_nothing_else(france: NationView) -> None:
    assert scores(None, france) == {"valid": 0.0}


def test_a_sensible_plan_scores_full_marks(france: NationView) -> None:
    target = across_the_border(france)
    plan = Plan(army="conquer", conquer=[target], war_on="spain", befriend=["austria"])

    assert set(scores(plan, france).values()) == {1.0}


def test_names_that_do_not_exist_are_marked(france: NationView) -> None:
    assert scores(Plan(conquer=["atlantis"]), france)["real_names"] == 0.0


@pytest.mark.parametrize(
    "plan",
    [
        Plan(army="conquer", war_on="spain", peace_with=["spain"]),
        Plan(army="conquer", war_on="spain", befriend=["spain"]),
        Plan(army="defend", war_on="spain"),
    ],
)
def test_a_plan_that_contradicts_itself_is_not_consistent(plan: Plan, france: NationView) -> None:
    assert scores(plan, france)["consistent"] == 0.0


def test_conquering_its_own_land_is_not_consistent(france: NationView) -> None:
    assert scores(Plan(conquer=[france.me.capital]), france)["consistent"] == 0.0


def test_war_on_a_treaty_partner_breaks_the_treaty(france: NationView) -> None:
    truce = TreatyView(kind=TreatyKind.TRUCE, partner="spain", until_turn=5)
    bound = france.model_copy(update={"me": france.me.model_copy(update={"treaties": (truce,)})})

    assert scores(Plan(army="conquer", war_on="spain"), bound)["keeps_treaties"] == 0.0
    assert scores(Plan(army="conquer", war_on="austria"), bound)["keeps_treaties"] == 1.0


def test_reachable_is_the_share_of_conquests_on_the_border(france: NationView) -> None:
    near = across_the_border(france)

    assert scores(Plan(conquer=[near, far_from(france)]), france)["reachable"] == 0.5


class Fixed:
    """A model that always writes the same plan, or always fails."""

    def __init__(self, plan: Plan | None) -> None:
        self.plan = plan
        self.asked: list[PlanRequest] = []

    async def write_plan(self, request: PlanRequest) -> Plan:
        self.asked.append(request)
        if self.plan is None:
            raise ConnectionError("the model is down")
        return self.plan


def run_task(model: Fixed, situation: Situation) -> Any:
    seen = views([situation])
    task = evals.plan_task(model, seen)
    output = asyncio.run(task(item={"input": {"seed": 1, "turn": 1, "nation": "france"}}))
    return output, evals.evaluator(seen)(input=situation.__dict__, output=output)


def test_the_task_asks_for_a_plan_in_that_situation_and_the_scores_follow() -> None:
    model = Fixed(Plan(note="Grow."))

    output, evaluations = run_task(model, Situation(1, 1, "france"))

    assert "France" in model.asked[0].user or "france" in model.asked[0].user
    assert output == {"plan": Plan(note="Grow.").model_dump(mode="json")}
    assert {e["name"]: e["value"] for e in evaluations}["valid"] == 1.0


def test_a_failed_call_is_an_answer_scored_not_valid() -> None:
    output, evaluations = run_task(Fixed(None), Situation(1, 1, "france"))

    assert output["error"].startswith("ConnectionError")
    assert evaluations == [{"name": "valid", "value": 0.0, "comment": "no plan came back"}]


def test_an_evaluation_needs_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)

    with pytest.raises(SystemExit, match="Langfuse"):
        main(["eval", "--budget", "1"])
