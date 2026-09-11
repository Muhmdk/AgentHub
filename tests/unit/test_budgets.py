"""Deterministic tests for rolling model budget accounting."""

from dataclasses import dataclass

import pytest

from packages.governance.budgets import (
    BudgetExceeded,
    BudgetKey,
    BudgetLimits,
    BudgetManager,
    RateLimitExceeded,
)


@dataclass
class FakeClock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


def _key(agent: str = "inventory-agent", model: str = "gpt-test") -> BudgetKey:
    return BudgetKey(
        agent_name=agent,
        agent_version="1.0.0",
        provider="azure-openai",
        model=model,
    )


@pytest.mark.unit
def test_request_limits_are_isolated_by_agent_and_model() -> None:
    manager = BudgetManager(FakeClock())
    limits = BudgetLimits(requests_per_minute=1, tokens_per_minute=100, cost_per_hour_usd=1)
    first = manager.reserve(_key(), limits, tokens=1, cost_usd=0)
    manager.complete(first, tokens=1, cost_usd=0)

    with pytest.raises(RateLimitExceeded):
        manager.reserve(_key(), limits, tokens=1, cost_usd=0)

    manager.reserve(_key(agent="knowledge-agent"), limits, tokens=1, cost_usd=0)
    manager.reserve(_key(model="gpt-other"), limits, tokens=1, cost_usd=0)


@pytest.mark.unit
def test_token_reservations_prevent_concurrent_overspend_and_release_on_failure() -> None:
    manager = BudgetManager(FakeClock())
    limits = BudgetLimits(requests_per_minute=10, tokens_per_minute=10, cost_per_hour_usd=1)
    lease = manager.reserve(_key(), limits, tokens=10, cost_usd=0)

    with pytest.raises(BudgetExceeded, match="token"):
        manager.reserve(_key(), limits, tokens=1, cost_usd=0)

    manager.release(lease)
    manager.reserve(_key(), limits, tokens=10, cost_usd=0)


@pytest.mark.unit
def test_cost_reservations_enforce_hourly_limit() -> None:
    manager = BudgetManager(FakeClock())
    limits = BudgetLimits(requests_per_minute=10, tokens_per_minute=100, cost_per_hour_usd=0.01)
    manager.reserve(_key(), limits, tokens=1, cost_usd=0.01)

    with pytest.raises(BudgetExceeded, match="cost"):
        manager.reserve(_key(), limits, tokens=1, cost_usd=0.001)


@pytest.mark.unit
def test_completion_replaces_worst_case_reservation_with_actual_usage() -> None:
    manager = BudgetManager(FakeClock())
    limits = BudgetLimits(requests_per_minute=10, tokens_per_minute=10, cost_per_hour_usd=1)
    lease = manager.reserve(_key(), limits, tokens=10, cost_usd=1)
    manager.complete(lease, tokens=2, cost_usd=0.2)

    manager.reserve(_key(), limits, tokens=8, cost_usd=0.8)


@pytest.mark.unit
def test_rolling_windows_expire_request_token_and_cost_usage() -> None:
    clock = FakeClock()
    manager = BudgetManager(clock)
    limits = BudgetLimits(requests_per_minute=1, tokens_per_minute=10, cost_per_hour_usd=1)
    lease = manager.reserve(_key(), limits, tokens=10, cost_usd=1)
    manager.complete(lease, tokens=10, cost_usd=1)

    clock.now = 60
    with pytest.raises(BudgetExceeded, match="cost"):
        manager.reserve(_key(), limits, tokens=10, cost_usd=1)

    clock.now = 3600
    manager.reserve(_key(), limits, tokens=10, cost_usd=1)


@pytest.mark.unit
def test_invalid_limits_and_usage_are_rejected() -> None:
    with pytest.raises(ValueError, match="limits"):
        BudgetLimits(requests_per_minute=0)
    manager = BudgetManager(FakeClock())
    with pytest.raises(ValueError, match="negative"):
        manager.reserve(_key(), BudgetLimits(), tokens=-1, cost_usd=0)
