"""Seeded public-surface proof from release evidence through verified recovery."""

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from apps.api.config import Settings
from apps.api.main import create_app
from packages.contracts.incident import RecoveryOutcome, RecoveryPolicy, RollbackStatus
from packages.delivery.repository import DeliveryRepository
from packages.incidents.faults import TopKRegressionFault
from packages.incidents.recovery import RollbackRecoveryVerifier
from packages.incidents.repository import IncidentRepository
from packages.incidents.rollback_repository import RollbackOperationRepository
from packages.registry.database import Database
from scripts.seed_demo import reset_demo, seed_demo

ROOT = Path(__file__).parents[2]


@pytest.fixture
def demo_lifecycle_database() -> Iterator[tuple[Database, Settings]]:
    database_url = os.getenv("AGENTHUB_DATABASE_URL")
    if database_url is None:
        pytest.skip("Seeded lifecycle E2E requires AGENTHUB_DATABASE_URL")
    alembic = Config(ROOT / "alembic.ini")
    alembic.set_main_option("sqlalchemy.url", database_url)
    alembic_command.upgrade(alembic, "head")
    database = Database(database_url)
    settings = Settings(environment="test", database_url=database_url, _env_file=None)
    reset_demo(settings, database)
    try:
        yield database, settings
    finally:
        reset_demo(settings, database)
        database.dispose()


@pytest.mark.e2e
@pytest.mark.integration
def test_seeded_demo_blocks_denies_rolls_back_and_verifies_recovery(
    demo_lifecycle_database: tuple[Database, Settings],
) -> None:
    database, settings = demo_lifecycle_database
    report = asyncio.run(seed_demo(settings, database))
    incident_id = UUID(report.incident_id)

    app = create_app(settings, database=database)
    with TestClient(app) as client:
        registry = client.get("/registry/agents")
        assert registry.status_code == 200
        assert {agent["name"] for agent in registry.json()} == {
            "inventory-agent",
            "knowledge-agent",
            "shopping-agent",
        }

        passing = client.get(f"/evaluations/runs/{report.passing_evaluation_id}")
        failing = client.get(f"/evaluations/runs/{report.failing_evaluation_id}")
        assert passing.status_code == 200 and passing.json()["gate"]["passed"] is True
        assert failing.status_code == 200 and failing.json()["gate"]["passed"] is False

        audit = client.get("/governance/audit", params={"outcome": "deny"})
        assert audit.status_code == 200
        assert [(event["outcome"], event["target"]) for event in audit.json()] == [
            ("deny", "admin.delete")
        ]

        route = client.get(f"/delivery/routes/{report.route_id}")
        canary = client.get(f"/delivery/canaries/{report.canary_rollout_id}")
        assert route.status_code == 200
        assert route.json()["allocation"]["candidate_weight_basis_points"] == 500
        assert canary.status_code == 200
        assert canary.json()["progress"]["state"] == "5_percent"

        for path, heading in {
            "/registry": "Agent registry",
            "/evaluations": "Evaluation runs",
            "/governance": "Policy command center",
            "/observability": "Fleet health",
            "/delivery": "Progressive delivery",
            "/incidents-console": "Incident investigation",
        }.items():
            page = client.get(path)
            assert page.status_code == 200
            assert heading in page.text

        investigation = client.get(f"/incidents/{incident_id}/investigation")
        assert investigation.status_code == 200
        view = investigation.json()
        assert view["analysis"]["probable_cause"] is not None
        assert len(view["timeline"]["entries"]) == 4
        assert all(
            claim["citations"]
            for claim in [
                view["analysis"]["probable_cause"],
                *view["analysis"]["findings"],
                *view["analysis"]["counter_evidence"],
            ]
        )

        rollback = client.post(
            f"/incidents/{incident_id}/rollback",
            json={
                "idempotency_key": "final-demo-e2e-rollback",
                "expected_incident_revision": view["incident"]["revision"],
                "actor": "operator-console",
                "reason": "Restore the persisted known-good release in the final lifecycle proof",
                "human_approved": True,
            },
        )
        assert rollback.status_code == 200
        assert rollback.json()["operation"]["status"] == "executed"

    persisted_route = DeliveryRepository(database).get(UUID(report.route_id))
    assert persisted_route.allocation.candidate_weight_basis_points == 0
    operations = RollbackOperationRepository(database)
    executed = operations.list_for_incident(incident_id)[0]
    assert executed.status is RollbackStatus.EXECUTED

    policy = RecoveryPolicy()
    verifier = RollbackRecoveryVerifier(operations)
    started_at = datetime.now(UTC)
    verifying = verifier.begin(executed, policy, started_at=started_at)
    assert verifying.verification_deadline is not None
    recovery, completed = verifier.verify(
        verifying,
        TopKRegressionFault.recovery_observation(window_start=started_at),
        policy,
        evaluated_at=verifying.verification_deadline,
    )

    assert recovery.outcome is RecoveryOutcome.RECOVERED
    assert completed.status is RollbackStatus.RECOVERED
    assert IncidentRepository(database).get(incident_id).status.value == "resolved"
    with database.transaction() as session:
        statuses = session.execute(
            text(
                "SELECT status FROM rollback_events WHERE operation_id = :operation_id "
                "ORDER BY occurred_at, id"
            ),
            {"operation_id": completed.id},
        ).scalars()
        assert list(statuses) == ["requested", "executed", "verifying", "recovered"]
