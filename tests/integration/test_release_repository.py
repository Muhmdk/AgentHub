"""PostgreSQL coverage for immutable and idempotent candidate releases."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from agents.knowledge.agent import KnowledgeAgent
from agents.shared.corpus import create_retail_retriever
from apps.api.config import Settings
from apps.api.main import create_app
from packages.contracts.evaluation import EvaluationRunReport
from packages.contracts.manifest import AgentManifest
from packages.contracts.release import (
    CreateCandidateRequest,
    PolicyAttestation,
    PromoteReleaseRequest,
    ReleaseState,
    SecurityAttestation,
)
from packages.evaluation.catalog import EvaluationCatalog
from packages.evaluation.repository import EvaluationRepository
from packages.evaluation.runner import EvaluationRunner
from packages.registry.database import Database
from packages.registry.repository import RegistryRepository
from packages.release.repository import (
    ReleaseBlockedError,
    ReleaseConflictError,
    ReleaseRepository,
)
from packages.release.service import ReleaseService

ROOT = Path(__file__).parents[2]
DIGEST = f"sha256:{'d' * 64}"


def _evaluation(database: Database) -> EvaluationRunReport:
    manifest = AgentManifest.model_validate_json(
        (ROOT / "data/manifests/knowledge-agent-v1.json").read_text()
    )
    registered = RegistryRepository(database).register(
        manifest,
        actor="release-test",
        correlation_id="release-registration",
    )
    suite, dataset, gate = EvaluationCatalog().resolve("knowledge-agent-suite")
    retriever, corpus, _ = create_retail_retriever()
    report = asyncio.run(
        EvaluationRunner().run(
            target=KnowledgeAgent(retriever=retriever, corpus=corpus),
            agent_version_id=registered.agent_version.id,
            agent_version=registered.agent_version.version,
            manifest_hash=registered.agent_version.manifest_hash,
            suite=suite,
            dataset=dataset,
            gate_profile=gate,
            environment="integration",
            provider_settings={"provider": "fake", "model": "deterministic-v1"},
        )
    )
    return EvaluationRepository(database).save(report)


def _request(
    report: EvaluationRunReport, *, key: str = "candidate-workflow-1"
) -> CreateCandidateRequest:
    return CreateCandidateRequest(
        idempotency_key=key,
        agent_name=report.agent_name,
        agent_version=report.agent_version,
        evaluation_run_id=report.run_id,
        sbom_digest=DIGEST,
        build_provenance_digest=f"sha256:{'e' * 64}",
        security=SecurityAttestation(
            dependency_scan_passed=True,
            image_scan_passed=True,
            maximum_severity="none",
            scanner="trivy",
            scanner_version="1.0.0",
        ),
        policy=PolicyAttestation(
            decision_id="release-policy",
            decision_version="1.0.0",
            passed=True,
            reasons=[],
        ),
        actor="release-workflow",
    )


def _service(database: Database) -> ReleaseService:
    return ReleaseService(
        RegistryRepository(database),
        EvaluationRepository(database),
        ReleaseRepository(database),
    )


@pytest.mark.integration
def test_release_migration_created_lineage_tables(registry_database: Database) -> None:
    tables = set(inspect(registry_database.engine).get_table_names())
    assert {"releases", "release_events"} <= tables


@pytest.mark.integration
def test_candidate_is_idempotent_and_lineage_is_complete(registry_database: Database) -> None:
    report = _evaluation(registry_database)
    service = _service(registry_database)
    request = _request(report)

    first = service.create_candidate(request)
    replay = service.create_candidate(request)
    stored = ReleaseRepository(registry_database).get(first.release.id)

    assert first.created is True
    assert replay.created is False
    assert replay.release.id == first.release.id
    assert stored.provenance.evaluation_artifact_hash == report.artifact_hash
    assert stored.provenance.manifest_hash == report.manifest_hash
    assert stored.provenance.image_reference.endswith(stored.provenance.image_digest)
    assert len(stored.provenance_hash) == 64
    assert len(ReleaseRepository(registry_database).events(stored.id)) == 1


@pytest.mark.integration
def test_promotion_is_ordered_and_retry_safe(registry_database: Database) -> None:
    release = (
        _service(registry_database)
        .create_candidate(_request(_evaluation(registry_database)))
        .release
    )
    repository = ReleaseRepository(registry_database)

    approved_change = PromoteReleaseRequest(
        target_state=ReleaseState.APPROVED,
        actor="release-approver",
        reason="All technical and policy gates passed",
        expected_revision=1,
        idempotency_key="promote-approved-1",
    )
    approved = repository.transition(release.id, approved_change)
    staged = repository.transition(
        release.id,
        PromoteReleaseRequest(
            target_state=ReleaseState.STAGED,
            actor="release-workflow",
            reason="Protected staging environment approved",
            expected_revision=2,
            idempotency_key="promote-staged-1",
        ),
    )
    production = repository.transition(
        release.id,
        PromoteReleaseRequest(
            target_state=ReleaseState.PRODUCTION,
            actor="release-approver",
            reason="Protected production environment approved",
            expected_revision=3,
            idempotency_key="promote-production-1",
        ),
    )
    replay = repository.transition(release.id, approved_change)

    assert approved.state == ReleaseState.APPROVED
    assert staged.state == ReleaseState.STAGED
    assert production.state == ReleaseState.PRODUCTION
    assert replay == production
    notes = _service(registry_database).notes(release.id)
    assert notes.image_reference == release.provenance.image_reference
    assert [event.new_state for event in repository.events(release.id)] == [
        ReleaseState.EVALUATED,
        ReleaseState.APPROVED,
        ReleaseState.STAGED,
        ReleaseState.PRODUCTION,
    ]


@pytest.mark.integration
def test_failed_security_gate_blocks_approval(registry_database: Database) -> None:
    report = _evaluation(registry_database)
    request = _request(report).model_copy(
        update={
            "security": _request(report).security.model_copy(
                update={"image_scan_passed": False, "maximum_severity": "high"}
            )
        }
    )
    release = _service(registry_database).create_candidate(request).release

    with pytest.raises(ReleaseBlockedError, match="image_scan_failed"):
        ReleaseRepository(registry_database).transition(
            release.id,
            PromoteReleaseRequest(
                target_state=ReleaseState.APPROVED,
                actor="release-approver",
                reason="Attempt promotion for block test",
                expected_revision=1,
                idempotency_key="blocked-approval-1",
            ),
        )


@pytest.mark.integration
def test_conflicting_retry_and_lineage_tampering_are_rejected(
    registry_database: Database,
) -> None:
    report = _evaluation(registry_database)
    service = _service(registry_database)
    request = _request(report)
    release = service.create_candidate(request).release
    changed = request.model_copy(
        update={"security": request.security.model_copy(update={"scanner_version": "2.0.0"})}
    )

    with pytest.raises(ReleaseConflictError, match="immutable release lineage"):
        service.create_candidate(changed)
    with (
        pytest.raises(DBAPIError, match="release lineage is immutable"),
        registry_database.transaction() as session,
    ):
        session.execute(
            text("UPDATE releases SET provenance_hash = :hash WHERE id = :id"),
            {"hash": "f" * 64, "id": release.id},
        )
    with (
        pytest.raises(DBAPIError, match="release events are immutable"),
        registry_database.transaction() as session,
    ):
        session.execute(
            text("DELETE FROM release_events WHERE release_id = :id"), {"id": release.id}
        )


@pytest.mark.contract
@pytest.mark.integration
def test_release_api_exposes_candidate_provenance_events_and_notes(
    registry_database: Database,
) -> None:
    report = _evaluation(registry_database)
    app = create_app(
        Settings(
            environment="test",
            database_url=registry_database.engine.url.render_as_string(hide_password=False),
            _env_file=None,
        ),
        database=registry_database,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        created = client.post(
            "/releases/candidates",
            json=_request(report, key="candidate-api-1").model_dump(mode="json"),
            headers={"X-Correlation-ID": "release-api"},
        )
        release_id = created.json()["release"]["id"]
        listed = client.get("/releases")
        fetched = client.get(f"/releases/{release_id}")
        events = client.get(f"/releases/{release_id}/events")
        notes = client.get(f"/releases/{release_id}/notes")

    assert created.status_code == 200
    assert created.headers["X-Correlation-ID"] == "release-api"
    assert created.json()["release"]["gate"]["passed"] is True
    assert listed.json() == [fetched.json()]
    assert events.json()[0]["event_type"] == "candidate_created"
    assert notes.json()["image_reference"] == fetched.json()["provenance"]["image_reference"]
