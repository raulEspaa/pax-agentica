"""The council: the strategist and a diplomat as a LangGraph graph, the ministers carrying out.

    START ─> assess ─┬─ a plan is due ─> strategist ─┬─ letters ─> diplomat ─> ministers ─> END
                     │                               └─ none ───────────────────┘
                     ├─ letters ─────────────────────────────> diplomat
                     └─ neither ─────────────────────────────────────────────> ministers

The same decisions as `Strategist` (spec 002), written as a graph:

- **State** is what the council remembers from year to year: the plan, when it was written, and
  what the realm looked like. A checkpointer keeps it per nation (`thread_id`), so it is not held
  in the object, and a Postgres checkpointer could keep it across a crash.
- **Context** is this year's view: read by every node, never stored in a checkpoint.
- **Conditional edges** decide what is asked of whom, so a quiet year costs nothing.
- **Retry, timeout and fallback** are settings on the nodes (`retry_policy`, `timeout`,
  `error_handler`) instead of the try/except of `Strategist._ask`.

The greedy bot keeps its own memory of the game, so it lives in the `Council`, not in the state.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import NodeError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, RetryPolicy

from pax_agentica.agents import diplomat, prompts
from pax_agentica.agents.budget import BudgetExceeded
from pax_agentica.agents.checks import clean_plan
from pax_agentica.agents.diplomat import Diplomacy
from pax_agentica.agents.prompts import PlanRequest
from pax_agentica.agents.strategist import (
    MAX_FAILURE_CHARS,
    MODEL_TIMEOUT_SECONDS,
    YEARS_BETWEEN_PLANS,
    _Realm,
    _why,
)
from pax_agentica.agents.tracing import Tracer
from pax_agentica.engine import NationView, Orders
from pax_agentica.engine.actions import MAX_THOUGHTS_CHARS
from pax_agentica.players.greedy_bot import GreedyBot
from pax_agentica.players.plan import Plan, combine
from pax_agentica.tools import inbox


class CouncilModel(Protocol):
    """Whatever writes the plans and the letters: a language model, or a fake in the tests."""

    async def write_plan(self, request: PlanRequest) -> Plan: ...

    async def write_diplomacy(self, request: PlanRequest) -> Diplomacy: ...


class Memory(TypedDict, total=False):
    """The graph's state. Plain data only, so that any checkpointer can store it."""

    plan: dict[str, Any] | None  # the plan in force
    plan_turn: int | None  # the year it was written
    realm: dict[str, Any] | None  # wars, provinces and monarch last year, to spot grave news
    why: str  # why a plan is due this year, or "" if it is not
    remarks: list[str]  # what this year's thoughts should say about the council
    envoy: dict[str, Any] | None  # this year's orders from the diplomat
    orders: dict[str, Any]  # this year's orders, the bot's and the envoy's


@dataclass(frozen=True)
class Year:
    """The graph's context: what every node may read this year, and never stored."""

    view: NationView


type Next = Literal["strategist", "diplomat", "ministers"]


def _realm_data(realm: _Realm) -> dict[str, Any]:
    return {
        "wars": sorted(realm.wars),
        "provinces": sorted(realm.provinces),
        "monarch": list(realm.monarch) if realm.monarch else None,
    }


def _realm_from(data: dict[str, Any]) -> _Realm:
    monarch = data["monarch"]
    return _Realm(
        wars=frozenset(data["wars"]),
        provinces=frozenset(data["provinces"]),
        monarch=(monarch[0], monarch[1]) if monarch else None,
    )


def _no_retry_when_broke(exc: Exception) -> bool:
    """Retry any failure but a spent budget, which a second try cannot mend."""
    return not isinstance(exc, BudgetExceeded)


