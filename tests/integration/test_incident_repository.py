"""PostgreSQL coverage for idempotent incident intake and immutable triggers."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from packages.contracts.delivery import DeliveryEnvironment
from packages.contracts.incident import (
    IncidentSeverity,
    IncidentSignal,
    IncidentStatus,
    IncidentTriggerType,
    ObserveIncidentSignalRequest,
)
from packages.incidents.repository import (
    IncidentConflictError,
    IncidentNotFoundError,
    IncidentRepository,
)
from packages.incidents.service import IncidentService
from packages.registry.database import Database


def _signal(**updates: object) -> IncidentSignal:
    values: dict[str, object] = {
        "idempotency_key": "incident-error-rate-production",
        "trigger_type": IncidentTriggerType.ERROR_RATE,
        "severity": IncidentSeverity.CRITICAL,
        "agent_name": "shopping-agent",
        "environment": DeliveryEnvironment.PRODUCTION,
        "signal_name": "agent.error_rate",
        "observed_value": 0.08,
        "threshold": 0.01,
        "observed_at": datetime(2026, 9, 10, 20, 0, tzinfo=UTC),
        "source_ref": "telemetry://shopping-agent/slo/error-rate",
        "summary": "Production error rate exceeded its maximum threshold",
    }
    values.update(updates)
    return IncidentSignal.model_validate(values)


@pytest.mark.integration
def test_incident_migration_created_intake_tables(registry_database: Database) -> None:
    tables = set(inspect(registry_database.engine).get_table_names())
    assert {"incidents", "incident_triggers"} <= tables


@pytest.mark.integration
def test_breached_signal_creates_idempotent_incident_and_trigger(
    registry_database: Database,
) -> None:
    repository = IncidentRepository(registry_database)
    service = IncidentService(repository)
    request = ObserveIncidentSignalRequest(signal=_signal(), actor="incident-controller")

    first = service.observe(request)
    replay = service.observe(request)

    assert first.detected is True
    assert first.result is not None
    assert first.result.created is True
    assert first.result.incident.status is IncidentStatus.DETECTED
    assert first.result.incident.trigger_count == 1
    assert replay.detected is True
    assert replay.result is not None
    assert replay.result.created is False
    assert replay.result.incident == first.result.incident
    assert replay.result.trigger == first.result.trigger
    assert repository.get(first.result.incident.id) == first.result.incident
    assert repository.list_incidents("shopping-agent") == [first.result.incident]
    assert repository.triggers(first.result.incident.id) == [first.result.trigger]


@pytest.mark.integration
def test_non_breach_is_not_persisted_and_conflicting_retry_is_rejected(
    registry_database: Database,
) -> None:
    repository = IncidentRepository(registry_database)
    service = IncidentService(repository)
    safe = service.observe(
        ObserveIncidentSignalRequest(
            signal=_signal(observed_value=0.01), actor="incident-controller"
        )
    )
    assert safe.detected is False
    assert repository.list_incidents() == []

    request = ObserveIncidentSignalRequest(signal=_signal(), actor="incident-controller")
    service.observe(request)
    with pytest.raises(IncidentConflictError, match="different operational signal"):
        service.observe(
            request.model_copy(
                update={"signal": request.signal.model_copy(update={"observed_value": 0.09})}
            )
        )


@pytest.mark.integration
def test_database_protects_incident_identity_and_trigger_history(
    registry_database: Database,
) -> None:
    detection = IncidentService(IncidentRepository(registry_database)).observe(
        ObserveIncidentSignalRequest(signal=_signal(), actor="incident-controller")
    )
    assert detection.result is not None
    incident_id = detection.result.incident.id

    with (
        pytest.raises(DBAPIError, match="incident identity is immutable"),
        registry_database.transaction() as session,
    ):
        session.execute(
            text("UPDATE incidents SET agent_name = 'knowledge-agent' WHERE id = :id"),
            {"id": incident_id},
        )
    with (
        pytest.raises(DBAPIError, match="incidents cannot be deleted"),
        registry_database.transaction() as session,
    ):
        session.execute(text("DELETE FROM incidents WHERE id = :id"), {"id": incident_id})
    with (
        pytest.raises(DBAPIError, match="incident triggers are append-only"),
        registry_database.transaction() as session,
    ):
        session.execute(
            text("DELETE FROM incident_triggers WHERE incident_id = :id"),
            {"id": incident_id},
        )


@pytest.mark.integration
def test_missing_incident_returns_a_stable_error(registry_database: Database) -> None:
    with pytest.raises(IncidentNotFoundError, match="Incident was not found"):
        IncidentRepository(registry_database).get(uuid4())
