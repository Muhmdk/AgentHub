"""Promotion guardrails for samples, windows, telemetry, and regressions."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from packages.contracts.delivery import (
    CanaryGateDecision,
    CanaryGuardrailPolicy,
    MetricDelta,
    ShadowComparison,
)
from packages.delivery.guardrails import CanaryGuardrailEvaluator

NOW = datetime(2026, 9, 10, 18, tzinfo=UTC)


def _metric(
    delta: float,
    *,
    low: float | None = None,
    high: float | None = None,
    unit: str = "score",
    lower_is_better: bool = False,
    samples: int = 100,
) -> MetricDelta:
    return MetricDelta(
        samples=samples,
        stable_mean=0.5,
        candidate_mean=0.5 + delta,
        delta=delta,
        confidence_low=delta if low is None else low,
        confidence_high=delta if high is None else high,
        unit=unit,
        lower_is_better=lower_is_better,
    )


def _comparison(**updates: object) -> ShadowComparison:
    comparison = ShadowComparison(
        route_id=UUID(int=1),
        route_revisions=[1, 2],
        stable_release_id=UUID(int=2),
        candidate_release_id=UUID(int=3),
        sample_count=100,
        successful_sample_count=98,
        window_start=NOW - timedelta(minutes=10),
        window_end=NOW - timedelta(seconds=30),
        quality=_metric(0.02, low=0.005),
        safety=_metric(0.01, low=0.001),
        latency=_metric(
            20,
            high=40,
            unit="milliseconds",
            lower_is_better=True,
        ),
        error_rate=_metric(0, high=0.005, unit="rate", lower_is_better=True),
        cost=_metric(0.001, high=0.002, unit="usd", lower_is_better=True),
    )
    return comparison.model_copy(update=updates)


def _decision(
    comparison: ShadowComparison | None,
    *,
    healthy: bool = True,
) -> CanaryGateDecision:
    return CanaryGuardrailEvaluator.evaluate(
        comparison,
        CanaryGuardrailPolicy(),
        evaluated_at=NOW,
        telemetry_healthy=healthy,
    )


def test_healthy_fresh_comparison_allows_promotion_with_explainable_checks() -> None:
    decision = _decision(_comparison())

    assert decision.allowed is True
    assert decision.reasons == []
    assert len(decision.checks) == 11
    assert all(check.passed for check in decision.checks)


def test_missing_unhealthy_stale_or_future_telemetry_blocks_promotion() -> None:
    missing = _decision(None)
    unhealthy = _decision(_comparison(), healthy=False)
    stale = _decision(_comparison(window_end=NOW - timedelta(minutes=3)))
    future = _decision(_comparison(window_end=NOW + timedelta(seconds=1)))

    assert missing.allowed is False
    assert "Paired telemetry is missing" in missing.reasons
    assert unhealthy.allowed is False
    assert "Telemetry pipeline is unhealthy" in unhealthy.reasons
    assert stale.allowed is False
    assert "Telemetry is stale or dated in the future" in stale.reasons
    assert future.allowed is False
    assert "Telemetry is stale or dated in the future" in future.reasons


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"sample_count": 99}, "Paired sample count is too low"),
        ({"successful_sample_count": 94}, "Successful candidate sample count is too low"),
        (
            {"window_start": NOW - timedelta(minutes=4)},
            "Observation window is too short",
        ),
        (
            {"quality": _metric(-0.03, low=-0.04)},
            "Quality regression or uncertainty exceeds policy",
        ),
        (
            {"safety": _metric(-0.01, low=-0.02)},
            "Safety regression or uncertainty exceeds policy",
        ),
        (
            {
                "latency": _metric(
                    90,
                    high=101,
                    unit="milliseconds",
                    lower_is_better=True,
                )
            },
            "Latency regression or uncertainty exceeds policy",
        ),
        (
            {"error_rate": _metric(0.01, high=0.02, unit="rate", lower_is_better=True)},
            "Error-rate regression or uncertainty exceeds policy",
        ),
        (
            {"cost": _metric(0.004, high=0.006, unit="usd", lower_is_better=True)},
            "Cost regression or uncertainty exceeds policy",
        ),
    ],
)
def test_each_evidence_or_regression_guardrail_fails_closed(
    updates: dict[str, object], reason: str
) -> None:
    decision = _decision(_comparison(**updates))

    assert decision.allowed is False
    assert reason in decision.reasons


def test_policy_rejects_impossible_success_threshold() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        CanaryGuardrailPolicy(min_samples=10, min_successful_samples=11)
