"""Explainable absolute and candidate-versus-production release gates."""

from uuid import UUID

from packages.contracts.evaluation import (
    GateDecision,
    GateProfile,
    GateReason,
    MetricAggregate,
    MetricDirection,
    RegressionMode,
)


def decide_gate(
    profile: GateProfile,
    candidate: list[MetricAggregate],
    baseline: list[MetricAggregate] | None = None,
    baseline_run_id: UUID | None = None,
) -> GateDecision:
    """Evaluate every configured threshold and fail closed on absent metrics."""
    candidate_values = {metric.name: metric for metric in candidate}
    baseline_values = {metric.name: metric for metric in baseline or []}
    reasons: list[GateReason] = []
    for name, threshold in profile.thresholds.items():
        metric = candidate_values.get(name)
        if metric is None or metric.error_count:
            reasons.append(
                GateReason(
                    code="metric_unavailable",
                    passed=False,
                    metric=name,
                    candidate_value=metric.value if metric else None,
                    message=f"{name} is missing or has evaluator errors",
                )
            )
            continue
        value = metric.value
        if threshold.minimum is not None:
            passed = value >= threshold.minimum
            outcome = "meets" if passed else "is below"
            reasons.append(
                GateReason(
                    code="minimum_passed" if passed else "minimum_failed",
                    passed=passed,
                    metric=name,
                    candidate_value=value,
                    threshold=threshold.minimum,
                    message=(f"{name} {value:.6g} {outcome} minimum {threshold.minimum:.6g}"),
                )
            )
        if threshold.maximum is not None:
            passed = value <= threshold.maximum
            outcome = "meets" if passed else "exceeds"
            reasons.append(
                GateReason(
                    code="maximum_passed" if passed else "maximum_failed",
                    passed=passed,
                    metric=name,
                    candidate_value=value,
                    threshold=threshold.maximum,
                    message=(f"{name} {value:.6g} {outcome} maximum {threshold.maximum:.6g}"),
                )
            )
        if threshold.max_regression is not None and baseline is not None:
            baseline_metric = baseline_values.get(name)
            if baseline_metric is None or baseline_metric.error_count:
                reasons.append(
                    GateReason(
                        code="baseline_metric_unavailable",
                        passed=False,
                        metric=name,
                        candidate_value=value,
                        message=f"Baseline {name} is missing or has evaluator errors",
                    )
                )
                continue
            baseline_value = baseline_metric.value
            regression = _regression(
                value,
                baseline_value,
                threshold.direction,
                threshold.regression_mode,
            )
            passed = regression <= threshold.max_regression
            reasons.append(
                GateReason(
                    code="regression_passed" if passed else "regression_failed",
                    passed=passed,
                    metric=name,
                    candidate_value=value,
                    baseline_value=baseline_value,
                    threshold=threshold.max_regression,
                    message=(
                        f"{name} regression {regression:.6g} "
                        f"{'meets' if passed else 'exceeds'} maximum "
                        f"{threshold.max_regression:.6g}"
                    ),
                )
            )
    return GateDecision(
        passed=bool(reasons) and all(reason.passed for reason in reasons),
        profile_id=profile.profile_id,
        profile_version=profile.version,
        baseline_run_id=baseline_run_id,
        reasons=reasons,
    )


def _regression(
    candidate: float,
    baseline: float,
    direction: MetricDirection,
    mode: RegressionMode,
) -> float:
    raw = (
        baseline - candidate
        if direction == MetricDirection.HIGHER_IS_BETTER
        else candidate - baseline
    )
    if mode == RegressionMode.ABSOLUTE:
        return max(0.0, raw)
    denominator = abs(baseline)
    if denominator == 0:
        return 0.0 if raw <= 0 else float("inf")
    return max(0.0, raw / denominator)
