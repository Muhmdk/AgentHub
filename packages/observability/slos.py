"""Versioned SLO loading, error budgets, burn rates, and fleet health."""

import math
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import time

from packages.contracts.observability import (
    AgentHealth,
    BurnRateWindow,
    FleetHealth,
    SLOIndicator,
    SLOObjective,
    SLOProfile,
    SLOStatus,
)
from packages.observability.conventions import Attribute
from packages.observability.telemetry import Observation, Telemetry

BURN_WINDOWS = (300, 1800, 3600, 21600)


def load_slo_profile(profile_id: str = "default", version: str = "1.0.0") -> SLOProfile:
    path = (
        Path(__file__).parents[2] / "data" / "slos" / f"{profile_id}-v{version.split('.')[0]}.json"
    )
    if not path.is_file():
        raise FileNotFoundError(f"SLO profile was not found: {profile_id}@{version}")
    profile = SLOProfile.model_validate_json(path.read_text())
    if profile.version != version:
        raise ValueError(
            f"SLO profile version mismatch: expected {version}, found {profile.version}"
        )
    return profile


def evaluate_objective(
    objective: SLOObjective,
    observations: list[Observation],
    *,
    now: float | None = None,
) -> SLOStatus:
    current = now if now is not None else time()
    signal, predicate, relevant_event = _indicator(objective)
    relevant = [
        event
        for event in observations
        if event.signal == signal
        and event.occurred_at >= current - objective.window_seconds
        and relevant_event(event)
    ]
    good = sum(predicate(event.value) for event in relevant)
    total = len(relevant)
    compliance = good / total if total else None
    budget = _budget_remaining(good, total, objective.target)
    windows = [_burn_window(objective, observations, seconds, current) for seconds in BURN_WINDOWS]
    severity = _alert_severity(windows)
    return SLOStatus(
        objective_id=objective.objective_id,
        indicator=objective.indicator,
        target=objective.target,
        threshold=objective.threshold,
        window_seconds=objective.window_seconds,
        good_events=good,
        total_events=total,
        compliance=compliance,
        error_budget_remaining=budget,
        burn_windows=windows,
        alert_severity=severity,
    )


def fleet_health(
    telemetry: Telemetry,
    agent_versions: dict[str, str],
    profile: SLOProfile | None = None,
) -> FleetHealth:
    selected_profile = profile or load_slo_profile()
    observations = telemetry.observations.snapshot()
    by_agent: dict[str, list[Observation]] = defaultdict(list)
    for event in observations:
        name = event.attributes.get(Attribute.AGENT_NAME.value)
        if isinstance(name, str) and name in agent_versions:
            by_agent[name].append(event)
    agents = [
        _agent_health(
            name,
            version,
            by_agent[name],
            selected_profile,
            telemetry.last_trace_id(name),
        )
        for name, version in sorted(agent_versions.items())
    ]
    return FleetHealth(
        generated_at=datetime.now(UTC).isoformat(),
        profile_id=selected_profile.profile_id,
        profile_version=selected_profile.version,
        agents=agents,
    )


def _agent_health(
    name: str,
    version: str,
    observations: list[Observation],
    profile: SLOProfile,
    trace_id: str | None,
) -> AgentHealth:
    values: dict[str, list[float]] = defaultdict(list)
    for event in observations:
        values[event.signal].append(event.value)
    successes = values["agent.success"]
    latencies = values["agent.duration_ms"]
    tools = values["tool.success"]
    groundedness = [
        event.value
        for event in observations
        if event.signal == "evaluation.score"
        and event.attributes.get(Attribute.EVALUATION_METRIC.value) == "groundedness"
    ]
    evaluations = values["evaluation.gate"]
    costs = values["model.cost_usd"]
    return AgentHealth(
        agent_name=name,
        agent_version=version,
        request_count=len(values["agent.request"]),
        availability=_mean(successes),
        p95_latency_ms=_percentile(latencies, 0.95),
        tool_success=_mean(tools),
        groundedness=_mean(groundedness),
        evaluation_pass_rate=_mean(evaluations),
        mean_cost_usd=_mean(costs),
        last_trace_id=trace_id,
        slos=[evaluate_objective(objective, observations) for objective in profile.objectives],
    )


def _indicator(
    objective: SLOObjective,
) -> tuple[str, Callable[[float], bool], Callable[[Observation], bool]]:
    def any_event(_event: Observation) -> bool:
        return True

    if objective.indicator == SLOIndicator.AVAILABILITY:
        return "agent.success", lambda value: value >= 1, any_event
    if objective.indicator == SLOIndicator.LATENCY:
        threshold = objective.threshold or 0
        return "agent.duration_ms", lambda value: value <= threshold, any_event
    if objective.indicator == SLOIndicator.TOOL_SUCCESS:
        return "tool.success", lambda value: value >= 1, any_event
    if objective.indicator == SLOIndicator.GROUNDEDNESS:
        threshold = objective.threshold or objective.target
        return (
            "evaluation.score",
            lambda value: value >= threshold,
            lambda event: event.attributes.get(Attribute.EVALUATION_METRIC.value) == "groundedness",
        )
    if objective.indicator == SLOIndicator.EVALUATION_PASS_RATE:
        return "evaluation.gate", lambda value: value >= 1, any_event
    threshold = objective.threshold or 0
    return "model.cost_usd", lambda value: value <= threshold, any_event


def _burn_window(
    objective: SLOObjective,
    observations: list[Observation],
    seconds: int,
    current: float,
) -> BurnRateWindow:
    signal, predicate, relevant_event = _indicator(objective)
    events = [
        event
        for event in observations
        if event.signal == signal
        and event.occurred_at >= current - seconds
        and relevant_event(event)
    ]
    good = sum(predicate(event.value) for event in events)
    total = len(events)
    error_ratio = (total - good) / total if total else None
    allowed = 1 - objective.target
    burn_rate = error_ratio / allowed if error_ratio is not None and allowed > 0 else None
    return BurnRateWindow(
        window_seconds=seconds,
        good_events=good,
        total_events=total,
        error_ratio=error_ratio,
        burn_rate=burn_rate,
    )


def _budget_remaining(good: int, total: int, target: float) -> float | None:
    if not total:
        return None
    allowed_bad = total * (1 - target)
    if allowed_bad == 0:
        return float(good == total)
    return max(0.0, 1 - ((total - good) / allowed_bad))


def _alert_severity(windows: list[BurnRateWindow]) -> str | None:
    by_seconds = {window.window_seconds: window for window in windows}
    pairs = (("critical", 300, 3600, 14.4), ("warning", 1800, 21600, 6.0))
    for severity, short, long, threshold in pairs:
        short_rate = by_seconds[short].burn_rate
        long_rate = by_seconds[long].burn_rate
        if (
            short_rate is not None
            and long_rate is not None
            and short_rate >= threshold
            and long_rate >= threshold
        ):
            return severity
    return None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]
