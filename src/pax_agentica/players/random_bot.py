"""A ruler with no plan at all: the baseline every other player should beat."""

import random

from pax_agentica.engine import NationView, Orders
from pax_agentica.engine.actions import (
    MAX_ACTIONS_PER_TURN,
    Action,
    Attack,
    DeclareWar,
    Move,
    ProposePeace,
    Recruit,
    Respond,
)


class RandomBot:
    def __init__(self, seed: int = 0) -> None:
        self.seed = seed

    @property
    def name(self) -> str:
        return "random"

    async def decide(self, view: NationView) -> Orders:
        return self.plan(view)

    def plan(self, view: NationView) -> Orders:
        rng = random.Random(f"{self.seed}:{view.me.id}:{view.turn}")  # noqa: S311
        me = view.me
        mine = [p for p in view.provinces if p.owner == me.id]
        enemies = set(me.at_war_with)
        actions: list[Action] = [
            Respond(proposal_id=p.id, accept=rng.random() < 0.5) for p in view.proposals_to_answer
        ]

        cost = view.rules.recruit_cost
        if mine and me.resources.covers(cost):
            actions.append(Recruit(province=rng.choice(mine).id, regiments=1))

        for province in mine:
            troops = province.troops or 0
            if troops < 2:
                continue
            target_id = rng.choice(province.neighbors + province.sea_neighbors)
            target = next(p for p in view.provinces if p.id == target_id)
            regiments = rng.randint(1, troops - 1)
            if target.owner == me.id:
                actions.append(Move(origin=province.id, target=target.id, regiments=regiments))
            elif target.owner is None or target.owner in enemies:
                actions.append(Attack(origin=province.id, target=target.id, regiments=regiments))

        others = [n.id for n in view.nations if n.alive]
        if others and rng.random() < 0.05:
            actions.append(DeclareWar(target=rng.choice(others)))
        for enemy in enemies:
            if rng.random() < 0.2:
                actions.append(ProposePeace(target=enemy))
        return Orders(actions=actions[:MAX_ACTIONS_PER_TURN])
