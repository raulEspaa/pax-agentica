"""The greedy bot carries out a plan: the plan says what, the bot works out how."""

import asyncio

import pytest
from pydantic import ValidationError

from pax_agentica.engine import GameState, Orders, resolve_turn, view_for
from pax_agentica.engine.actions import (
    DeclareWar,
    ProposeAlliance,
    ProposePeace,
    Research,
    Respond,
)
from pax_agentica.engine.model import Resources, TechBranch
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.players.plan import Plan


def orders(state: GameState, nation: str, plan: Plan | None, seed: int = 0) -> Orders:
    return asyncio.run(GreedyBot(seed, plan=plan).decide(view_for(state, nation)))


def ready_for_war(state: GameState) -> GameState:
    """Some years on, France with a great army on the Spanish border."""
    state.turn = 10
    view = view_for(state, "france")
    spanish = {p.id for p in view.provinces if p.owner == "spain"}
    for p in view.provinces:
        if p.owner == "france" and set(p.neighbors) & spanish:
            state.provinces[p.id].troops = 40
    return state


def test_a_plan_is_small_and_strict() -> None:
    assert Plan() == Plan(economy="balanced", army="defend")
    with pytest.raises(ValidationError):
        Plan(army="raze")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Plan(befriend=["a", "b", "c", "d"])
    with pytest.raises(ValidationError):
        Plan.model_validate({"economy": "grow", "taxes": "high"})


def test_a_defending_plan_starts_no_war(state: GameState) -> None:
    ready = ready_for_war(state)
    for seed in range(6):
        acts = orders(ready, "france", Plan(army="defend"), seed).actions
        assert not any(isinstance(a, DeclareWar) for a in acts)


def test_the_plan_names_the_war(state: GameState) -> None:
    ready = ready_for_war(state)
    for seed in range(4):
        acts = orders(ready, "france", Plan(army="conquer", war_on="spain"), seed).actions
        wars = [a for a in acts if isinstance(a, DeclareWar)]
        assert [w.target for w in wars] == ["spain"]


def test_a_court_the_plan_spares_is_never_attacked(state: GameState) -> None:
    ready = ready_for_war(state)
    plan = Plan(army="conquer", peace_with=["spain"])
    for seed in range(6):
        acts = orders(ready, "france", plan, seed).actions
        assert not any(isinstance(a, DeclareWar) and a.target == "spain" for a in acts)


def test_the_plan_ends_a_war_it_does_not_want(state: GameState) -> None:
    war = resolve_turn(state, {"france": Orders(actions=[DeclareWar(target="spain")])})
    war = resolve_turn(war, {})
    acts = orders(war, "france", Plan(peace_with=["spain"])).actions
    assert any(isinstance(a, ProposePeace) and a.target == "spain" for a in acts)


def test_the_plan_takes_the_peace_it_asked_for(state: GameState) -> None:
    war = resolve_turn(state, {"france": Orders(actions=[DeclareWar(target="spain")])})
    war.wars[0].battles["spain"] = 3  # Spain is ahead: on its own it would hold out
    offered = resolve_turn(war, {"france": Orders(actions=[ProposePeace(target="spain")])})
    alone = orders(offered, "spain", None)
    planned = orders(offered, "spain", Plan(peace_with=["france"]))
    assert not next(a for a in alone.actions if isinstance(a, Respond)).accept
    assert next(a for a in planned.actions if isinstance(a, Respond)).accept


def test_the_plan_courts_its_friends(state: GameState) -> None:
    acts = orders(state, "france", Plan(befriend=["austria"])).actions
    assert any(isinstance(a, ProposeAlliance) and a.target == "austria" for a in acts)


def test_the_plan_chooses_what_to_study(state: GameState) -> None:
    state.nations["france"].resources = Resources(ducats=2000, iron=50, timber=50, grain=50)
    for branch in (TechBranch.NAVAL, TechBranch.ADMINISTRATION):
        acts = orders(state, "france", Plan(research=[branch])).actions
        studied = [a.branch for a in acts if isinstance(a, Research)]
        assert studied == [branch]


def test_a_saving_plan_spends_less_than_a_growing_one(state: GameState) -> None:
    state.nations["france"].resources = Resources(ducats=220, iron=20, timber=20, grain=40)

    def spent(plan: Plan) -> int:
        acts = orders(state, "france", plan).actions
        return sum(1 for a in acts if a.type in ("develop", "build", "improve"))

    assert spent(Plan(economy="save")) < spent(Plan(economy="grow"))


def test_the_plan_is_in_the_rulers_thoughts(state: GameState) -> None:
    thoughts = orders(state, "france", Plan(note="Grow rich, then take Flanders.")).thoughts
    assert thoughts.startswith("The plan: Grow rich, then take Flanders.")


def test_the_bot_can_change_its_plan(state: GameState) -> None:
    bot = GreedyBot(0)
    bot.follow(Plan(note="first"))
    assert bot.following == Plan(note="first")
    bot.follow(None)
    assert bot.following is None
