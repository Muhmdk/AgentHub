"""PostgreSQL coverage for atomic, idempotent traffic routes."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from agents.knowledge.agent import KnowledgeAgent
from agents.shared.corpus import create_retail_retriever
from packages.contracts.delivery import (
    CreateTrafficRouteRequest,
    DeliveryEnvironment,
    ReplaceTrafficRouteRequest,
)
from packages.contracts.evaluation import EvaluationRunReport
from packages.contracts.manifest import AgentManifest
from packages.contracts.release import (
    CreateCandidateRequest,
    PolicyAttestation,
    PromoteReleaseRequest,
    ReleaseState,
    SecurityAttestation,
)
from packages.delivery.repository import (
    DeliveryBlockedError,
    DeliveryConflictError,
    DeliveryNotFoundError,
    DeliveryRepository,
)
from packages.evaluation.catalog import EvaluationCatalog
from packages.evaluation.repository import EvaluationRepository
from packages.evaluation.runner import EvaluationRunner
from packages.registry.database import Database
from packages.registry.repository import RegistryRepository
from packages.release.repository import ReleaseRepository
from packages.release.service import ReleaseService

ROOT = Path(__file__).parents[2]
DIGEST = f"sha256:{'d' * 64}"


def _evaluation(database: Database) -> EvaluationRunReport:
    manifest = AgentManifest.model_validate_json(
        (ROOT / "data/manifests/knowledge-agent-v1.json").read_text()
    )
    registered = RegistryRepository(database).register(
        manifest,
        actor="delivery-test",
        correlation_id=f"delivery-registration-{uuid4()}",
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


def _candidate(database: Database, key: str) -> UUID:
    report = _evaluation(database)
    service = ReleaseService(
        RegistryRepository(database),
        EvaluationRepository(database),
        ReleaseRepository(database),
    )
    result = service.create_candidate(
        CreateCandidateRequest(
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
                decision_id="delivery-policy",
                decision_version="1.0.0",
                passed=True,
                reasons=[],
            ),
            actor="delivery-workflow",
        )
    )
    return result.release.id


def _transition(
    repository: ReleaseRepository,
    release_id: UUID,
    target: ReleaseState,
    revision: int,
    key: str,
) -> None:
    repository.transition(
        release_id,
        PromoteReleaseRequest(
            target_state=target,
            actor="delivery-approver",
            reason=f"Make release eligible for {target.value}",
            expected_revision=revision,
            idempotency_key=key,
        ),
    )


def _eligible_releases(database: Database) -> tuple[UUID, UUID]:
    stable_id = _candidate(database, "delivery-stable-candidate")
    candidate_id = _candidate(database, "delivery-canary-candidate")
    releases = ReleaseRepository(database)
    _transition(releases, stable_id, ReleaseState.APPROVED, 1, "delivery-stable-approved")
    _transition(releases, stable_id, ReleaseState.STAGED, 2, "delivery-stable-staged")
    _transition(releases, stable_id, ReleaseState.PRODUCTION, 3, "delivery-stable-production")
    _transition(releases, candidate_id, ReleaseState.APPROVED, 1, "delivery-new-approved")
    _transition(releases, candidate_id, ReleaseState.STAGED, 2, "delivery-new-staged")
    return stable_id, candidate_id


def _create_request(stable_id: UUID, candidate_id: UUID) -> CreateTrafficRouteRequest:
    return CreateTrafficRouteRequest(
        idempotency_key="production-route-create",
        agent_name="knowledge-agent",
        environment=DeliveryEnvironment.PRODUCTION,
        stable_release_id=stable_id,
        candidate_release_id=candidate_id,
        candidate_weight_basis_points=0,
        actor="delivery-operator",
        reason="Initialize a shadow-only production candidate",
    )


@pytest.mark.integration
def test_delivery_migration_created_route_tables(registry_database: Database) -> None:
    tables = set(inspect(registry_database.engine).get_table_names())
    assert {"traffic_routes", "traffic_route_events"} <= tables


@pytest.mark.integration
def test_route_creation_is_idempotent_and_preserves_immutable_targets(
    registry_database: Database,
) -> None:
    stable_id, candidate_id = _eligible_releases(registry_database)
    repository = DeliveryRepository(registry_database)
    request = _create_request(stable_id, candidate_id)

    first = repository.create(request)
    replay = repository.create(request)
    fetched = repository.get_for_agent("knowledge-agent", DeliveryEnvironment.PRODUCTION)
    events = repository.events(first.route.id)

    assert first.created is True
    assert replay.created is False
    assert replay.route == first.route
    assert fetched == first.route
    assert repository.list_routes("knowledge-agent") == [first.route]
    assert first.route.allocation.stable.release_id == stable_id
    assert first.route.allocation.candidate is not None
    assert first.route.allocation.candidate.release_id == candidate_id
    assert first.route.allocation.stable.provenance_hash
    assert [(event.event_type, event.new_revision) for event in events] == [("route_created", 1)]


@pytest.mark.integration
def test_atomic_replace_is_revision_guarded_idempotent_and_audited(
    registry_database: Database,
) -> None:
    stable_id, candidate_id = _eligible_releases(registry_database)
    repository = DeliveryRepository(registry_database)
    created = repository.create(_create_request(stable_id, candidate_id)).route
    change = ReplaceTrafficRouteRequest(
        idempotency_key="production-route-weight-5",
        expected_revision=1,
        stable_release_id=stable_id,
        candidate_release_id=candidate_id,
        candidate_weight_basis_points=500,
        actor="delivery-operator",
        reason="Begin the five percent canary cohort",
    )

    changed = repository.replace(created.id, change)
    replay = repository.replace(created.id, change)

    assert changed.revision == 2
    assert changed.allocation.candidate_weight_basis_points == 500
    assert replay == changed
    events = repository.events(created.id)
    assert [event.new_revision for event in events] == [1, 2]
    assert events[1].previous_allocation == created.allocation
    assert events[1].new_allocation == changed.allocation

    with pytest.raises(DeliveryConflictError, match="revision conflict"):
        repository.replace(
            created.id,
            change.model_copy(
                update={
                    "idempotency_key": "production-route-stale",
                    "candidate_weight_basis_points": 2_500,
                }
            ),
        )


@pytest.mark.integration
def test_concurrent_route_retries_commit_once_and_return_the_same_revision(
    registry_database: Database,
) -> None:
    stable_id, candidate_id = _eligible_releases(registry_database)
    repository = DeliveryRepository(registry_database)
    route = repository.create(_create_request(stable_id, candidate_id)).route
    change = ReplaceTrafficRouteRequest(
        idempotency_key="concurrent-route-retry",
        expected_revision=route.revision,
        stable_release_id=stable_id,
        candidate_release_id=candidate_id,
        candidate_weight_basis_points=500,
        actor="delivery-operator",
        reason="Apply one concurrent route mutation",
    )
    barrier = Barrier(2)

    def replace() -> int:
        barrier.wait()
        return repository.replace(route.id, change).revision

    with ThreadPoolExecutor(max_workers=2) as executor:
        revisions = list(executor.map(lambda _: replace(), range(2)))

    assert revisions == [2, 2]
    assert repository.get(route.id).allocation.candidate_weight_basis_points == 500
    assert [event.new_revision for event in repository.events(route.id)] == [1, 2]


@pytest.mark.integration
def test_concurrent_route_changes_allow_exactly_one_revision_winner(
    registry_database: Database,
) -> None:
    stable_id, candidate_id = _eligible_releases(registry_database)
    repository = DeliveryRepository(registry_database)
    route = repository.create(_create_request(stable_id, candidate_id)).route
    barrier = Barrier(2)

    def replace(weight: int) -> int | DeliveryConflictError:
        request = ReplaceTrafficRouteRequest(
            idempotency_key=f"concurrent-route-{weight}",
            expected_revision=route.revision,
            stable_release_id=stable_id,
            candidate_release_id=candidate_id,
            candidate_weight_basis_points=weight,
            actor="delivery-operator",
            reason=f"Compete to set candidate weight to {weight}",
        )
        barrier.wait()
        try:
            return repository.replace(route.id, request).allocation.candidate_weight_basis_points
        except DeliveryConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(replace, (500, 2_500)))

    winners = [outcome for outcome in outcomes if isinstance(outcome, int)]
    conflicts = [outcome for outcome in outcomes if isinstance(outcome, DeliveryConflictError)]
    assert len(winners) == 1
    assert len(conflicts) == 1
    assert "revision conflict" in str(conflicts[0])
    assert repository.get(route.id).allocation.candidate_weight_basis_points == winners[0]
    assert [event.new_revision for event in repository.events(route.id)] == [1, 2]


@pytest.mark.integration
def test_conflicting_route_identity_and_ineligible_release_are_rejected(
    registry_database: Database,
) -> None:
    stable_id, candidate_id = _eligible_releases(registry_database)
    repository = DeliveryRepository(registry_database)
    request = _create_request(stable_id, candidate_id)
    repository.create(request)

    with pytest.raises(DeliveryConflictError, match="existing route"):
        repository.create(request.model_copy(update={"idempotency_key": "different-route-key"}))

    evaluated_id = _candidate(registry_database, "delivery-ineligible-candidate")
    with pytest.raises(DeliveryBlockedError, match="not eligible"):
        repository.create(
            CreateTrafficRouteRequest(
                idempotency_key="staging-route-ineligible",
                agent_name="knowledge-agent",
                environment=DeliveryEnvironment.STAGING,
                stable_release_id=evaluated_id,
                actor="delivery-operator",
                reason="Attempt to route an unapproved release",
            )
        )

    with pytest.raises(DeliveryNotFoundError, match="Referenced release"):
        repository.create(
            CreateTrafficRouteRequest(
                idempotency_key="staging-route-missing",
                agent_name="knowledge-agent",
                environment=DeliveryEnvironment.STAGING,
                stable_release_id=uuid4(),
                actor="delivery-operator",
                reason="Attempt to route a missing release",
            )
        )


@pytest.mark.integration
def test_database_protects_route_identity_and_append_only_events(
    registry_database: Database,
) -> None:
    stable_id, candidate_id = _eligible_releases(registry_database)
    route = (
        DeliveryRepository(registry_database).create(_create_request(stable_id, candidate_id)).route
    )

    with (
        pytest.raises(DBAPIError, match="traffic route identity is immutable"),
        registry_database.transaction() as session,
    ):
        session.execute(
            text("UPDATE traffic_routes SET agent_name = 'changed-agent' WHERE id = :id"),
            {"id": route.id},
        )
    with (
        pytest.raises(DBAPIError, match="traffic routes cannot be deleted"),
        registry_database.transaction() as session,
    ):
        session.execute(text("DELETE FROM traffic_routes WHERE id = :id"), {"id": route.id})
    with (
        pytest.raises(DBAPIError, match="traffic route events are append-only"),
        registry_database.transaction() as session,
    ):
        session.execute(
            text("DELETE FROM traffic_route_events WHERE route_id = :id"), {"id": route.id}
        )
