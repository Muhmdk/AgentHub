"""Fail-closed canary promotion guardrails over paired shadow telemetry."""

from datetime import datetime

from packages.contracts.delivery import (
    CanaryGateDecision,
    CanaryGuardrailPolicy,
    GuardrailCheck,
    ShadowComparison,
)


class CanaryGuardrailEvaluator:
    """Require sufficient, fresh evidence and confidence-bounded health."""

    @staticmethod
    def evaluate(
        comparison: ShadowComparison | None,
        policy: CanaryGuardrailPolicy,
        *,
        evaluated_at: datetime,
        telemetry_healthy: bool,
    ) -> CanaryGateDecision:
        checks: list[GuardrailCheck] = [
            GuardrailCheck(
                name="telemetry_present",
                passed=comparison is not None,
                observed=comparison is not None,
                operator="present",
                threshold=True,
                reason=(
                    "Paired telemetry is available"
                    if comparison is not None
                    else "Paired telemetry is missing"
                ),
            ),
            GuardrailCheck(
                name="telemetry_healthy",
                passed=telemetry_healthy,
                observed=telemetry_healthy,
                operator="healthy",
                threshold=True,
                reason=(
                    "Telemetry pipeline is healthy"
                    if telemetry_healthy
                    else "Telemetry pipeline is unhealthy"
                ),
            ),
        ]
        if comparison is not None:
            age_seconds = (evaluated_at - comparison.window_end).total_seconds()
            window_seconds = (comparison.window_end - comparison.window_start).total_seconds()
            checks.extend(
                [
                    CanaryGuardrailEvaluator._maximum(
                        "telemetry_age_seconds",
                        age_seconds,
                        policy.max_telemetry_age_seconds,
                        "Telemetry is fresh",
                        "Telemetry is stale or dated in the future",
                        require_nonnegative=True,
                    ),
                    CanaryGuardrailEvaluator._minimum(
                        "sample_count",
                        comparison.sample_count,
                        policy.min_samples,
                        "Minimum paired sample count reached",
                        "Paired sample count is too low",
                    ),
                    CanaryGuardrailEvaluator._minimum(
                        "successful_sample_count",
                        comparison.successful_sample_count,
                        policy.min_successful_samples,
                        "Minimum successful sample count reached",
                        "Successful candidate sample count is too low",
                    ),
                    CanaryGuardrailEvaluator._minimum(
                        "window_seconds",
                        window_seconds,
                        policy.min_window_seconds,
                        "Minimum observation window reached",
                        "Observation window is too short",
                    ),
                    CanaryGuardrailEvaluator._minimum(
                        "quality_confidence_low",
                        comparison.quality.confidence_low,
                        policy.min_quality_delta,
                        "Quality confidence bound is acceptable",
                        "Quality regression or uncertainty exceeds policy",
                    ),
                    CanaryGuardrailEvaluator._minimum(
                        "safety_confidence_low",
                        comparison.safety.confidence_low,
                        policy.min_safety_delta,
                        "Safety confidence bound is acceptable",
                        "Safety regression or uncertainty exceeds policy",
                    ),
                    CanaryGuardrailEvaluator._maximum(
                        "latency_confidence_high_ms",
                        comparison.latency.confidence_high,
                        policy.max_latency_delta_ms,
                        "Latency confidence bound is acceptable",
                        "Latency regression or uncertainty exceeds policy",
                    ),
                    CanaryGuardrailEvaluator._maximum(
                        "error_rate_confidence_high",
                        comparison.error_rate.confidence_high,
                        policy.max_error_rate_delta,
                        "Error-rate confidence bound is acceptable",
                        "Error-rate regression or uncertainty exceeds policy",
                    ),
                    CanaryGuardrailEvaluator._maximum(
                        "cost_confidence_high_usd",
                        comparison.cost.confidence_high,
                        policy.max_cost_delta_usd,
                        "Cost confidence bound is acceptable",
                        "Cost regression or uncertainty exceeds policy",
                    ),
                ]
            )
        reasons = [check.reason for check in checks if not check.passed]
        return CanaryGateDecision(
            allowed=not reasons,
            checks=checks,
            reasons=reasons,
            evaluated_at=evaluated_at,
        )

    @staticmethod
    def _minimum(
        name: str,
        observed: float | int,
        threshold: float | int,
        passed_reason: str,
        failed_reason: str,
    ) -> GuardrailCheck:
        passed = observed >= threshold
        return GuardrailCheck(
            name=name,
            passed=passed,
            observed=observed,
            operator=">=",
            threshold=threshold,
            reason=passed_reason if passed else failed_reason,
        )

    @staticmethod
    def _maximum(
        name: str,
        observed: float | int,
        threshold: float | int,
        passed_reason: str,
        failed_reason: str,
        *,
        require_nonnegative: bool = False,
    ) -> GuardrailCheck:
        passed = observed <= threshold and (not require_nonnegative or observed >= 0)
        return GuardrailCheck(
            name=name,
            passed=passed,
            observed=observed,
            operator="<=",
            threshold=threshold,
            reason=passed_reason if passed else failed_reason,
        )
