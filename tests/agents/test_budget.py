"""The budget: money is set aside before a call, so that no run can spend past its limit."""

import pytest

from pax_agentica.agents.budget import Budget, BudgetExceeded


def test_a_reservation_within_the_limit_is_granted() -> None:
    budget = Budget(limit_usd=1.0)

    budget.reserve(0.4)

    assert budget.committed_usd == pytest.approx(0.4)
    assert budget.spent_usd == 0


def test_a_reservation_past_the_limit_is_refused_and_leaves_no_trace() -> None:
    budget = Budget(limit_usd=1.0)
    budget.reserve(0.8)

    with pytest.raises(BudgetExceeded):
        budget.reserve(0.3)

    assert budget.committed_usd == pytest.approx(0.8)


def test_calls_in_flight_count_against_the_limit() -> None:
    """Nine crowns ask at once: each must see what the others have already set aside."""
    budget = Budget(limit_usd=1.0)
    for _ in range(4):
        budget.reserve(0.25)

    with pytest.raises(BudgetExceeded):
        budget.reserve(0.01)


def test_settling_frees_what_was_not_spent() -> None:
    budget = Budget(limit_usd=1.0)
    budget.reserve(0.9)

    budget.settle(reserved_usd=0.9, spent_usd=0.1)
    budget.reserve(0.9)

    assert budget.spent_usd == pytest.approx(0.1)
    assert budget.committed_usd == pytest.approx(1.0)


def test_a_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        Budget(limit_usd=0)
