"""Adapters from runtime health contracts into sanitized incident signals."""

from datetime import datetime
from typing import Any
from uuid import UUID

from packages.contracts.delivery import (
    CanaryGateDecision,
    CanaryGuardrailPolicy,
    DeliveryEnvironment,
    ShadowComparison,
)
from packages.contracts.incident import (
    IncidentSeverity,
    IncidentSignal,
    IncidentTriggerType,
)
from packages.contracts.observability import SLOStatus


class IncidentSignalFactory:
    """Normalize concrete health outputs before deterministic breach evaluation."""

    @staticmethod
    def from_slo_status(
        status: SLOStatus,
        *,
        idempotency_key: str,
        agent_name: str,
        environment: DeliveryEnvironment,
        observed_at: datetime,
        source_ref: str,
        release_id: UUID | None = None,
        route_id: UUID | None = None,
    ) -> IncidentSignal | None:
        if status.alert_severity is None:
            return None
        burn_rates = [
            window.burn_rate for window in status.burn_windows if window.burn_rate is not None
        ]
        if not burn_rates:
            return None
        threshold = 14.4 if status.alert_severity == "critical" else 6.0
        return IncidentSignal(
            idempotency_key=idempotency_key,
            trigger_type=IncidentTriggerType.SLO_BURN,
            severity=IncidentSeverity(status.alert_severity),
            agent_name=agent_name,
            environment=environment,
            signal_name=f"slo.{status.objective_id}.burn_rate",
            observed_value=max(burn_rates),
            threshold=threshold,
            observed_at=observed_at,
            source_ref=source_ref,
            summary=f"{status.objective_id} has a {status.alert_severity} burn-rate alert",
            release_id=release_id,
            route_id=route_id,
        )

    @staticmethod
    def from_shadow_comparison(
        comparison: ShadowComparison,
        policy: CanaryGuardrailPolicy,
        *,
        idempotency_prefix: str,
        agent_name: str,
        environment: DeliveryEnvironment,
        source_ref: str,
    ) -> list[IncidentSignal]:
        common: dict[str, Any] = {
            "agent_name": agent_name,
            "environment": environment,
            "observed_at": comparison.window_end,
            "source_ref": source_ref,
            "release_id": comparison.candidate_release_id,
            "route_id": comparison.route_id,
        }
        return [
            IncidentSignal(
                idempotency_key=f"{idempotency_prefix}-quality",
                trigger_type=IncidentTriggerType.QUALITY_REGRESSION,
                severity=IncidentSeverity.WARNING,
                signal_name="shadow.quality_confidence_low",
                observed_value=comparison.quality.confidence_low,
                threshold=policy.min_quality_delta,
                summary="Candidate quality confidence bound crossed its minimum",
                **common,
            ),
            IncidentSignal(
                idempotency_key=f"{idempotency_prefix}-error-rate",
                trigger_type=IncidentTriggerType.ERROR_RATE,
                severity=IncidentSeverity.CRITICAL,
                signal_name="shadow.error_rate_confidence_high",
                observed_value=comparison.error_rate.confidence_high,
                threshold=policy.max_error_rate_delta,
                summary="Candidate error-rate confidence bound crossed its maximum",
                **common,
            ),
            IncidentSignal(
                idempotency_key=f"{idempotency_prefix}-cost",
                trigger_type=IncidentTriggerType.COST_ANOMALY,
                severity=IncidentSeverity.WARNING,
                signal_name="shadow.cost_confidence_high_usd",
                observed_value=comparison.cost.confidence_high,
                threshold=policy.max_cost_delta_usd,
                summary="Candidate cost confidence bound crossed its maximum",
                **common,
            ),
            IncidentSignal(
                idempotency_key=f"{idempotency_prefix}-safety",
                trigger_type=IncidentTriggerType.SAFETY_VIOLATION,
                severity=IncidentSeverity.CRITICAL,
                signal_name="shadow.safety_confidence_low",
                observed_value=comparison.safety.confidence_low,
                threshold=policy.min_safety_delta,
                summary="Candidate safety confidence bound crossed its minimum",
                **common,
            ),
        ]

    @staticmethod
    def from_canary_gate(
        gate: CanaryGateDecision,
        *,
        idempotency_key: str,
        agent_name: str,
        environment: DeliveryEnvironment,
        source_ref: str,
        release_id: UUID,
        route_id: UUID,
        canary_rollout_id: UUID,
    ) -> IncidentSignal:
        failures = sum(not check.passed for check in gate.checks)
        return IncidentSignal(
            idempotency_key=idempotency_key,
            trigger_type=IncidentTriggerType.CANARY_GUARDRAIL_FAILURE,
            severity=IncidentSeverity.CRITICAL,
            agent_name=agent_name,
            environment=environment,
            signal_name="canary.failed_guardrail_count",
            observed_value=failures,
            threshold=0,
            observed_at=gate.evaluated_at,
            source_ref=source_ref,
            summary=f"Canary evaluation reported {failures} failed guardrail checks",
            release_id=release_id,
            route_id=route_id,
            canary_rollout_id=canary_rollout_id,
        )
