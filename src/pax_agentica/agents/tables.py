"""The AI council at the public tables: anyone who opens a table may set it against a crown.

One model and one daily budget are shared by every table on the server, so the whole bill of a
day is capped however many people play. When the day's money is spent, the council's calls are
refused before they are made; the council keeps its last plan and its bot plays on, so a game is
never stopped by the budget.

    GEMINI_API_KEY=...          # the key; without it the tables have no AI
    PAX_AI_DAILY_USD=3          # the most the server spends on models in a day (UTC)
    PAX_AI_CALLS_PER_MINUTE=60  # optional: the model's pace; the default suits the free tier

Imported only by a server that has both: the image for tables without AI goes without LangGraph.
"""

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from pax_agentica.agents import meter
from pax_agentica.agents.budget import DailyBudget
from pax_agentica.agents.council import Council, CouncilModel
from pax_agentica.agents.diplomat import Diplomacy
from pax_agentica.agents.prompts import PlanRequest
from pax_agentica.analytics import AudienceRow, DecisionRow, timestamp
from pax_agentica.engine import NationId, NationView, Orders
from pax_agentica.players import Player
from pax_agentica.players.plan import Plan

log = logging.getLogger(__name__)

BUDGET_FILE = "ai-budget.json"  # beside the tables' saves, so a restart remembers the day
TIMEOUT_SECONDS = 50.0  # per try: thinking ahead hides it, and the model's latency varies a lot


class ThinksAhead:
    """A ruler that starts deciding when the year begins, not when the humans end it.

    Its orders depend only on its view, and the view is fixed from the start of the year, so it
    can think while the humans play: a model that takes half a minute is not waited for."""

    def __init__(self, ruler: Player) -> None:
        self.ruler = ruler
        self._turn: int | None = None
        self._thinking: asyncio.Task[Orders] | None = None

    @property
    def name(self) -> str:
        return self.ruler.name

    def thinking_on(self) -> int | None:
        """The year it is thinking about, if any."""
        return self._turn

    def think(self, view: NationView) -> asyncio.Task[Orders]:
        """Start on this year's orders, if not started yet. Needs a running event loop."""
        if self._thinking is None or self._turn != view.turn:
            self._turn = view.turn
            self._thinking = asyncio.get_running_loop().create_task(self.ruler.decide(view))
        return self._thinking

    async def decide(self, view: NationView) -> Orders:
        return await self.think(view)


class MeteredModel:
    """The council's model, telling the decision's meter what was asked and what came back."""

    def __init__(self, model: CouncilModel) -> None:
        self.model = model

    @property
    def name(self) -> str:
        return str(getattr(self.model, "name", type(self.model).__name__))

    async def write_plan(self, request: PlanRequest) -> Plan:
        return await self._ask("plan", self.model.write_plan(request))

    async def write_diplomacy(self, request: PlanRequest) -> Diplomacy:
        answer = await self._ask("diplomacy", self.model.write_diplomacy(request))
        if (decision := meter.current()) is not None:
            decision.letters += len(answer.letters)
        return answer

    async def _ask[T](self, kind: str, call: Awaitable[T]) -> T:
        decision = meter.current()
        if decision is not None:
            decision.asked.add(kind)
        try:
            answer = await call
        except BaseException as exc:  # a node's timeout cancels the call: it is a failure too
            if decision is not None:
                decision.failures.append(f"{kind}:{type(exc).__name__}")
            raise
        if decision is not None:
            decision.written.add(kind)
        return answer


