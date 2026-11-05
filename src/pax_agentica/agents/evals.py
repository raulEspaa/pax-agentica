"""Evaluating the strategist offline: real situations, a model's plans, and rules that score them.

A situation is a moment of a game of greedy bots: a seed, a year and a nation. Only those three
numbers are stored, and the view is rebuilt by replaying the game, which the seed makes exact: so
a dataset item stays tiny, and the same situations serve any later prompt. A rule change would
change them too, so each item records the contract it was made under.

Each plan gets scores from rules, cheap and certain, before any LLM judge is worth its cost:

    valid           the model answered with a plan at all
    real_names      every province and court it names exists
    consistent      it does not fight a court it would also befriend or leave in peace, nor
                    conquer its own land, and asks for war only with army=conquer
    keeps_treaties  it makes no war on a court the realm has a treaty with
    reachable       the share of its conquests that border land the realm holds
"""

import asyncio
from collections.abc import Callable, Coroutine, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from pax_agentica.agents.checks import clean_plan
from pax_agentica.agents.prompts import PROMPT_VERSION, build_request
from pax_agentica.agents.strategist import PlanModel
from pax_agentica.engine import GameState, NationView, Orders, new_game, resolve_turn, view_for
from pax_agentica.engine.contract import CONTRACT_VERSION
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.players.plan import Plan

if TYPE_CHECKING:
    from langfuse import Langfuse
    from langfuse.experiment import EvaluatorFunction, ExperimentResult, TaskFunction

DATASET = "strategist-situations"
NATIONS = ("france", "spain", "austria", "ottomans", "poland")
TURNS = (1, 8, 15, 22)  # the opening, and then every seven years of a fifty-year game


@dataclass(frozen=True)
class Situation:
    seed: int
    turn: int
    nation: str

    @property
    def id(self) -> str:
        return f"seed{self.seed}-turn{self.turn}-{self.nation}"


SITUATIONS = tuple(Situation(1, turn, nation) for turn in TURNS for nation in NATIONS)


@dataclass(frozen=True)
class Score:
    name: str
    value: float
    comment: str = ""


def views(situations: Iterable[Situation]) -> dict[Situation, NationView]:
    """What each nation saw at the start of each year: one game of greedy bots for each seed.

    The game keeps its usual length and stops early, or the views would say it ends soon."""
    wanted = list(situations)
    found: dict[Situation, NationView] = {}
    for seed in sorted({s.seed for s in wanted}):
        here = [s for s in wanted if s.seed == seed]
        state = new_game(seed)
        bots = {n: GreedyBot(seed) for n in state.nations}
        for turn in range(1, max(s.turn for s in here) + 1):
            for s in here:
                if s.turn == turn:
                    found[s] = view_for(state, s.nation)
            state = resolve_turn(state, asyncio.run(_decide(bots, state)))
    return found


async def _decide(bots: dict[str, GreedyBot], state: GameState) -> dict[str, Orders]:
    alive = [n for n in bots if state.nations[n].alive]
    orders = await asyncio.gather(*(bots[n].decide(view_for(state, n)) for n in alive))
    return dict(zip(alive, orders, strict=True))


def score(plan: Plan | None, view: NationView) -> list[Score]:
    """The rule-based scores of a plan written for this view. `None`: the model gave no plan."""
    if plan is None:
        return [Score("valid", 0.0, "no plan came back")]
    _, dropped = clean_plan(plan, view)
    return [
        Score("valid", 1.0),
        Score("real_names", float(not dropped), ", ".join(dropped)),
        _consistent(plan, view),
        _keeps_treaties(plan, view),
        _reachable(plan, view),
    ]


def _consistent(plan: Plan, view: NationView) -> Score:
    faults = []
    if plan.war_on and plan.war_on in {*plan.peace_with, *plan.befriend}:
        faults.append(f"war on {plan.war_on} and peace or friendship with it too")
    if plan.war_on and plan.army != "conquer":
        faults.append(f"war on {plan.war_on} with army={plan.army}")
    own = set(view.me.provinces)
    faults.extend(f"conquer its own {p}" for p in plan.conquer if p in own)
    return Score("consistent", float(not faults), "; ".join(faults))


