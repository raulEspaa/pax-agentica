"""What the AI council at the tables reports (spec 009): one `decisions` row per decision, its
own cost however many councils think at once, and its fallbacks."""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pax_agentica.agents import meter
from pax_agentica.agents.audience import Reply
from pax_agentica.agents.budget import Budget, DailyBudget
from pax_agentica.agents.council import Council
from pax_agentica.agents.diplomat import Diplomacy, Letter
from pax_agentica.agents.prompts import PlanRequest
from pax_agentica.agents.tables import MeteredModel, Recorded, TableAI, metered_audience
from pax_agentica.analytics import AudienceRow, DecisionRow
from pax_agentica.engine import new_game, view_for
from pax_agentica.multiplayer import create_lobby_app
from pax_agentica.players.plan import Plan

type FitsSchema = Callable[[dict[str, Any], str], None]  # the fixtures of conftest.py
type NdjsonRows = Callable[[Path, str], list[dict[str, Any]]]

PLAN = Plan(economy="grow", army="build_up", note="Grow.")


class Priced:
    """A model that takes a while and charges the shared budget a price of its own per call."""

    def __init__(self, budget: Budget, price: float, pause: float = 0.0, letters: int = 0) -> None:
        self.budget = budget
        self.price = price
        self.pause = pause
        self.letters = letters

    async def _pay(self) -> None:
        self.budget.reserve(self.price)
        try:
            await asyncio.sleep(self.pause)  # let the other council's calls settle in between
        finally:
            self.budget.settle(self.price, self.price)

    async def write_plan(self, request: PlanRequest) -> Plan:
        await self._pay()
        return PLAN

    async def write_diplomacy(self, request: PlanRequest) -> Diplomacy:
        await self._pay()
        return Diplomacy(letters=[Letter(to="spain", text="Peace.")] * self.letters)

    async def write_reply(self, request: PlanRequest) -> Reply:
        await self._pay()
        return Reply(text="Well met.")


class Hangs:
    """A model that never answers in time."""

    name = "slow-model"

    async def write_plan(self, request: PlanRequest) -> Plan:
        await asyncio.sleep(60)
        return PLAN

    async def write_diplomacy(self, request: PlanRequest) -> Diplomacy:
        await asyncio.sleep(60)
        return Diplomacy()


def recorded(model: Any, rows: list[DecisionRow], timeout: float = 5.0) -> Recorded:
    council = Council(MeteredModel(model), seed=1, timeout=timeout)
    return Recorded(council, "t1", MeteredModel(model).name, rows.append)


def test_each_decision_pays_only_for_its_own_calls_when_councils_think_at_once(
    fits_schema: FitsSchema,
) -> None:
    budget = Budget(1.0)  # one budget for both, as at the tables
    rows: list[DecisionRow] = []
    cheap = recorded(Priced(budget, 0.01, pause=0.05), rows)
    dear = recorded(Priced(budget, 0.07, pause=0.03), rows)
    state = new_game(3)

    async def both() -> None:
        await asyncio.gather(
            cheap.decide(view_for(state, "france")), dear.decide(view_for(state, "england"))
        )

    asyncio.run(both())
    costs = {r.nation: r.cost_usd for r in rows}
    assert costs == {"france": 0.01, "england": 0.07}  # a delta of the budget would give 0.08
    assert budget.spent_usd == 0.08
    for row in rows:
        assert row.model_calls == 1
        assert row.plan_asked
        assert row.plan_written
        assert not row.fallback
        assert not row.timed_out
        fits_schema(json.loads(row.model_dump_json()), "decisions")


def test_a_council_that_times_out_falls_back_and_says_so() -> None:
    rows: list[DecisionRow] = []
    council = recorded(Hangs(), rows, timeout=0.05)
    orders = asyncio.run(council.decide(view_for(new_game(3), "france")))
    assert orders.actions  # the bot played the year without a plan
    [row] = rows
    assert row.plan_asked
    assert not row.plan_written
    assert row.fallback
    assert row.timed_out
    assert row.failures
    assert all(f.startswith("plan:") for f in row.failures)
    assert row.error is None
    assert row.model == "slow-model"
    assert row.latency_s >= 0.05


def test_letters_are_counted_when_the_diplomat_writes() -> None:
    model = Priced(Budget(1.0), 0.0, letters=2)
    decision = meter.Meter()

    async def write() -> None:
        with meter.metered() as measured:
            await MeteredModel(model).write_diplomacy(PlanRequest(system="", user=""))
            decision.letters, decision.written = measured.letters, measured.written

    asyncio.run(write())
    assert decision.letters == 2
    assert decision.written == {"diplomacy"}


def test_an_audience_reply_is_measured_and_reported(fits_schema: FitsSchema) -> None:
    budget = Budget(1.0)
    rows: list[AudienceRow] = []

    async def reply() -> str:
        budget.reserve(0.002)
        budget.settle(0.002, 0.002)
        return "Well met."

    view = view_for(new_game(3), "spain")
    said = asyncio.run(
        metered_audience(reply(), table="t1", view=view, model="m", report=rows.append)
    )
    assert said == "Well met."
    [row] = rows
    assert (row.nation, row.cost_usd, row.model_calls) == ("spain", 0.002, 1)
    fits_schema(json.loads(row.model_dump_json()), "audience")


def test_a_table_writes_a_decision_row_per_ai_year_and_its_spend_on_close(
    tmp_path: Path, fits_schema: FitsSchema, ndjson_rows: NdjsonRows
) -> None:
    budget = DailyBudget(1.0)
    ai = TableAI(Priced(budget, 0.01), budget)
    client = TestClient(create_lobby_app(tmp_path, invite_code="", ai=ai))
    body = {"name": "Anne", "nation": "france", "seed": 3, "years": 10, "ai": ["england"]}
    opened = client.post("/api/tables", json=body).json()
    seat = {"X-Seat": opened["token"]}
    for _ in range(2):
        client.post(f"/api/t/{opened['table']}/turn", json={"actions": []}, headers=seat)
    client.post(f"/api/t/{opened['table']}/leave", headers=seat)
    decisions = ndjson_rows(tmp_path / "analytics", "decisions")
    # years 1 and 2, and perhaps 3: the council starts on the next year as soon as one ends
    assert [(d["nation"], d["turn"]) for d in decisions][:2] == [("england", 1), ("england", 2)]
    assert decisions[0]["cost_usd"] == 0.01  # the first plan; the second year was quiet
    for row in decisions:
        fits_schema(row, "decisions")
        assert row["table_id"] == opened["table"]
    [game] = ndjson_rows(tmp_path / "analytics", "games")
    assert game["ai_nations"] == ["england"]
    assert game["ai_cost_usd"] == pytest.approx(sum(d["cost_usd"] for d in decisions))
    england = next(s for s in game["standings"] if s["nation"] == "england")
    assert england["ruler"] == "council"


def test_a_decision_row_that_cannot_be_written_does_not_cost_the_year(tmp_path: Path) -> None:
    (tmp_path / "analytics").write_text("not a folder")
    budget = DailyBudget(1.0)
    client = TestClient(
        create_lobby_app(tmp_path, invite_code="", ai=TableAI(Priced(budget, 0.01), budget))
    )
    body = {"name": "Anne", "nation": "france", "seed": 3, "ai": ["england"]}
    opened = client.post("/api/tables", json=body).json()
    seat = {"X-Seat": opened["token"]}
    r = client.post(f"/api/t/{opened['table']}/turn", json={"actions": []}, headers=seat)
    assert r.status_code == 200
    assert client.get("/api/lobby").json()["tables"][0]["turn"] == 2  # the year was played