class Council:
    """A `Player` whose decisions run through a LangGraph graph. One per nation and game."""

    def __init__(
        self,
        model: CouncilModel,
        seed: int = 0,
        timeout: float = MODEL_TIMEOUT_SECONDS,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        tracer: Tracer | None = None,
        thread: str = "",
    ) -> None:
        self._model = model
        self._bot = GreedyBot(seed)
        self._graph = self._build(timeout, checkpointer or InMemorySaver())
        self._tracer = tracer or Tracer()
        self._thread = thread

    @property
    def name(self) -> str:
        return "council"

    @property
    def graph(self) -> CompiledStateGraph[Memory, Year, Memory, Memory]:
        return self._graph

    async def decide(self, view: NationView) -> Orders:
        year: Memory = {"why": "", "remarks": [], "envoy": None}
        with self._tracer.council(view) as traced:
            config: Any = {
                "configurable": {"thread_id": self._thread or view.me.id},
                "run_name": "graph",
                **traced,
            }
            state = await self._graph.ainvoke(year, config, context=Year(view))
        return Orders.model_validate(state["orders"])

    # ------------------------------------------------------------ the graph

    def _build(
        self, timeout: float, checkpointer: BaseCheckpointSaver[Any]
    ) -> CompiledStateGraph[Memory, Year, Memory, Memory]:
        retry = RetryPolicy(max_attempts=2, initial_interval=1.0, retry_on=_no_retry_when_broke)
        graph = StateGraph(Memory, context_schema=Year)
        graph.add_node("assess", self._assess)
        graph.add_node(
            "strategist",
            self._strategist,
            retry_policy=retry,
            timeout=timeout,
            error_handler=self._without_a_new_plan,
        )
        graph.add_node(
            "diplomat",
            self._diplomat,
            retry_policy=retry,
            timeout=timeout,
            error_handler=self._without_letters,
        )
        graph.add_node("ministers", self._ministers)
        graph.add_edge(START, "assess")
        graph.add_conditional_edges("assess", self._after_assess)
        graph.add_conditional_edges("strategist", self._to_the_desk)
        graph.add_edge("diplomat", "ministers")
        graph.add_edge("ministers", END)
        return graph.compile(checkpointer=checkpointer)

    def _assess(self, state: Memory, *, runtime: Runtime[Year]) -> Memory:
        """Why a new plan is due this year, if it is: the same rule as the strategist's."""
        view = runtime.context.view
        realm = _Realm.of(view)
        last, turn = state.get("realm"), state.get("plan_turn")
        if turn is None or last is None:
            why = "no plan yet"
        elif realm.grave_news_since(_realm_from(last)):
            why = "grave news"
        elif view.turn - turn >= YEARS_BETWEEN_PLANS:
            why = f"{YEARS_BETWEEN_PLANS} years since the last plan"
        else:
            why = ""
        return {"why": why, "realm": _realm_data(realm)}

    def _after_assess(self, state: Memory, *, runtime: Runtime[Year]) -> Next:
        return "strategist" if state["why"] else self._to_the_desk(state, runtime=runtime)

    def _to_the_desk(self, state: Memory, *, runtime: Runtime[Year]) -> Next:
        """The diplomat only in a year when someone wrote or proposed something."""
        return "diplomat" if inbox(runtime.context.view) else "ministers"

    async def _strategist(self, state: Memory, *, runtime: Runtime[Year]) -> Memory:
        view = runtime.context.view
        last = Plan.model_validate(state["plan"]) if state.get("plan") else None
        answer = await self._model.write_plan(prompts.build_request(view, last))
        plan, dropped = clean_plan(answer, view)
        remarks = [f"Dropped from the plan: {', '.join(dropped)}."] if dropped else []
        return {"plan": plan.model_dump(mode="json"), "plan_turn": view.turn, "remarks": remarks}

    def _without_a_new_plan(
        self, state: Memory, error: NodeError, *, runtime: Runtime[Year]
    ) -> Command[Next]:
        """Both tries failed: the last plan stands, and the year goes on."""
        outcome = "the last plan stands" if state.get("plan") else "the ministers rule without one"
        line = f"No new plan this year, {outcome}: {_why(_failure(error))}"[:MAX_FAILURE_CHARS]
        return Command(update={"remarks": [line]}, goto=self._to_the_desk(state, runtime=runtime))

    async def _diplomat(self, state: Memory, *, runtime: Runtime[Year]) -> Memory:
        view = runtime.context.view
        plan = Plan.model_validate(state["plan"]) if state.get("plan") else None
        request = diplomat.build_request(view, plan)
        if request is None:
            return {}
        orders, dropped = diplomat.to_orders(await self._model.write_diplomacy(request), view)
        remarks = [f"The envoy could not: {', '.join(dropped)}."] if dropped else []
        return {
            "envoy": orders.model_dump(mode="json"),
            "remarks": [*state.get("remarks", []), *remarks],
        }

    def _without_letters(self, state: Memory, error: NodeError) -> Command[Next]:
        line = f"The envoy wrote nothing this year: {_why(_failure(error))}"[:MAX_FAILURE_CHARS]
        remarks = [*state.get("remarks", []), line]
        return Command(update={"remarks": remarks}, goto="ministers")

    async def _ministers(self, state: Memory, *, runtime: Runtime[Year]) -> Memory:
        """The bot follows a plan written this year, and gives the year's orders. The envoy's
        orders go over the bot's; the thoughts say the plan, then the envoy, then the council."""
        view = runtime.context.view
        if state.get("plan_turn") == view.turn and state.get("plan"):
            self._bot.follow(Plan.model_validate(state["plan"]))
        bots = await self._bot.decide(view)
        envoy = Orders.model_validate(state["envoy"]) if state.get("envoy") else Orders()
        orders = combine(bots, envoy.model_copy(update={"thoughts": ""}))
        lines = [bots.thoughts, envoy.thoughts, *state.get("remarks", [])]
        thoughts = "\n".join(line for line in lines if line)[:MAX_THOUGHTS_CHARS]
        return {"orders": orders.model_copy(update={"thoughts": thoughts}).model_dump(mode="json")}


def _failure(error: NodeError) -> Exception:
    """What made the node fail: an `Exception`, since a cancellation is never handled here."""
    cause = error.error
    return cause if isinstance(cause, Exception) else RuntimeError(repr(cause))