def _keeps_treaties(plan: Plan, view: NationView) -> Score:
    bound = {t.partner: t.kind for t in view.me.treaties}
    if plan.war_on in bound:
        return Score(
            "keeps_treaties", 0.0, f"war on {plan.war_on}, bound by a {bound[plan.war_on]}"
        )
    return Score("keeps_treaties", 1.0)


def _reachable(plan: Plan, view: NationView) -> Score:
    if not plan.conquer:
        return Score("reachable", 1.0, "nothing to conquer")
    provinces = {p.id: p for p in view.provinces}
    held = set(view.me.held) | set(view.me.provinces)
    far = [
        target
        for target in plan.conquer
        if target in provinces
        and not held & {*provinces[target].neighbors, *provinces[target].sea_neighbors}
    ]
    share = 1 - len(far) / len(plan.conquer)
    return Score("reachable", share, f"no border with {', '.join(far)}" if far else "")


type Task = Callable[..., Coroutine[Any, Any, dict[str, Any]]]


def plan_task(model: PlanModel, seen: dict[Situation, NationView]) -> Task:
    """What an experiment runs on each item: the plan the model writes for that situation.

    A failure is an answer too, scored as not valid, so it returns instead of raising."""

    async def task(*, item: Any, **_: Any) -> dict[str, Any]:
        situation = Situation(**_input(item))
        try:
            plan = await model.write_plan(build_request(seen[situation], None))
        except Exception as exc:
            return {"error": f"{type(exc).__name__} {' '.join(str(exc).split())}"[:300]}
        return {"plan": plan.model_dump(mode="json")}

    return task


def evaluator(seen: dict[Situation, NationView]) -> Callable[..., list[dict[str, Any]]]:
    """The rule-based scores, in the form a Langfuse experiment takes them."""

    def evaluate(*, input: Any, output: Any, **_: Any) -> list[dict[str, Any]]:
        situation = Situation(**input)
        written = output.get("plan") if isinstance(output, dict) else None
        plan = Plan.model_validate(written) if written is not None else None
        return [
            {"name": s.name, "value": s.value, "comment": s.comment or None}
            for s in score(plan, seen[situation])
        ]

    return evaluate


def items(situations: Sequence[Situation]) -> list[dict[str, Any]]:
    """The situations as dataset items: three numbers each, and the contract they come from."""
    return [
        {
            "id": s.id,
            "input": {"seed": s.seed, "turn": s.turn, "nation": s.nation},
            "metadata": {"contract": CONTRACT_VERSION},
        }
        for s in situations
    ]


def run(
    langfuse: "Langfuse", model: PlanModel, situations: Sequence[Situation], run_name: str
) -> "ExperimentResult":
    """Write the situations into the Langfuse dataset, and run the model over them as one run.

    Runs on the same dataset sit side by side in Langfuse, which is how models and prompts are
    compared. Items are written by id, so writing them again changes nothing."""
    langfuse.create_dataset(name=DATASET, description="Moments of greedy-bot games to plan from")
    for item in items(situations):
        langfuse.create_dataset_item(dataset_name=DATASET, **item)
    wanted = {s.id for s in situations}
    data = [i for i in langfuse.get_dataset(DATASET).items if i.id in wanted]
    seen = views(situations)
    return langfuse.run_experiment(
        name=DATASET,
        run_name=run_name,
        data=data,
        task=cast("TaskFunction", plan_task(model, seen)),
        evaluators=[cast("EvaluatorFunction", evaluator(seen))],
        max_concurrency=4,
        metadata={"prompt": PROMPT_VERSION, "contract": CONTRACT_VERSION},
    )


def _input(item: Any) -> dict[str, Any]:
    """A dataset item from Langfuse keeps its input as an attribute; a local one, as a key."""
    found = item["input"] if isinstance(item, dict) else item.input
    return dict(found)
