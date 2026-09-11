"""Known-good rollback planning and audited control-plane execution."""

import hashlib
import json
from datetime import datetime

from packages.contracts.delivery import (
    CanaryAction,
    CanaryActionRequest,
    CanaryRollout,
    CanaryState,
    ReplaceTrafficRouteRequest,
    TrafficAllocation,
    TrafficRoute,
)
from packages.contracts.incident import (
    Incident,
    PrepareRollbackRequest,
    RollbackCommand,
    RollbackExecution,
)
from packages.contracts.release import ReleaseState, ReleaseView
from packages.delivery.canary_repository import CanaryStore
from packages.delivery.repository import DeliveryStore


class RollbackValidationError(RuntimeError):
    """A rollback command does not identify an immutable known-good target."""


class KnownGoodRollbackPlanner:
    """Validate incident, route, canary, and release lineage before actuation."""

    @staticmethod
    def prepare(
        incident: Incident,
        route: TrafficRoute,
        target: ReleaseView,
        request: PrepareRollbackRequest,
        *,
        canary: CanaryRollout | None = None,
    ) -> RollbackCommand:
        if incident.id != request.incident_id:
            raise RollbackValidationError("Rollback incident identity does not match")
        if route.id != request.route_id or route.revision != request.expected_route_revision:
            raise RollbackValidationError("Rollback route identity or revision does not match")
        if incident.route_id is not None and incident.route_id != route.id:
            raise RollbackValidationError("Incident is linked to a different traffic route")
        if incident.agent_name != route.agent_name or incident.environment is not route.environment:
            raise RollbackValidationError("Incident scope does not match the traffic route")
        if (
            incident.canary_rollout_id is not None
            and incident.canary_rollout_id != request.canary_rollout_id
        ):
            raise RollbackValidationError("Incident is linked to a different canary rollout")
        if target.id != request.target_release_id:
            raise RollbackValidationError("Rollback target release identity does not match")
        if target.provenance_hash != request.target_provenance_hash:
            raise RollbackValidationError("Rollback target provenance does not match")
        if target.agent_name != route.agent_name:
            raise RollbackValidationError("Rollback target belongs to a different agent")
        if target.state is not ReleaseState.PRODUCTION or not target.gate.passed:
            raise RollbackValidationError("Rollback target is not a known-good production release")

        route_target = route.allocation.stable
        if canary is not None:
            if (
                request.canary_rollout_id != canary.id
                or request.expected_canary_revision != canary.revision
                or canary.route_id != route.id
            ):
                raise RollbackValidationError("Rollback canary identity or revision does not match")
            if canary.progress.state in {CanaryState.COMPLETED, CanaryState.ROLLED_BACK}:
                raise RollbackValidationError("Rollback canary is already terminal")
            if (
                canary.stable_release_id != target.id
                or route_target.release_id != target.id
                or canary.candidate_release_id
                != (
                    route.allocation.candidate.release_id
                    if route.allocation.candidate is not None
                    else None
                )
            ):
                raise RollbackValidationError("Rollback canary lineage does not match the route")
            target_allocation = TrafficAllocation(
                stable=route_target,
                candidate=route.allocation.candidate,
                candidate_weight_basis_points=0,
            )
        else:
            if request.canary_rollout_id is not None:
                raise RollbackValidationError("Rollback canary record was not supplied")
            target_route = route_target.model_copy(
                update={
                    "release_id": target.id,
                    "agent_version_id": target.agent_version_id,
                    "agent_version": target.agent_version,
                    "provenance_hash": target.provenance_hash,
                }
            )
            target_allocation = TrafficAllocation(stable=target_route)
        return RollbackCommand(
            command_hash=_command_hash(
                request,
                route.agent_name,
                route.environment.value,
                route.allocation,
                target_allocation,
            ),
            request=request,
            agent_name=route.agent_name,
            environment=route.environment,
            previous_allocation=route.allocation,
            target_allocation=target_allocation,
        )


class KnownGoodRollbackExecutor:
    """Execute only a prevalidated command through audited delivery stores."""

    def __init__(self, routes: DeliveryStore, canaries: CanaryStore) -> None:
        self._routes = routes
        self._canaries = canaries

    def execute(self, command: RollbackCommand, *, executed_at: datetime) -> RollbackExecution:
        if executed_at.tzinfo is None or executed_at.utcoffset() is None:
            raise ValueError("Rollback execution timestamps must be timezone-aware")
        request = command.request
        expected_hash = _command_hash(
            request,
            command.agent_name,
            command.environment.value,
            command.previous_allocation,
            command.target_allocation,
        )
        if expected_hash != command.command_hash:
            raise RollbackValidationError("Rollback command hash does not match its content")
        canary: CanaryRollout | None = None
        if request.canary_rollout_id is not None:
            assert request.expected_canary_revision is not None
            canary = self._canaries.transition(
                request.canary_rollout_id,
                CanaryActionRequest(
                    idempotency_key=request.idempotency_key,
                    action=CanaryAction.ABORT,
                    expected_revision=request.expected_canary_revision,
                    expected_route_revision=request.expected_route_revision,
                    actor=request.actor,
                    reason=request.reason,
                ),
            )
            route = self._routes.get(request.route_id)
        else:
            route = self._routes.replace(
                request.route_id,
                ReplaceTrafficRouteRequest(
                    idempotency_key=request.idempotency_key,
                    expected_revision=request.expected_route_revision,
                    stable_release_id=command.target_allocation.stable.release_id,
                    candidate_release_id=None,
                    candidate_weight_basis_points=0,
                    actor=request.actor,
                    reason=request.reason,
                ),
            )
        if route.allocation != command.target_allocation:
            raise RollbackValidationError("Executed route does not match the rollback command")
        return RollbackExecution(
            command=command,
            route=route,
            canary=canary,
            executed_at=executed_at,
        )


def _command_hash(
    request: PrepareRollbackRequest,
    agent_name: str,
    environment: str,
    previous_allocation: TrafficAllocation,
    target_allocation: TrafficAllocation,
) -> str:
    payload = {
        "request": request.model_dump(mode="json"),
        "agent_name": agent_name,
        "environment": environment,
        "previous_allocation": previous_allocation.model_dump(mode="json"),
        "target_allocation": target_allocation.model_dump(mode="json"),
    }
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()
