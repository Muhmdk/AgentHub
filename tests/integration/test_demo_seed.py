"""End-to-end database state created by the local demo reset."""

import asyncio
from uuid import UUID

import pytest

from apps.api.config import Settings
from packages.contracts.delivery import CanaryState, DeliveryEnvironment
from packages.contracts.governance import GovernanceAuditOutcome
from packages.delivery.canary_repository import CanaryRepository
from packages.delivery.repository import DeliveryRepository
from packages.evaluation.repository import EvaluationRepository
from packages.governance.repository import GovernanceAuditRepository
from packages.incidents.evidence_repository import IncidentEvidenceRepository
from packages.incidents.repository import IncidentRepository
from packages.registry.database import Database
from scripts.seed_demo import reset_demo, seed_demo


@pytest.mark.integration
def test_demo_reset_recreates_a_complete_truthfully_labelled_story(
    migrated_database: Database,
) -> None:
    settings = Settings(
        environment="test",
        database_url=migrated_database.engine.url.render_as_string(hide_password=False),
        _env_file=None,
    )
    try:
        reset_demo(settings, migrated_database)
        report = asyncio.run(seed_demo(settings, migrated_database))

        evaluations = EvaluationRepository(migrated_database)
        assert evaluations.get(UUID(report.passing_evaluation_id)).gate.passed
        assert not evaluations.get(UUID(report.failing_evaluation_id)).gate.passed
        route = DeliveryRepository(migrated_database).get_for_agent(
            "knowledge-agent", DeliveryEnvironment.PRODUCTION
        )
        assert route.allocation.candidate_weight_basis_points == 500
        canary = CanaryRepository(migrated_database).get(UUID(report.canary_rollout_id))
        assert canary.progress.state is CanaryState.FIVE_PERCENT
        incident = IncidentRepository(migrated_database).get(UUID(report.incident_id))
        assert incident.status.value == "detected"
        assert len(IncidentEvidenceRepository(migrated_database).list_evidence(incident.id)) == 3
        denials = GovernanceAuditRepository(migrated_database).list_events(
            outcome=GovernanceAuditOutcome.DENY
        )
        assert len(denials) == 1
        assert denials[0].target == "admin.delete"
        assert report.fixture_notice.startswith("Synthetic local demo evidence")

        reset_demo(settings, migrated_database)
        repeated = asyncio.run(seed_demo(settings, migrated_database))
        assert repeated.registered_agents == 3
        assert len(IncidentRepository(migrated_database).list_incidents()) == 1
    finally:
        reset_demo(settings, migrated_database)
