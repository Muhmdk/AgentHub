"""Known-good rollback command validation and execution coverage."""

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from packages.contracts.delivery import (
    CanaryActionRequest,
    CanaryProgress,
    CanaryRollout,
    CanaryState,
    DeliveryEnvironment,
    ReplaceTrafficRouteRequest,
    RouteTarget,
    TrafficAllocation,
    TrafficRoute,
)
from packages.contracts.incident import (
    Incident,
    IncidentSeverity,
    IncidentStatus,
    PrepareRollbackRequest,
)
from packages.contracts.release import (
    PolicyAttestation,
    ReleaseGateDecision,
    ReleaseProvenance,
    ReleaseState,
    ReleaseView,
    SecurityAttestation,
)
from packages.delivery.canary_repository import CanaryStore
from packages.delivery.repository import DeliveryStore
from packages.incidents.rollback import (
    KnownGoodRollbackExecutor,
    KnownGoodRollbackPlanner,
    RollbackValidationError,
)

NOW = datetime(2026, 9, 11, 5, 0, tzinfo=UTC)


def _release(release_id: UUID, target: RouteTarget) -> ReleaseView:
    return ReleaseView.model_construct(
        id=release_id,
        agent_version_id=target.agent_version_id,
        agent_name="shopping-agent",
        agent_version=target.agent_version,
        state=ReleaseState.PRODUCTION,
        state_revision=4,
        idempotency_key="rollback-target-release",
        provenance=ReleaseProvenance(
            schema_version="agenthub.dev/release-provenance/v1",
            source_repository="https://example.invalid/agenthub",
            source_sha="d" * 40,
            image_reference=f"registry.example/agent@sha256:{'e' * 64}",
            image_digest=f"sha256:{'e' * 64}",
            manifest_hash="f" * 64,
            sbom_digest=f"sha256:{'1' * 64}",
            build_provenance_digest=f"sha256:{'2' * 64}",
            evaluation_run_id=uuid4(),
            evaluation_artifact_hash="3" * 64,
            policy_decision_id="rollback-policy",
            policy_decision_version="1.0.0",
        ),
        provenance_hash=target.provenance_hash,
        security=SecurityAttestation(
            dependency_scan_passed=True,
            image_scan_passed=True,
            maximum_severity="none",
            scanner="test",
            scanner_version="1",
        ),
        policy=PolicyAttestation(
            decision_id="rollback-policy",
            decision_version="1.0.0",
            passed=True,
            reasons=[],
        ),
        gate=ReleaseGateDecision(
            passed=True,
            evaluation_passed=True,
            security_passed=True,
            policy_passed=True,
            reasons=[],
        ),
        created_by="release-controller",
        created_at=NOW,
        updated_at=NOW,
    )