class Recorded:
    """A ruler whose every decision is measured: its cost, latency, and what fell back.

    The meter is opened inside `decide`, which `ThinksAhead` runs as a task of its own, so
    councils thinking at once at different tables never share one."""

    def __init__(
        self,
        ruler: Player,
        table: str,
        model: str,
        report: Callable[[DecisionRow], None],
        source: str = "tables",
    ) -> None:
        self.ruler = ruler
        self.table = table
        self.model = model
        self.report = report
        self.source = source

    @property
    def name(self) -> str:
        return self.ruler.name

    async def decide(self, view: NationView) -> Orders:
        started = time.monotonic()
        error: str | None = None
        with meter.metered() as measured:
            try:
                return await self.ruler.decide(view)
            except BaseException as exc:
                error = type(exc).__name__
                raise
            finally:
                self._report(view, measured, time.monotonic() - started, error)

    def _report(self, view: NationView, m: meter.Meter, seconds: float, error: str | None) -> None:
        try:
            self.report(
                DecisionRow(
                    at=timestamp(),
                    source=self.source,
                    table_id=self.table,
                    nation=view.me.id,
                    turn=view.turn,
                    year=view.year,
                    model=self.model,
                    cost_usd=round(m.cost_usd, 8),
                    model_calls=m.calls,
                    latency_s=round(seconds, 3),
                    plan_asked="plan" in m.asked,
                    plan_written="plan" in m.written,
                    diplomacy_asked="diplomacy" in m.asked,
                    diplomacy_written="diplomacy" in m.written,
                    letters=m.letters,
                    failures=m.failures,
                    timed_out=m.timed_out,
                    fallback=m.fallback,
                    error=error,
                )
            )
        except Exception:  # analytics never costs a crown its year
            log.exception("analytics: could not report a decision")


async def audience[T](
    reply: Awaitable[T],
    *,
    table: str,
    view: NationView,
    model: str,
    report: Callable[[AudienceRow], None],
    source: str = "tables",
) -> T:
    """Await one AI reply in a chat with a human, and report its `audience` row: what its calls
    cost and how long it took. Pass the coroutine itself, not a task already started, so that
    its calls run inside this meter."""
    started = time.monotonic()
    error: str | None = None
    with meter.metered() as measured:
        try:
            return await reply
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            try:
                report(
                    AudienceRow(
                        at=timestamp(),
                        source=source,
                        table_id=table,
                        nation=view.me.id,
                        turn=view.turn,
                        year=view.year,
                        model=model,
                        cost_usd=round(measured.cost_usd, 8),
                        model_calls=measured.calls,
                        latency_s=round(time.monotonic() - started, 3),
                        error=error,
                    )
                )
            except Exception:
                log.exception("analytics: could not report an audience")


class TableAI:
    """Makes a council for any crown at any table, all spending from one budget."""

    def __init__(self, model: CouncilModel, budget: DailyBudget) -> None:
        self.model = MeteredModel(model)
        self.budget = budget

    @classmethod
    def from_env(cls, saves: Path) -> "TableAI | None":
        """The council with Gemini, if this server has a key and a daily limit; else None."""
        limit = os.environ.get("PAX_AI_DAILY_USD", "")
        if not os.environ.get("GEMINI_API_KEY") or not limit:
            return None
        from pax_agentica.agents import gemini  # the SDK only on a server that uses it

        saves.mkdir(parents=True, exist_ok=True)
        budget = DailyBudget(float(limit), saves / BUDGET_FILE)
        pace = int(os.environ.get("PAX_AI_CALLS_PER_MINUTE", gemini.CALLS_PER_MINUTE))
        return cls(gemini.GeminiModel(gemini.new_client(), budget, calls_per_minute=pace), budget)

    def ruler(
        self,
        seed: int,
        table: str,
        nation: NationId,
        on_decision: Callable[[DecisionRow], None] | None = None,
    ) -> Player:
        """A council of its own for this crown at this table (its memory is its thread); each of
        its decisions is reported to `on_decision`, if given."""
        council: Player = Council(self.model, seed, TIMEOUT_SECONDS, thread=f"{table}:{nation}")
        if on_decision is not None:
            council = Recorded(council, table, self.model.name, on_decision)
        return ThinksAhead(council)

    def status(self) -> dict[str, float | bool]:
        left = self.budget.left_usd
        return {"available": left >= 0.01, "left_usd": round(left, 2)}
