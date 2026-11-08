"""The public server's budget: a limit per day that survives a restart."""

from pathlib import Path

import pytest

from pax_agentica.agents import budget as budget_module
from pax_agentica.agents.budget import BudgetExceeded, DailyBudget


@pytest.fixture
def day(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    today = ["2026-11-08"]
    monkeypatch.setattr(budget_module, "_today", lambda: today[0])
    return today


def spend(budget: DailyBudget, usd: float) -> None:
    budget.reserve(usd)
    budget.settle(usd, usd)


def test_a_day_cannot_spend_past_its_limit(day: list[str]) -> None:
    budget = DailyBudget(1.0)
    spend(budget, 0.9)
    with pytest.raises(BudgetExceeded):
        budget.reserve(0.2)
    assert budget.left_usd == pytest.approx(0.1)


def test_the_next_day_starts_again(day: list[str]) -> None:
    budget = DailyBudget(1.0)
    spend(budget, 1.0)
    day[0] = "2026-11-09"
    assert budget.left_usd == 1.0
    budget.reserve(0.5)  # no longer refused


def test_a_restart_remembers_what_the_day_spent(day: list[str], tmp_path: Path) -> None:
    path = tmp_path / "ai-budget.json"
    spend(DailyBudget(1.0, path), 0.75)
    again = DailyBudget(1.0, path)  # the server woke up again
    assert again.spent_usd == pytest.approx(0.75)
    day[0] = "2026-11-09"
    assert DailyBudget(1.0, path).spent_usd == 0.0  # yesterday's record is not today's


def test_an_unreadable_record_starts_the_day_at_zero(day: list[str], tmp_path: Path) -> None:
    path = tmp_path / "ai-budget.json"
    path.write_text("not json")
    assert DailyBudget(1.0, path).spent_usd == 0.0
