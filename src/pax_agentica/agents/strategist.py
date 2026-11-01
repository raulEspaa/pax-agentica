"""The strategist: a ruler that decides strategy and leaves the tactics to the greedy bot.

Every second year a model writes a `Plan` from the compact view; every year the bot turns the
current plan into orders. See specs/002-council-strategist.
"""

from typing import Protocol

from pax_agentica.engine import NationView, Orders
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.players.plan import Plan, combine
from pax_agentica.tools import compact_view

YEARS_BETWEEN_PLANS = 2


class PlanModel(Protocol):
    """Whatever writes the plans: a language model, or a fake in the tests."""

    async def write_plan(self, request: str) -> Plan: ...


class Strategist:
    """A `Player` that asks its model for a plan when one is due, and has the bot carry it out."""

    def __init__(self, model: PlanModel, seed: int = 0) -> None:
        self._model = model
        self._bot = GreedyBot(seed)
        self._note = ""
        self._last_plan_turn: int | None = None

    @property
    def name(self) -> str:
        return "strategist"

    async def decide(self, view: NationView) -> Orders:
        if self._plan_is_due(view):
            plan = await self._model.write_plan(compact_view(view))
            self._bot.follow(plan)
            self._note = plan.note
            self._last_plan_turn = view.turn
        return combine(await self._bot.decide(view), Orders(thoughts=self._note))

    def _plan_is_due(self, view: NationView) -> bool:
        if self._last_plan_turn is None:
            return True
        return view.turn - self._last_plan_turn >= YEARS_BETWEEN_PLANS
