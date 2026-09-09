"""SLO arithmetic, burn-rate alerting, and fleet-health contracts."""

from typing import Any

import pytest
from pydantic import ValidationError

from packages.contracts.observability import SLOIndicator, SLOObjective
from packages.observability.conventions import Attribute
from packages.observability.slos import evaluate_objective, fleet_health, load_slo_profile
from packages.observability.telemetry import Observation, Telemetry, TelemetryConfig


def _event(
    signal: str,
    value: float,
    occurred_at: float,
    attributes: dict[str, Any] | None = None,
) -> Observation:
    return Observation(occurred_at, signal, value, attributes or {})


@pytest.mark.unit
def test_default_profile_covers_the_required_indicators() -> None:
    profile = load_slo_profile()

    assert {objective.indicator for objective in profile.objectives} == set(SLOIndicator)
    assert profile.version == "1.0.0"


@pytest.mark.unit
def test_threshold_objectives_require_a_threshold() -> None:
    with pytest.raises(ValidationError, match="require a threshold"):
        SLOObjective(
            objective_id="latency",
            indicator=SLOIndicator.LATENCY,
            target=0.95,
            window_seconds=300,
        )


@pytest.mark.unit
def test_forced_availability_failures_exhaust_budget_and_trigger_critical_burn() -> None:
    objective = SLOObjective(
        objective_id="availability",
        indicator=SLOIndicator.AVAILABILITY,
        target=0.99,
        window_seconds=30 * 24 * 60 * 60,
    )
    now = 10_000.0
    events = [_event("agent.success", 1, now - 10) for _ in range(8)]
    events.extend(_event("agent.success", 0, now - 10) for _ in range(2))

    status = evaluate_objective(objective, events, now=now)

    assert status.compliance == pytest.approx(0.8)
    assert status.error_budget_remaining == 0
    assert status.alert_severity == "critical"
    assert status.burn_windows[0].burn_rate == pytest.approx(20)


@pytest.mark.unit
def test_groundedness_excludes_other_evaluation_metrics() -> None:
    objective = SLOObjective(
        objective_id="groundedness",
        indicator=SLOIndicator.GROUNDEDNESS,
        target=0.95,
        threshold=0.9,
        window_seconds=300,
    )
    now = 1_000.0
    events = [
        _event(
            "evaluation.score",
            0.92,
            now,
            {Attribute.EVALUATION_METRIC.value: "groundedness"},
        ),
        _event(
            "evaluation.score",
            0.1,
            now,
            {Attribute.EVALUATION_METRIC.value: "correctness"},
        ),
    ]

    status = evaluate_objective(objective, events, now=now)

    assert status.good_events == 1
    assert status.total_events == 1
    assert status.compliance == 1


@pytest.mark.unit
def test_fleet_health_uses_real_bounded_observations_and_trace_link() -> None:
    telemetry = Telemetry(TelemetryConfig("agenthub-api", "test", "test"))
    labels = {Attribute.AGENT_NAME: "inventory-agent"}
    telemetry.record_agent(labels, 120, success=True)
    telemetry.record_tool(labels, 25, success=True)
    telemetry.record_model(labels, input_tokens=10, output_tokens=5, cost_usd=0.001)
    telemetry.record_evaluation(
        labels,
        {"groundedness": 0.98, "correctness": 0.75},
        passed=True,
    )
    trace_id = "0af7651916cd43dd8448eb211c80319c"  # pragma: allowlist secret
    telemetry.remember_trace("inventory-agent", trace_id)

    health = fleet_health(telemetry, {"inventory-agent": "1.0.0"})
    agent = health.agents[0]

    assert agent.request_count == 1
    assert agent.availability == 1
    assert agent.p95_latency_ms == 120
    assert agent.tool_success == 1
    assert agent.groundedness == 0.98
    assert agent.evaluation_pass_rate == 1
    assert agent.mean_cost_usd == 0.001
    assert agent.last_trace_id == "0af7651916cd43dd8448eb211c80319c"  # pragma: allowlist secret
    assert len(agent.slos) == 6


@pytest.mark.unit
def test_trace_index_rejects_invalid_values_and_remains_bounded() -> None:
    telemetry = Telemetry(TelemetryConfig("agenthub-api", "test", "test"))
    telemetry.remember_trace("inventory-agent", "not-a-trace")
    for index in range(129):
        telemetry.remember_trace(f"agent-{index}", f"{index + 1:032x}")

    assert telemetry.last_trace_id("inventory-agent") is None
    assert telemetry.last_trace_id("agent-0") is None
    assert telemetry.last_trace_id("agent-128") == f"{129:032x}"
