"""Automatic rollback policy table coverage."""

from datetime import UTC, datetime, timedelta

import pytest

from packages.contracts.incident import RollbackPolicy, RollbackPolicyInput
from packages.incidents.policy import RollbackPolicyEvaluator

NOW = datetime(2026, 9, 11, 6, 0, tzinfo=UTC)


def _inputs(**updates: object) -> RollbackPolicyInput:
    values: dict[str, object] = {
        "canary_active": True,
        "guardrail_breached": True,
        "evidence_count": 3,
        "concurrent_rollout": False,
        "ambiguous_cause": False,
        "includes_data_migration": False,
        "high_risk": False,
        "human_approved": False,
        "previous_attempts": 0,
        "last_attempt_at": None,
        "evaluated_at": NOW,
    }
    values.update(updates)
    return RollbackPolicyInput.model_validate(values)


@pytest.mark.unit
def test_eligible_canary_guardrail_breach_is_automatic() -> None:
    decision = RollbackPolicyEvaluator.evaluate(_inputs(), RollbackPolicy())

    assert decision.allowed is True
    assert decision.automatic is True
    assert decision.requires_approval is False
    assert all(check.passed for check in decision.checks)


@pytest.mark.unit
@pytest.mark.parametrize(
    "updates",
    [
        {"canary_active": False},
        {"guardrail_breached": False},
        {"ambiguous_cause": True},
        {"includes_data_migration": True},
        {"high_risk": True},
    ],
)
def test_ambiguous_stable_or_high_risk_rollback_requires_human_approval(
    updates: dict[str, object],
) -> None:
    blocked = RollbackPolicyEvaluator.evaluate(_inputs(**updates), RollbackPolicy())
    approved = RollbackPolicyEvaluator.evaluate(
        _inputs(**updates, human_approved=True), RollbackPolicy()
    )

    assert blocked.allowed is False
    assert blocked.requires_approval is True
    assert approved.allowed is True
    assert approved.automatic is False
    assert approved.requires_approval is True


@pytest.mark.unit
@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"evidence_count": 2}, "insufficient"),
        ({"concurrent_rollout": True}, "Another rollout"),
        ({"previous_attempts": 3}, "attempt limit"),
        (
            {"last_attempt_at": NOW - timedelta(seconds=899)},
            "cooldown is active",
        ),
    ],
)
def test_common_safety_limits_cannot_be_overridden_by_approval(
    updates: dict[str, object], reason: str
) -> None:
    decision = RollbackPolicyEvaluator.evaluate(
        _inputs(**updates, human_approved=True), RollbackPolicy()
    )

    assert decision.allowed is False
    assert any(reason in item for item in decision.reasons)


@pytest.mark.unit
def test_exact_cooldown_and_attempt_boundaries_are_allowed() -> None:
    decision = RollbackPolicyEvaluator.evaluate(
        _inputs(
            previous_attempts=2,
            last_attempt_at=NOW - timedelta(seconds=900),
        ),
        RollbackPolicy(),
    )

    assert decision.allowed is True


@pytest.mark.unit
def test_policy_rejects_naive_evaluation_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        RollbackPolicyEvaluator.evaluate(
            _inputs(evaluated_at=datetime(2026, 9, 11, 6, 0)), RollbackPolicy()
        )
