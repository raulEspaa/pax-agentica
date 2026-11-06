"""Controls for the council: the greedy bot carrying out plans that no model wrote.

The council plays through `GreedyBot(plan=...)`, so a gain over the plain bot could come from
following any plan at all rather than from the model's. These two rulers separate the two:

- `steady`: one fixed plan for the whole game (grow the economy, build up the army).
- `random-plan`: a new plan drawn at random every second year, as often as the strategist plans,
  naming only provinces and courts the view shows.

If the council beats both, the model's plans are worth something; if a control does as well,
the gain was the plan-following bot's.
"""

import random

from pax_agentica.engine import NationView, Orders
from pax_agentica.engine.model import TechBranch
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.players.plan import Army, Economy, Plan

STEADY = Plan(economy="grow", army="build_up", note="a fixed plan, the same every year")
YEARS_BETWEEN_PLANS = 2  # as the strategist's (agents/strategist.py)

_ECONOMIES: tuple[Economy, ...] = ("grow", "balanced", "save")
_ARMIES: tuple[Army, ...] = ("defend", "build_up", "conquer")


class SteadyBot(GreedyBot):
    """The greedy bot with one plan, never changed."""

    def __init__(self, seed: int = 0) -> None:
        super().__init__(seed, plan=STEADY)

    @property
    def name(self) -> str:
        return "steady"


class RandomPlanBot:
    """The greedy bot with a new random plan every second year."""

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed
        self._bot = GreedyBot(seed)

    @property
    def name(self) -> str:
        return "random-plan"

    @property
    def following(self) -> Plan | None:
        return self._bot.following

    async def decide(self, view: NationView) -> Orders:
        if (view.turn - 1) % YEARS_BETWEEN_PLANS == 0:
            rng = random.Random(f"{self.seed}:{view.me.id}:{view.turn}:plan")  # noqa: S311
            self._bot.follow(random_plan(view, rng))
        return await self._bot.decide(view)


def random_plan(view: NationView, rng: random.Random) -> Plan:
    """A plan of the right shape and no thought: its targets are real, its choices are dice."""
    me = view.me.id
    mine = {p.id for p in view.provinces if p.owner == me}
    border = sorted(
        {n for p in view.provinces if p.id in mine for n in p.neighbors if n not in mine}
    )
    owners = {p.id: p.owner for p in view.provinces}
    neighbours = sorted({o for n in border if (o := owners.get(n)) and o != me})
    courts = sorted(n.id for n in view.nations if n.alive and n.id != me)
    army = rng.choice(_ARMIES)
    return Plan(
        economy=rng.choice(_ECONOMIES),
        army=army,
        conquer=rng.sample(border, min(len(border), rng.randint(0, 3))),
        war_on=rng.choice(neighbours) if army == "conquer" and neighbours else None,
        peace_with=rng.sample(courts, min(len(courts), rng.randint(0, 2))),
        befriend=rng.sample(courts, min(len(courts), rng.randint(0, 2))),
        research=rng.sample(list(TechBranch), len(TechBranch)),
        note="a random plan",
    )
