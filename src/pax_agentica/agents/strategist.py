"""The strategist: a ruler that decides strategy and leaves the tactics to the greedy bot.

Every second year, and at once on grave news, a model writes a `Plan` (see prompts.py); every
year the bot turns the current plan into orders. See specs/002-council-strategist.
"""

import asyncio
from dataclasses import dataclass
from typing import Protocol

from pax_agentica.agents.checks import clean_plan
from pax_agentica.agents.prompts import PlanRequest, build_request
from pax_agentica.engine import NationView, Orders
from pax_agentica.engine.actions import MAX_THOUGHTS_CHARS
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.players.plan import Plan

YEARS_BETWEEN_PLANS = 2
MODEL_TIMEOUT_SECONDS = 30.0
MAX_FAILURE_CHARS = 300  # an error can be long, and the thoughts have a limit


def _why(exc: Exception) -> str:
    """An error on one line, with its type: a `ValidationError` says nothing of its type."""
    return f"{type(exc).__name__} {' '.join(str(exc).split())}"


class PlanModel(Protocol):
    """Whatever writes the plans: a language model, or a fake in the tests."""

    async def write_plan(self, request: PlanRequest) -> Plan: ...


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

    def __init__(
        self, model: PlanModel, seed: int = 0, timeout: float = MODEL_TIMEOUT_SECONDS
    ) -> None:
        self._model = model
        self._timeout = timeout
        self._bot = GreedyBot(seed)
        self._plan: Plan | None = None
        self._last_plan_turn: int | None = None
        self._last_year: _Realm | None = None

    @property
    def name(self) -> str:
        return "strategist"

    async def decide(self, view: NationView) -> Orders:
        realm = _Realm.of(view)
        remark = await self._new_plan(view) if self._plan_is_due(view, realm) else ""
        self._last_year = realm
        orders = await self._bot.decide(view)  # its thoughts open with "The plan:" and the note
        thoughts = "\n".join(line for line in (orders.thoughts, remark) if line)
        return orders.model_copy(update={"thoughts": thoughts[:MAX_THOUGHTS_CHARS]})

    async def _new_plan(self, view: NationView) -> str:
        """Ask for a plan and follow it. Returns what the thoughts should say about it, if anything.

        After a failure `_last_plan_turn` stays as it was, so the plan is due again next year."""
        request = build_request(view, self._plan)
        try:
            answer, first_failure = await self._ask(request)
        except Exception as exc:  # whatever went wrong, a model never costs the nation its year
            outcome = "the last plan stands" if self._plan else "the ministers rule without one"
            return f"No new plan this year, {outcome}: {_why(exc)}"[:MAX_FAILURE_CHARS]
        self._plan, dropped = clean_plan(answer, view)
        self._bot.follow(self._plan)
        self._last_plan_turn = view.turn
        lines = (
            [f"The first try failed: {first_failure}"[:MAX_FAILURE_CHARS]] if first_failure else []
        )
        if dropped:
            lines.append(f"Dropped from the plan: {', '.join(dropped)}.")
        return "\n".join(lines)

    async def _ask(self, request: PlanRequest) -> tuple[Plan, str]:
        """One attempt and one retry: the plan, and why the first attempt failed if it did.

        If the retry fails too, its error is the one that is raised."""
        try:
            return await self._attempt(request), ""
        except Exception as exc:
            first_failure = _why(exc)
        return await self._attempt(request), first_failure

    async def _attempt(self, request: PlanRequest) -> Plan:
        async with asyncio.timeout(self._timeout):
            return await self._model.write_plan(request)

    def _plan_is_due(self, view: NationView, realm: _Realm) -> bool:
        if self._last_plan_turn is None or self._last_year is None:
            return True
        if realm.grave_news_since(self._last_year):
            return True
        return view.turn - self._last_plan_turn >= YEARS_BETWEEN_PLANS
