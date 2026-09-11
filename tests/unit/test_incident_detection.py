"""Deterministic operational incident trigger coverage."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.contracts.delivery import (
    CanaryGateDecision,
    CanaryGuardrailPolicy,
    DeliveryEnvironment,
    GuardrailCheck,
    MetricDelta,
    ShadowComparison,
)
from packages.contracts.incident import (
    IncidentSeverity,
    IncidentSignal,
    IncidentTriggerType,
    ObserveIncidentSignalRequest,
)
from packages.contracts.observability import BurnRateWindow, SLOIndicator, SLOStatus
from packages.incidents.detection import IncidentTriggerDetector
from packages.incidents.service import IncidentService
from packages.incidents.sources import IncidentSignalFactory

NOW = datetime(2026, 9, 10, 20, 0, tzinfo=UTC)


def _signal(
    trigger_type: IncidentTriggerType,
    observed: float,
    threshold: float,
) -> IncidentSignal:
    return IncidentSignal(
        idempotency_key=f"incident-{trigger_type.value}",
        trigger_type=trigger_type,
        severity=IncidentSeverity.CRITICAL,
        agent_name="shopping-agent",
        environment=DeliveryEnvironment.PRODUCTION,
        signal_name=f"shopping.{trigger_type.value}",
        observed_value=observed,
        threshold=threshold,
        observed_at=NOW,
        source_ref=f"telemetry://shopping-agent/{trigger_type.value}",
        summary=f"Shopping Agent reported {trigger_type.value.replace('_', ' ')}",
        canary_rollout_id=(
            uuid4() if trigger_type is IncidentTriggerType.CANARY_GUARDRAIL_FAILURE else None
        ),
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("trigger_type", "observed", "threshold", "operator"),
    [
        (IncidentTriggerType.SLO_BURN, 14.4, 14.4, ">="),
        (IncidentTriggerType.QUALITY_REGRESSION, -0.03, -0.02, "<"),
        (IncidentTriggerType.ERROR_RATE, 0.02, 0.01, ">"),
        (IncidentTriggerType.COST_ANOMALY, 0.03, 0.01, ">"),
        (IncidentTriggerType.SAFETY_VIOLATION, -0.01, 0, "<"),
        (IncidentTriggerType.CANARY_GUARDRAIL_FAILURE, 1, 0, ">"),
    ],
)
def test_each_operational_trigger_has_an_explainable_breach_rule(
    trigger_type: IncidentTriggerType,
    observed: float,
    threshold: float,
    operator: str,
) -> None:
    evaluation = IncidentTriggerDetector.evaluate(_signal(trigger_type, observed, threshold))

    assert evaluation.breached is True
    assert evaluation.operator == operator
    assert "breached" in evaluation.reason


@pytest.mark.unit
@pytest.mark.parametrize(
    ("trigger_type", "observed", "threshold"),
    [
        (IncidentTriggerType.SLO_BURN, 14.39, 14.4),
        (IncidentTriggerType.QUALITY_REGRESSION, -0.02, -0.02),
        (IncidentTriggerType.ERROR_RATE, 0.01, 0.01),
        (IncidentTriggerType.COST_ANOMALY, 0.01, 0.01),
        (IncidentTriggerType.SAFETY_VIOLATION, 0, 0),
        (IncidentTriggerType.CANARY_GUARDRAIL_FAILURE, 0, 0),
    ],
)
def test_healthy_boundary_does_not_open_an_incident(
    trigger_type: IncidentTriggerType,
    observed: float,
    threshold: float,
) -> None:
    signal = _signal(trigger_type, observed, threshold)
    store = Mock()

    detection = IncidentService(store).observe(
        ObserveIncidentSignalRequest(signal=signal, actor="incident-controller")
    )

    assert detection.detected is False
    assert detection.result is None
    assert "did not breach" in detection.evaluation.reason
    store.create.assert_not_called()


@pytest.mark.unit
def test_signal_requires_aware_time_and_canary_identity() -> None:
    signal = _signal(IncidentTriggerType.ERROR_RATE, 0.02, 0.01)
    with pytest.raises(ValidationError, match="timezone-aware"):
        IncidentSignal.model_validate(
            signal.model_dump() | {"observed_at": datetime(2026, 9, 10, 20, 0)}
        )
    with pytest.raises(ValidationError, match="rollout identifier"):
        IncidentSignal.model_validate(
            _signal(IncidentTriggerType.CANARY_GUARDRAIL_FAILURE, 1, 0).model_dump()
            | {"canary_rollout_id": None}
        )


@pytest.mark.unit
def test_signal_rejects_non_finite_measurements() -> None:
    signal = _signal(IncidentTriggerType.ERROR_RATE, 0.02, 0.01)
    with pytest.raises(ValidationError):
        IncidentSignal.model_validate(signal.model_dump() | {"observed_value": float("inf")})


@pytest.mark.unit
def test_slo_alert_is_normalized_into_a_burn_trigger() -> None:
    status = SLOStatus(
        objective_id="availability",
        indicator=SLOIndicator.AVAILABILITY,
        target=0.99,
        threshold=None,
        window_seconds=86_400,
        good_events=80,
        total_events=100,
        compliance=0.8,
        error_budget_remaining=0,
        burn_windows=[
            BurnRateWindow(
                window_seconds=300,
                good_events=80,
                total_events=100,
                error_ratio=0.2,
                burn_rate=20,
            )
        ],
        alert_severity="critical",
    )

    signal = IncidentSignalFactory.from_slo_status(
        status,
        idempotency_key="incident-slo-availability",
        agent_name="shopping-agent",
        environment=DeliveryEnvironment.PRODUCTION,
        observed_at=NOW,
        source_ref="telemetry://shopping-agent/slo/availability",
    )

    assert signal is not None
    assert signal.trigger_type is IncidentTriggerType.SLO_BURN
    assert signal.observed_value == 20
    assert IncidentTriggerDetector.evaluate(signal).breached is True


def _metric(value: float, *, lower_is_better: bool = False) -> MetricDelta:
    return MetricDelta(
        samples=100,
        stable_mean=0.5,
        candidate_mean=0.5 + value,
        delta=value,
        confidence_low=value,
        confidence_high=value,
        unit="rate" if lower_is_better else "score",
        lower_is_better=lower_is_better,
    )


@pytest.mark.unit
def test_shadow_comparison_normalizes_quality_error_cost_and_safety_signals() -> None:
    comparison = ShadowComparison(
        route_id=uuid4(),
        route_revisions=[2],
        stable_release_id=uuid4(),
        candidate_release_id=uuid4(),
        sample_count=100,
        successful_sample_count=90,
        window_start=NOW - timedelta(minutes=10),
        window_end=NOW,
        quality=_metric(-0.03),
        safety=_metric(-0.01),
        latency=_metric(10, lower_is_better=True),
        error_rate=_metric(0.02, lower_is_better=True),
        cost=MetricDelta(
            samples=100,
            stable_mean=0.01,
            candidate_mean=0.02,
            delta=0.01,
            confidence_low=0.01,
            confidence_high=0.01,
            unit="usd",
            lower_is_better=True,
        ),
    )

    signals = IncidentSignalFactory.from_shadow_comparison(
        comparison,
        CanaryGuardrailPolicy(),
        idempotency_prefix="incident-shadow-comparison",
        agent_name="shopping-agent",
        environment=DeliveryEnvironment.PRODUCTION,
        source_ref="delivery://comparison/shopping-agent",
    )

    assert {signal.trigger_type for signal in signals} == {
        IncidentTriggerType.QUALITY_REGRESSION,
        IncidentTriggerType.ERROR_RATE,
        IncidentTriggerType.COST_ANOMALY,
        IncidentTriggerType.SAFETY_VIOLATION,
    }
    assert all(IncidentTriggerDetector.evaluate(signal).breached for signal in signals)


@pytest.mark.unit
def test_failed_canary_gate_is_normalized_into_a_guardrail_trigger() -> None:
    gate = CanaryGateDecision(
        allowed=False,
        checks=[
            GuardrailCheck(
                name="safety_confidence_low",
                passed=False,
                observed=-0.01,
                operator=">=",
                threshold=0,
                reason="Safety confidence bound failed",
            )
        ],
        reasons=["Safety confidence bound failed"],
        evaluated_at=NOW,
    )
    signal = IncidentSignalFactory.from_canary_gate(
        gate,
        idempotency_key="incident-canary-guardrail",
        agent_name="shopping-agent",
        environment=DeliveryEnvironment.PRODUCTION,
        source_ref="delivery://canary/guardrail",
        release_id=uuid4(),
        route_id=uuid4(),
        canary_rollout_id=uuid4(),
    )

    assert signal.trigger_type is IncidentTriggerType.CANARY_GUARDRAIL_FAILURE
    assert signal.observed_value == 1
    assert IncidentTriggerDetector.evaluate(signal).breached is True
