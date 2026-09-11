"""Canonical top-k regression investigation and automatic recovery proof."""

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import text

from packages.contracts.delivery import CanaryAction, CanaryActionRequest, CreateCanaryRequest
from packages.contracts.incident import (
    DraftNarrativeClaim,
    InvestigatorDraft,
    InvestigatorRequest,
    ObserveIncidentSignalRequest,
    PrepareRollbackRequest,
    RecommendedIncidentAction,
    RecoveryOutcome,
    RecoveryPolicy,
    RollbackPolicyInput,
    RollbackStatus,
)
from packages.delivery.canary_repository import CanaryRepository
from packages.delivery.repository import DeliveryRepository
from packages.incidents.analysis import DeterministicIncidentAnalyzer
from packages.incidents.coordinator import RollbackCoordinator
from packages.incidents.evidence_repository import IncidentEvidenceRepository
from packages.incidents.faults import TopKRegressionFault
from packages.incidents.investigator import LangGraphIncidentInvestigator
from packages.incidents.recovery import RollbackRecoveryVerifier
from packages.incidents.repository import IncidentRepository
from packages.incidents.rollback import KnownGoodRollbackExecutor, KnownGoodRollbackPlanner
from packages.incidents.rollback_repository import RollbackOperationRepository
from packages.incidents.service import IncidentService
from packages.incidents.timeline import IncidentTimelineBuilder
from packages.registry.database import Database
from packages.release.repository import ReleaseRepository
from tests.integration.test_canary_repository import healthy_comparison
from tests.integration.test_delivery_repository import _create_request, _eligible_releases

ROOT = Path(__file__).parents[2]


@pytest.fixture
def incident_database() -> Iterator[Database]:
    database_url = os.getenv("AGENTHUB_DATABASE_URL")
    if database_url is None:
        pytest.skip("Incident rollback E2E requires AGENTHUB_DATABASE_URL")
    alembic = Config(ROOT / "alembic.ini")
    alembic.set_main_option("sqlalchemy.url", database_url)
    alembic_command.upgrade(alembic, "head")
    database = Database(database_url)
    with database.engine.begin() as connection:
        connection.execute(text("TRUNCATE registry_audit_events, agent_versions, agents CASCADE"))
    try:
        yield database
    finally:
        with database.engine.begin() as connection:
            connection.execute(
                text("TRUNCATE registry_audit_events, agent_versions, agents CASCADE")
            )
        database.dispose()


class DrillSummaryModel:
    name = "fake/grounded-incident-drill-v1"

    async def summarize(self, request: InvestigatorRequest) -> InvestigatorDraft:
        probable = request.deterministic.probable_cause
        assert probable is not None
        cause_ids = [citation.evidence_id for citation in probable.citations]
        counter_ids = [
            citation.evidence_id
            for finding in request.deterministic.counter_evidence
            for citation in finding.citations
        ]

        def claim(statement: str, citation_ids: list[UUID] | None = None) -> DraftNarrativeClaim:
            return DraftNarrativeClaim(
                statement=statement,
                uncertainty="low",
                citation_ids=citation_ids or cause_ids,
            )

        return InvestigatorDraft(
            probable_cause=claim(
                "The top-k increase likely caused retrieval fan-out and the p95 regression"
            ),
            observations=[claim("Retrieval latency increased after the configuration change")],
            counter_evidence=[claim("Model latency did not materially change", counter_ids)],
            blast_radius=claim("The regression is bounded to the active candidate canary"),
            recommended_action=RecommendedIncidentAction.REQUEST_ROLLBACK,
            recommendation_rationale=claim(
                "The cited canary regression supports requesting a known-good rollback"
            ),
        )


