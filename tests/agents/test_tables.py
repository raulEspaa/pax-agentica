"""The AI council at the public tables: who may ask for it, who pays, and what happens when the
day's money is spent."""

import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pax_agentica.agents.budget import DailyBudget
from pax_agentica.agents.diplomat import Diplomacy
from pax_agentica.agents.prompts import PlanRequest
from pax_agentica.agents.tables import TableAI
from pax_agentica.multiplayer import create_lobby_app
from pax_agentica.players.plan import Plan

PLAN = Plan(economy="grow", army="build_up", note="Grow.")


class Paid:
    """A model that charges the budget a fixed price for every plan, like the real one."""

    def __init__(self, budget: DailyBudget, price: float = 0.01) -> None:
        self.budget = budget
        self.price = price
        self.plans: list[PlanRequest] = []

    async def write_plan(self, request: PlanRequest) -> Plan:
        self.budget.reserve(self.price)
        self.budget.settle(self.price, self.price)
        self.plans.append(request)
        return PLAN

    async def write_diplomacy(self, request: PlanRequest) -> Diplomacy:
        return Diplomacy()


def server(tmp_path: Path, limit: float = 1.0) -> tuple[TestClient, Paid]:
    budget = DailyBudget(limit, tmp_path / "ai-budget.json")
    model = Paid(budget)
    return TestClient(create_lobby_app(tmp_path, invite_code="", ai=TableAI(model, budget))), model


def open_table(client: TestClient, **extra: object) -> dict[str, str]:
    body = {"name": "Anne", "nation": "france", "seed": 3, "years": 10} | extra
    return client.post("/api/tables", json=body).json()  # type: ignore[no-any-return]


def test_a_table_can_set_the_council_on_a_crown(tmp_path: Path) -> None:
    client, model = server(tmp_path)
    opened = open_table(client, ai=["england"])
    seat = {"X-Seat": opened["token"]}
    client.post(f"/api/t/{opened['table']}/turn", json={"actions": []}, headers=seat)
    game = client.get(f"/api/t/{opened['table']}/game", headers=seat).json()
    assert game["rulers"]["england"] == "council"
    assert len(model.plans) == 1  # England's council wrote its first plan
    lobby = client.get("/api/lobby").json()
    england = next(n for n in lobby["tables"][0]["nations"] if n["id"] == "england")
    assert england["ai"] is True
    assert lobby["ai"] == {"available": True, "left_usd": 0.99}


def test_the_council_comes_back_after_a_restart(tmp_path: Path) -> None:
    client, _ = server(tmp_path)
    opened = open_table(client, ai=["england"])
    again, model = server(tmp_path)  # a new revision, reading the saved table
    seat = {"X-Seat": opened["token"]}
    again.post(f"/api/t/{opened['table']}/turn", json={"actions": []}, headers=seat)
    assert len(model.plans) == 1


def test_your_own_crown_is_never_given_to_the_council(tmp_path: Path) -> None:
    client, _ = server(tmp_path)
    opened = open_table(client, ai=["france", "spain"])
    game = client.get(f"/api/t/{opened['table']}/game", headers={"X-Seat": opened["token"]})
    assert game.json()["rulers"]["spain"] == "council"
    assert game.json()["rulers"]["france"] == "Anne"


def test_a_spent_day_refuses_new_ai_tables_and_the_old_ones_play_on(tmp_path: Path) -> None:
    client, model = server(tmp_path, limit=0.015)
    opened = open_table(client, ai=["england"])
    seat = {"X-Seat": opened["token"]}
    for _ in range(4):  # the second plan does not fit: the council keeps its first, and plays
        r = client.post(f"/api/t/{opened['table']}/turn", json={"actions": []}, headers=seat)
        assert r.status_code == 200
    assert len(model.plans) == 1
    refused = client.post(
        "/api/tables", json={"name": "Pedro", "nation": "spain", "ai": ["france"]}
    )
    assert refused.status_code == 429
    assert "budget" in refused.json()["detail"]
    assert client.get("/api/lobby").json()["ai"]["available"] is False


def test_a_server_without_ai_says_so(tmp_path: Path) -> None:
    client = TestClient(create_lobby_app(tmp_path, invite_code=""))
    assert client.get("/api/lobby").json()["ai"]["available"] is False
    r = client.post("/api/tables", json={"name": "Anne", "nation": "france", "ai": ["england"]})
    assert r.status_code == 422


def test_from_env_needs_a_key_and_a_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("PAX_AI_DAILY_USD", "1")
    assert TableAI.from_env(tmp_path) is None
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    monkeypatch.delenv("PAX_AI_DAILY_USD")
    assert TableAI.from_env(tmp_path) is None


class Slow(Paid):
    """A model that takes a while, and counts how many plans it has started."""

    def __init__(self, budget: DailyBudget) -> None:
        super().__init__(budget)
        self.started = 0

    async def write_plan(self, request: PlanRequest) -> Plan:
        self.started += 1
        await asyncio.sleep(0.2)
        return await super().write_plan(request)


def test_the_council_thinks_while_the_humans_play(tmp_path: Path) -> None:
    budget = DailyBudget(1.0)
    model = Slow(budget)
    client = TestClient(create_lobby_app(tmp_path, invite_code="", ai=TableAI(model, budget)))
    with client:  # one event loop for every request, as on the server
        opened = open_table(client, ai=["england"])
        seat = {"X-Seat": opened["token"]}
        client.get(f"/api/t/{opened['table']}/status", headers=seat)  # the page looks
        deadline = time.monotonic() + 5
        while not model.started and time.monotonic() < deadline:  # it runs on the server's loop
            time.sleep(0.01)
        assert model.started == 1  # before anyone ended the year
        client.get(f"/api/t/{opened['table']}/status", headers=seat)
        assert model.started == 1  # once a year, however often the page looks
        r = client.post(f"/api/t/{opened['table']}/turn", json={"actions": []}, headers=seat)
        assert r.status_code == 200
        assert len(model.plans) == 1
