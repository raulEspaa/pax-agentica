"""The controls for the council: the greedy bot with plans that no model wrote."""

import asyncio
import random

from pax_agentica.engine import new_game, resolve_turn, view_for
from pax_agentica.players import Player
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.players.plan import Plan
from pax_agentica.players.planned import STEADY, RandomPlanBot, SteadyBot, random_plan
from pax_agentica.runner import run_game


def test_the_steady_bot_follows_one_plan_all_game() -> None:
    bot = SteadyBot(seed=1)

    assert (bot.name, bot.following) == ("steady", STEADY)


def test_a_random_plan_names_only_what_the_view_shows() -> None:
    view = view_for(new_game(seed=1), "france")
    provinces = {p.id for p in view.provinces if p.owner != "france"}
    courts = {n.id for n in view.nations if n.alive} - {"france"}

    for i in range(50):
        plan = random_plan(view, random.Random(i))
        assert set(plan.conquer) <= provinces
        assert {*plan.peace_with, *plan.befriend} <= courts
        assert plan.war_on is None or (plan.army == "conquer" and plan.war_on in courts)


def test_the_random_plan_changes_every_second_year_and_repeats_with_the_seed() -> None:
    def plans(seed: int) -> list[Plan | None]:
        bot, state = RandomPlanBot(seed), new_game(seed=1)
        seen: list[Plan | None] = []
        for _ in range(4):
            asyncio.run(bot.decide(view_for(state, "france")))
            seen.append(bot.following)
            state = resolve_turn(state, {})
        return seen

    first = plans(3)
    assert first[0] == first[1]
    assert first[1] != first[2]
    assert first[2] == first[3]
    assert first == plans(3)
    assert first != plans(4)


def test_both_controls_play_a_whole_game() -> None:
    state = new_game(seed=2, max_turns=6)
    players: dict[str, Player] = {n: GreedyBot(2) for n in state.nations}
    players |= {"france": SteadyBot(2), "spain": RandomPlanBot(2)}

    record = asyncio.run(run_game(state, players))

    assert len(record.turns) == 6