@pytest.mark.e2e
@pytest.mark.integration
def test_top_k_regression_is_investigated_rolled_back_and_recovered(
    incident_database: Database,
) -> None:
    registry_database = incident_database
    observed_at = datetime.now(UTC)
    stable_id, candidate_id = _eligible_releases(registry_database)
    releases = ReleaseRepository(registry_database)
    target = releases.get(stable_id)
    routes = DeliveryRepository(registry_database)
    route = routes.create(_create_request(stable_id, candidate_id)).route
    canaries = CanaryRepository(registry_database)
    canary = canaries.create(
        CreateCanaryRequest(
            idempotency_key="top-k-drill-canary-create",
            route_id=route.id,
            expected_route_revision=route.revision,
            actor="delivery-controller",
            reason="Start the top-k regression recovery drill",
        )
    ).rollout
    canary = canaries.transition(
        canary.id,
        CanaryActionRequest(
            idempotency_key="top-k-drill-canary-start",
            action=CanaryAction.START,
            expected_revision=canary.revision,
            expected_route_revision=route.revision,
            actor="delivery-controller",
            reason="Expose five percent of traffic to the fault candidate",
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

    scenario = TopKRegressionFault().build(
        agent_name="knowledge-agent",
        environment="production",
        release_id=candidate_id,
        route_id=route.id,
        canary_rollout_id=canary.id,
        observed_at=observed_at,
    )
    incidents = IncidentRepository(registry_database)
    detection = IncidentService(incidents).observe(
        ObserveIncidentSignalRequest(signal=scenario.signal, actor="incident-controller")
    )
    assert detection.detected and detection.result is not None
    incident = detection.result.incident
    evidence_store = IncidentEvidenceRepository(registry_database)
    stored = evidence_store.collect(
        incident.id, list(scenario.evidence), actor="evidence-collector"
    )
    evidence = [result.evidence for result in stored]
    timeline = IncidentTimelineBuilder().build(
        incident.id,
        incidents.triggers(incident.id),
        evidence,
        generated_at=observed_at,
    )
    analysis = DeterministicIncidentAnalyzer().analyze(
        incident.id,
        timeline,
        evidence,
        generated_at=observed_at,
    )
    assert analysis.probable_cause is not None
    assert "retrieval fan-out" in analysis.probable_cause.statement
    assert "Model latency remained" in analysis.counter_evidence[0].statement
    report = asyncio.run(
        LangGraphIncidentInvestigator(DrillSummaryModel()).investigate(
            InvestigatorRequest(
                incident_id=incident.id,
                deterministic=analysis,
                timeline=timeline,
            ),
            generated_at=observed_at,
        )
    )
    assert report.recommended_action is RecommendedIncidentAction.REQUEST_ROLLBACK
    stored_ids = {entry.entry_id for entry in timeline.entries}
    report_claims = [
        *report.observations,
        *report.counter_evidence,
        report.recommendation_rationale,
    ]
    assert all(
        {citation.evidence_id for citation in claim.citations} <= stored_ids
        for claim in report_claims
    )

    command = KnownGoodRollbackPlanner.prepare(
        incident,
        route,
        target,
        PrepareRollbackRequest(
            idempotency_key="top-k-drill-rollback",
            incident_id=incident.id,
            route_id=route.id,
            expected_route_revision=route.revision,
            canary_rollout_id=canary.id,
            expected_canary_revision=canary.revision,
            target_release_id=target.id,
            target_provenance_hash=target.provenance_hash,
            actor="rollback-controller",
            reason="Restore the immutable known-good top-k 5 release",
            requested_at=observed_at,
        ),
        canary=canary,
    )
    operations = RollbackOperationRepository(registry_database)
    rollback = RollbackCoordinator(
        operations,
        KnownGoodRollbackExecutor(routes, canaries),
    ).execute(
        command,
        RollbackPolicyInput(
            canary_active=True,
            guardrail_breached=True,
            evidence_count=len(evidence),
            evaluated_at=observed_at,
        ),
        executed_at=observed_at,
    )
    assert rollback.operation.status is RollbackStatus.EXECUTED
    assert rollback.operation.mode.value == "automatic"
    assert routes.get(route.id).allocation.candidate_weight_basis_points == 0

    recovery_policy = RecoveryPolicy()
    verifier = RollbackRecoveryVerifier(operations)
    verification_started = datetime.now(UTC)
    verifying = verifier.begin(rollback.operation, recovery_policy, started_at=verification_started)
    assert verifying.verification_deadline is not None
    recovery, completed = verifier.verify(
        verifying,
        TopKRegressionFault.recovery_observation(window_start=verification_started),
        recovery_policy,
        evaluated_at=verifying.verification_deadline,
    )

    assert recovery.outcome is RecoveryOutcome.RECOVERED
    assert completed.status is RollbackStatus.RECOVERED
    assert incidents.get(incident.id).status.value == "resolved"
    assert [event.action for event in canaries.events(canary.id)] == [
        None,
        CanaryAction.START,
        CanaryAction.ABORT,
    ]
    with registry_database.transaction() as session:
        rollback_events = session.execute(
            text(
                "SELECT status FROM rollback_events WHERE operation_id = :id "
                "ORDER BY occurred_at, id"
            ),
            {"id": completed.id},
        ).scalars()
        assert list(rollback_events) == ["requested", "executed", "verifying", "recovered"]
