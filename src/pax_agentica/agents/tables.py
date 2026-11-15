"""The AI council at the public tables: anyone who opens a table may set it against a crown.

One model and one daily budget are shared by every table on the server, so the whole bill of a
day is capped however many people play. When the day's money is spent, the council's calls are
refused before they are made; the council keeps its last plan and its bot plays on, so a game is
never stopped by the budget.

    GEMINI_API_KEY=...          # the key; without it the tables have no AI
    PAX_AI_DAILY_USD=3          # the most the server spends on models in a day (UTC)
    PAX_AI_CALLS_PER_MINUTE=60  # optional: the model's pace; the default suits the free tier
    PAX_AI_TEXTS_PER_MINUTE=50  # optional: the embedder's pace (the free tier allows 100)

Each council keeps a memory of the courts (spec 008), embedded with `gemini-embedding-001` on
the same budget and kept in `memory/<table>.<nation>.json` beside the saves. A seated player may
also ask an AI crown for an audience: `audience` answers in the monarch's voice, in words only.

Imported only by a server that has both: the image for tables without AI goes without LangGraph.
"""

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Protocol

from pax_agentica.agents import audience, meter
from pax_agentica.agents.audience import Reply, Said
from pax_agentica.agents.budget import DailyBudget
from pax_agentica.agents.council import Council, CouncilModel
from pax_agentica.agents.diplomat import Diplomacy
from pax_agentica.agents.embeddings import Embedder
from pax_agentica.agents.memory import Chronicle, Embeddings
from pax_agentica.agents.prompts import PlanRequest
from pax_agentica.analytics import AudienceRow, DecisionRow, timestamp
from pax_agentica.engine import NationId, NationView, Orders
from pax_agentica.players import Player
from pax_agentica.players.plan import Plan

log = logging.getLogger(__name__)

BUDGET_FILE = "ai-budget.json"  # beside the tables' saves, so a restart remembers the day
MEMORY_DIR = "memory"  # beside the tables' saves: one file per AI crown and table
MEMORY_DIMENSIONS = 256  # a crown's memory is small: a quarter of the archive's, and its files
TIMEOUT_SECONDS = 50.0  # per try: thinking ahead hides it, and the model's latency varies a lot
AUDIENCE_TIMEOUT_SECONDS = 30.0  # a player is waiting for this one: past it, the court is silent


class TableModel(CouncilModel, Protocol):
    """The council's model, which at the tables also answers audiences."""

    async def write_reply(self, request: PlanRequest) -> Reply: ...


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

    def __init__(self, model: "TableModel") -> None:
        self.model = model

    @property
    def name(self) -> str:
        return str(getattr(self.model, "name", type(self.model).__name__))

    async def write_reply(self, request: PlanRequest) -> Reply:
        return await self._ask("reply", self.model.write_reply(request))

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


async def metered_audience[T](
    reply: Awaitable[T],
    *,
    table: str,
    view: NationView,
    model: str,
    report: Callable[[AudienceRow], object],
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

    def __init__(
        self,
        model: TableModel,
        budget: DailyBudget,
        embedder: Embedder | None = None,
        saves: Path | None = None,
    ) -> None:
        self.model = MeteredModel(model)
        self.budget = budget
        self.embeddings = Embeddings(embedder) if embedder is not None else None
        self.saves = saves  # where the memories are kept; None keeps them in memory only

    @classmethod
    def from_env(cls, saves: Path) -> "TableAI | None":
        """The council with Gemini, if this server has a key and a daily limit; else None."""
        limit = os.environ.get("PAX_AI_DAILY_USD", "")
        if not os.environ.get("GEMINI_API_KEY") or not limit:
            return None
        from pax_agentica.agents import gemini  # the SDK only on a server that uses it

        saves.mkdir(parents=True, exist_ok=True)
        budget = DailyBudget(float(limit), saves / BUDGET_FILE)
        from pax_agentica.agents import embeddings

        pace = int(os.environ.get("PAX_AI_CALLS_PER_MINUTE", gemini.CALLS_PER_MINUTE))
        texts = int(os.environ.get("PAX_AI_TEXTS_PER_MINUTE", embeddings.TEXTS_PER_MINUTE))
        client = gemini.new_client()
        embedder = embeddings.GeminiEmbedder(
            client, budget, dimensions=MEMORY_DIMENSIONS, texts_per_minute=texts
        )
        model = gemini.GeminiModel(client, budget, calls_per_minute=pace)
        return cls(model, budget, embedder, saves)

    def memory_path(self, table: str, nation: NationId) -> Path | None:
        return self.saves / MEMORY_DIR / f"{table}.{nation}.json" if self.saves else None

    def ruler(
        self,
        seed: int,
        table: str,
        nation: NationId,
        on_decision: Callable[[DecisionRow], None] | None = None,
    ) -> Player:
        """A council of its own for this crown at this table (its plans are its thread), with its
        memory of the courts read back from its file; each of its decisions is reported to
        `on_decision`, if given."""
        memory = Chronicle(self.embeddings, self.memory_path(table, nation))
        council = Council(
            self.model, seed, TIMEOUT_SECONDS, thread=f"{table}:{nation}", memory=memory
        )
        if on_decision is not None:
            return ThinksAhead(Recorded(council, table, self.model.name, on_decision))
        return ThinksAhead(council)

    def forget(self, table: str) -> None:
        """Delete the memories of a table that is gone."""
        if self.saves is not None:
            for path in (self.saves / MEMORY_DIR).glob(f"{table}.*.json"):
                path.unlink(missing_ok=True)

    async def audience(
        self, ruler: Player, view: NationView, guest: NationId, envoy: str, said: Sequence[Said]
    ) -> Reply:
        """The answer of the crown whose `view` this is, ruled by `ruler`, to the envoy of `guest`
        (a player called `envoy`) at the end of `said`. Raises `BudgetExceeded` when the day's
        money is spent, `TimeoutError` past the timeout, and whatever the model raises."""
        council = ruler.ruler if isinstance(ruler, ThinksAhead) else ruler
        council = council.ruler if isinstance(council, Recorded) else council
        if not isinstance(council, Council):
            raise TypeError("only the AI council gives audiences")
        plan = await council.plan_in_force(view)
        memory = council.memory
        last = said[-1].text if said else ""
        remembered = []
        if memory is not None:
            question = f"{guest}: promises, treaties, betrayals and wars. {last}"
            found = await memory.recall(guest, question)
            remembered = [e.text for e in sorted(found, key=lambda e: e.turn)]  # oldest first
        request = audience.build_request(view, plan, guest, envoy, said, remembered)
        async with asyncio.timeout(AUDIENCE_TIMEOUT_SECONDS):
            reply = await self.model.write_reply(request)
        if memory is not None:
            await memory.remember_audience(view, guest, envoy, last, reply.text)
        return reply

    def status(self) -> dict[str, float | bool]:
        left = self.budget.left_usd
        return {"available": left >= 0.01, "left_usd": round(left, 2)}
