"""Cost ledger aggregation and telemetry integration tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from packages.observability.conventions import Attribute
from packages.observability.cost import CostLedger
from packages.observability.telemetry import Telemetry, TelemetryConfig

NOW = datetime(2026, 9, 10, 18, tzinfo=UTC)


def _record(
    ledger: CostLedger,
    *,
    agent: str = "knowledge-agent",
    version: str = "1.0.0",
    model: str = "azure/gpt-small",
    environment: str = "production",
    team: str = "retail-ai-team",
    cost: float = 0.01,
    occurred_at: datetime = NOW,
) -> None:
    ledger.record(
        agent_name=agent,
        agent_version=version,
        model=model,
        environment=environment,
        team=team,
        input_tokens=10,
        output_tokens=5,
        cost_usd=cost,
        occurred_at=occurred_at,
    )


def test_costs_roll_up_by_agent_version_model_environment_and_team() -> None:
    ledger = CostLedger()
    _record(ledger)
    _record(ledger, cost=0.02)
    _record(ledger, model="azure/gpt-large", cost=0.1)
    _record(ledger, agent="shopping-agent", environment="staging", cost=0.03)

    report = ledger.report(
        window_start=NOW - timedelta(minutes=1),
        window_end=NOW + timedelta(minutes=1),
    )

    assert report.invocation_count == 4
    assert report.input_tokens == 40
    assert report.output_tokens == 20
    assert report.cost_usd == pytest.approx(0.16)
    assert len(report.rows) == 3
    small = next(row for row in report.rows if row.model == "azure/gpt-small")
    assert small.invocation_count == 2
    assert small.cost_usd == pytest.approx(0.03)
    assert small.agent_name == "knowledge-agent"
    assert small.agent_version == "1.0.0"
    assert small.environment == "production"
    assert small.team == "retail-ai-team"


def test_cost_report_filters_window_team_and_environment() -> None:
    ledger = CostLedger()
    _record(ledger)
    _record(ledger, team="other-team")
    _record(ledger, occurred_at=NOW - timedelta(days=1))

    report = ledger.report(
        window_start=NOW - timedelta(minutes=1),
        window_end=NOW + timedelta(minutes=1),
        team="retail-ai-team",
        environment="production",
    )

    assert report.invocation_count == 1
    assert report.rows[0].team == "retail-ai-team"


def test_telemetry_attaches_environment_and_team_to_cost_ledger() -> None:
    ledger = CostLedger()
    telemetry = Telemetry(
        TelemetryConfig("agenthub", "test", "staging"),
        cost_ledger=ledger,
    )

    telemetry.record_model(
        {
            Attribute.AGENT_NAME: "inventory-agent",
            Attribute.AGENT_VERSION: "2.0.0",
            Attribute.MODEL_PROVIDER: "azure",
            Attribute.MODEL_DEPLOYMENT: "azure/gpt-small",
            Attribute.TEAM: "supply-team",
        },
        input_tokens=20,
        output_tokens=8,
        cost_usd=0.04,
    )
    report = ledger.report(
        window_start=datetime.now(UTC) - timedelta(seconds=1),
        window_end=datetime.now(UTC) + timedelta(seconds=1),
    )

    assert report.rows[0].environment == "staging"
    assert report.rows[0].team == "supply-team"
    assert report.rows[0].agent_name == "inventory-agent"


def test_cost_ledger_is_bounded_and_thread_safe() -> None:
    ledger = CostLedger(capacity=10)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: _record(ledger), range(40)))
    report = ledger.report(
        window_start=NOW - timedelta(minutes=1),
        window_end=NOW + timedelta(minutes=1),
    )

    assert report.invocation_count == 10


def test_invalid_capacity_or_window_is_rejected() -> None:
    with pytest.raises(ValueError, match="capacity"):
        CostLedger(capacity=0)
    with pytest.raises(ValueError, match="window end"):
        CostLedger().report(window_start=NOW, window_end=NOW - timedelta(seconds=1))
