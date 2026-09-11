"""PostgreSQL coverage for policy-constrained durable rollback execution."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from packages.contracts.delivery import CanaryAction, CanaryActionRequest, CreateCanaryRequest
from packages.contracts.incident import (
    IncidentSignal,
    IncidentTriggerType,
    ObserveIncidentSignalRequest,
    PrepareRollbackRequest,
    RecoveryObservation,
    RecoveryOutcome,
    RecoveryPolicy,
    RollbackPolicyInput,
    RollbackStatus,
)
from packages.delivery.canary_repository import CanaryRepository
from packages.delivery.repository import DeliveryRepository
from packages.incidents.coordinator import RollbackCoordinator
from packages.incidents.recovery import RollbackRecoveryVerifier
from packages.incidents.repository import IncidentRepository
from packages.incidents.rollback import KnownGoodRollbackExecutor, KnownGoodRollbackPlanner
from packages.incidents.rollback_repository import RollbackOperationRepository
from packages.incidents.service import IncidentService
from packages.registry.database import Database
from packages.release.repository import ReleaseRepository
from tests.integration.test_canary_repository import healthy_comparison
from tests.integration.test_delivery_repository import _create_request, _eligible_releases

NOW = datetime(2026, 9, 11, 6, 30, tzinfo=UTC)


@pytest.mark.integration
def test_automatic_canary_rollback_is_durable_audited_and_idempotent(
    registry_database: Database,
) -> None:
    stable_id, candidate_id = _eligible_releases(registry_database)
    routes = DeliveryRepository(registry_database)
    route = routes.create(_create_request(stable_id, candidate_id)).route
    canaries = CanaryRepository(registry_database)
    canary = canaries.create(
        CreateCanaryRequest(
            idempotency_key="rollback-canary-create",
            route_id=route.id,
            expected_route_revision=route.revision,
            actor="delivery-controller",
            reason="Create candidate rollout for rollback testing",
        )
    ).rollout
    canary = canaries.transition(
        canary.id,
        CanaryActionRequest(
            idempotency_key="rollback-canary-start",
            action=CanaryAction.START,
            expected_revision=canary.revision,
            expected_route_revision=route.revision,
            actor="delivery-controller",
            reason="Start candidate traffic for rollback testing",
            comparison=healthy_comparison(
                route_id=route.id,
                route_revision=route.revision,
                stable_id=stable_id,
                candidate_id=candidate_id,
            ),
            telemetry_healthy=True,
        ),
    )
    route = routes.get(route.id)
    base_signal = IncidentSignal(
        idempotency_key="rollback-incident-trigger",
        trigger_type=IncidentTriggerType.ERROR_RATE,
        severity="critical",
        agent_name="knowledge-agent",
        environment="production",
        signal_name="agent.error_rate",
        observed_value=0.08,
        threshold=0.01,
        observed_at=NOW,
        source_ref="telemetry://knowledge-agent/error-rate",
        summary="Candidate error rate breached its rollback guardrail",
        release_id=candidate_id,
        route_id=route.id,
        canary_rollout_id=canary.id,
    )
    detection = IncidentService(IncidentRepository(registry_database)).observe(
        ObserveIncidentSignalRequest(signal=base_signal, actor="incident-controller")
    )
    assert detection.result is not None
    incident = detection.result.incident
    target = ReleaseRepository(registry_database).get(stable_id)
    request = PrepareRollbackRequest(
        idempotency_key="rollback-automatic-attempt",
        incident_id=incident.id,
        route_id=route.id,
        expected_route_revision=route.revision,
        canary_rollout_id=canary.id,
        expected_canary_revision=canary.revision,
        target_release_id=target.id,
        target_provenance_hash=target.provenance_hash,
        actor="rollback-controller",
        reason="Automatically restore the known-good stable release",
        requested_at=NOW,
    )
    command = KnownGoodRollbackPlanner.prepare(incident, route, target, request, canary=canary)
    operations = RollbackOperationRepository(registry_database)
    coordinator = RollbackCoordinator(
        operations,
        KnownGoodRollbackExecutor(routes, canaries),
    )
    inputs = RollbackPolicyInput(
        canary_active=True,
        guardrail_breached=True,
        evidence_count=3,
        evaluated_at=NOW,
    )

    first = coordinator.execute(command, inputs, executed_at=NOW)
    replay = coordinator.execute(command, inputs, executed_at=NOW)

    assert first.replayed is False
    assert first.execution is not None
    assert first.operation.status is RollbackStatus.EXECUTED
    assert first.operation.mode.value == "automatic"
    assert first.operation.route_revision_after == route.revision + 1
    assert first.execution.route.allocation.stable.release_id == stable_id
    assert first.execution.route.allocation.candidate_weight_basis_points == 0
    assert first.execution.canary is not None
    assert first.execution.canary.progress.state.value == "rolled_back"
    assert replay.replayed is True
    assert replay.operation == first.operation
    recovery_policy = RecoveryPolicy()
    verifier = RollbackRecoveryVerifier(operations)
    verifying = verifier.begin(first.operation, recovery_policy, started_at=NOW)
    decision, recovered = verifier.verify(
        verifying,
        RecoveryObservation(
            window_start=NOW,
            window_end=NOW + timedelta(minutes=5),
            observation_count=10,
            availability=0.999,
            error_rate=0.001,
            p95_latency_ms=250,
            guardrail_healthy=True,
            telemetry_complete=True,
            source_refs=["telemetry://knowledge-agent/recovery"],
        ),
        recovery_policy,
        evaluated_at=NOW + timedelta(minutes=5),
    )
    assert decision.outcome is RecoveryOutcome.RECOVERED
    assert recovered.status is RollbackStatus.RECOVERED
    assert IncidentRepository(registry_database).get(incident.id).status.value == "resolved"
    with registry_database.transaction() as session:
        event_count = session.execute(
            text("SELECT count(*) FROM rollback_events WHERE operation_id = :id"),
            {"id": first.operation.id},
        ).scalar_one()
    assert event_count == 4
    with (
        pytest.raises(DBAPIError, match="rollback events are append-only"),
        registry_database.transaction() as session,
    ):
        session.execute(
            text("DELETE FROM rollback_events WHERE operation_id = :id"),
            {"id": first.operation.id},
        )
