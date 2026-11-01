"""The strategist: a ruler that decides strategy and leaves the tactics to the greedy bot.

Every second year, and at once on grave news, a model writes a `Plan` from the compact view; every
year the bot turns the current plan into orders. See specs/002-council-strategist.
"""

from dataclasses import dataclass
from typing import Protocol

from pax_agentica.engine import NationView, Orders
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.players.plan import Plan, combine
from pax_agentica.tools import compact_view

YEARS_BETWEEN_PLANS = 2


class PlanModel(Protocol):
    """Whatever writes the plans: a language model, or a fake in the tests."""

    async def write_plan(self, request: str) -> Plan: ...


@dataclass(frozen=True)
class _Realm:
    """What the strategist remembers of a year, to see what has changed by the next."""

    wars: frozenset[str]
    provinces: frozenset[str]
    monarch: tuple[str, int] | None

    @classmethod
    def of(cls, view: NationView) -> "_Realm":
        ruler = view.me.ruler
        return cls(
            wars=frozenset(view.me.at_war_with),
            provinces=frozenset(view.me.provinces),
            monarch=(ruler.name, ruler.since) if ruler else None,
        )

    def grave_news_since(self, last_year: "_Realm") -> bool:
        """A war started or ended, a province was lost, or the throne changed hands."""
        return (
            self.wars != last_year.wars
            or bool(last_year.provinces - self.provinces)
            or self.monarch != last_year.monarch
        )


class Strategist:
    """A `Player` that asks its model for a plan when one is due, and has the bot carry it out."""

    def __init__(self, model: PlanModel, seed: int = 0) -> None:
        self._model = model
        self._bot = GreedyBot(seed)
        self._note = ""
        self._last_plan_turn: int | None = None
        self._last_year: _Realm | None = None

    @property
    def name(self) -> str:
        return "strategist"

    async def decide(self, view: NationView) -> Orders:
        realm = _Realm.of(view)
        if self._plan_is_due(view, realm):
            plan = await self._model.write_plan(compact_view(view))
            self._bot.follow(plan)
            self._note = plan.note
            self._last_plan_turn = view.turn
        self._last_year = realm
        return combine(await self._bot.decide(view), Orders(thoughts=self._note))

    def _plan_is_due(self, view: NationView, realm: _Realm) -> bool:
        if self._last_plan_turn is None or self._last_year is None:
            return True
        if realm.grave_news_since(self._last_year):
            return True
        return view.turn - self._last_plan_turn >= YEARS_BETWEEN_PLANS