def _context() -> tuple[Incident, TrafficRoute, CanaryRollout, ReleaseView]:
    stable = RouteTarget(
        release_id=uuid4(),
        agent_version_id=uuid4(),
        agent_version="1.0.0",
        provenance_hash="a" * 64,
    )
    candidate = RouteTarget(
        release_id=uuid4(),
        agent_version_id=uuid4(),
        agent_version="1.1.0",
        provenance_hash="b" * 64,
    )
    route = TrafficRoute(
        id=uuid4(),
        agent_name="shopping-agent",
        environment=DeliveryEnvironment.PRODUCTION,
        allocation=TrafficAllocation(
            stable=stable,
            candidate=candidate,
            candidate_weight_basis_points=2_500,
        ),
        revision=3,
        created_by="delivery-controller",
        created_at=NOW,
        updated_by="delivery-controller",
        updated_at=NOW,
    )
    canary = CanaryRollout(
        id=uuid4(),
        route_id=route.id,
        stable_release_id=stable.release_id,
        candidate_release_id=candidate.release_id,
        progress=CanaryProgress(state=CanaryState.TWENTY_FIVE_PERCENT),
        revision=3,
        route_revision=route.revision,
        created_by="delivery-controller",
        created_at=NOW,
        updated_by="delivery-controller",
        updated_at=NOW,
    )
    incident = Incident(
        id=uuid4(),
        agent_name="shopping-agent",
        environment=DeliveryEnvironment.PRODUCTION,
        title="Shopping Agent candidate latency regression",
        status=IncidentStatus.DETECTED,
        severity=IncidentSeverity.CRITICAL,
        release_id=candidate.release_id,
        route_id=route.id,
        canary_rollout_id=canary.id,
        revision=1,
        trigger_count=1,
        created_by="incident-controller",
        detected_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    return incident, route, canary, _release(stable.release_id, stable)


def _request(
    incident: Incident,
    route: TrafficRoute,
    target: ReleaseView,
    canary: CanaryRollout | None,
) -> PrepareRollbackRequest:
    return PrepareRollbackRequest(
        idempotency_key="incident-rollback-command",
        incident_id=incident.id,
        route_id=route.id,
        expected_route_revision=route.revision,
        canary_rollout_id=canary.id if canary is not None else None,
        expected_canary_revision=canary.revision if canary is not None else None,
        target_release_id=target.id,
        target_provenance_hash=target.provenance_hash,
        actor="rollback-controller",
        reason="Restore traffic to the immutable known-good release",
        requested_at=NOW,
    )


@pytest.mark.unit
def test_canary_rollback_command_preserves_lineage_and_sets_zero_traffic() -> None:
    incident, route, canary, target = _context()

    command = KnownGoodRollbackPlanner.prepare(
        incident,
        route,
        target,
        _request(incident, route, target, canary),
        canary=canary,
    )

    assert command.target_allocation.stable.release_id == target.id
    assert command.target_allocation.candidate == route.allocation.candidate
    assert command.target_allocation.candidate_weight_basis_points == 0
    assert len(command.command_hash) == 64


class _RouteStore:
    def __init__(self, route: TrafficRoute) -> None:
        self.route = route
        self.replacements: list[ReplaceTrafficRouteRequest] = []

    def get(self, _route_id: UUID) -> TrafficRoute:
        return self.route

    def replace(self, _route_id: UUID, request: ReplaceTrafficRouteRequest) -> TrafficRoute:
        self.replacements.append(request)
        return self.route


class _CanaryStore:
    def __init__(self, canary: CanaryRollout) -> None:
        self.canary = canary
        self.actions: list[CanaryActionRequest] = []

    def transition(self, _canary_id: UUID, request: CanaryActionRequest) -> CanaryRollout:
        self.actions.append(request)
        return self.canary


@pytest.mark.unit
def test_executor_uses_audited_canary_abort_boundary() -> None:
    incident, route, canary, target = _context()
    command = KnownGoodRollbackPlanner.prepare(
        incident,
        route,
        target,
        _request(incident, route, target, canary),
        canary=canary,
    )
    rolled_route = route.model_copy(update={"allocation": command.target_allocation, "revision": 4})
    rolled_canary = canary.model_copy(
        update={"progress": CanaryProgress(state=CanaryState.ROLLED_BACK), "revision": 4}
    )
    routes = _RouteStore(rolled_route)
    canaries = _CanaryStore(rolled_canary)

    result = KnownGoodRollbackExecutor(
        cast(DeliveryStore, routes), cast(CanaryStore, canaries)
    ).execute(command, executed_at=NOW)

    assert result.route == rolled_route
    assert result.canary == rolled_canary
    assert routes.replacements == []
    assert len(canaries.actions) == 1
    action = canaries.actions[0]
    assert action.action.value == "abort"


@pytest.mark.unit
def test_stable_rollback_clears_candidate_through_atomic_route_replace() -> None:
    incident, route, original_canary, _ = _context()
    incident = incident.model_copy(update={"canary_rollout_id": None})
    old_target = RouteTarget(
        release_id=uuid4(),
        agent_version_id=uuid4(),
        agent_version="0.9.0",
        provenance_hash="c" * 64,
    )
    target = _release(old_target.release_id, old_target)
    request = _request(incident, route, target, None)
    command = KnownGoodRollbackPlanner.prepare(incident, route, target, request)
    rolled_route = route.model_copy(update={"allocation": command.target_allocation, "revision": 4})
    routes = _RouteStore(rolled_route)
    canaries = _CanaryStore(original_canary)

    result = KnownGoodRollbackExecutor(
        cast(DeliveryStore, routes), cast(CanaryStore, canaries)
    ).execute(command, executed_at=NOW)

    assert result.route.allocation.stable.release_id == target.id
    assert result.route.allocation.candidate is None
    assert len(routes.replacements) == 1
    assert canaries.actions == []


@pytest.mark.unit
def test_planner_rejects_mutable_or_mismatched_targets() -> None:
    incident, route, canary, target = _context()
    request = _request(incident, route, target, canary)

    with pytest.raises(RollbackValidationError, match="provenance"):
        KnownGoodRollbackPlanner.prepare(
            incident,
            route,
            target,
            request.model_copy(update={"target_provenance_hash": "f" * 64}),
            canary=canary,
        )
    with pytest.raises(RollbackValidationError, match="known-good"):
        KnownGoodRollbackPlanner.prepare(
            incident,
            route,
            target.model_copy(update={"state": ReleaseState.STAGED}),
            request,
            canary=canary,
        )
    with pytest.raises(RollbackValidationError, match="route identity"):
        KnownGoodRollbackPlanner.prepare(
            incident,
            route,
            target,
            request.model_copy(update={"route_id": uuid4()}),
            canary=canary,
        )
