"""Contract validation for progressive-delivery traffic routes."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.contracts.delivery import (
    CreateTrafficRouteRequest,
    DeliveryEnvironment,
    RouteTarget,
    TrafficAllocation,
)


def _target() -> RouteTarget:
    return RouteTarget(
        release_id=uuid4(),
        agent_version_id=uuid4(),
        agent_version="1.2.3",
        provenance_hash="a" * 64,
    )


def test_allocation_requires_candidate_for_nonzero_weight() -> None:
    with pytest.raises(ValidationError, match="Candidate weight requires"):
        TrafficAllocation(stable=_target(), candidate_weight_basis_points=500)


def test_allocation_requires_distinct_release_targets() -> None:
    target = _target()

    with pytest.raises(ValidationError, match="must differ"):
        TrafficAllocation(stable=target, candidate=target)


@pytest.mark.parametrize("weight", [-1, 10_001])
def test_candidate_weight_is_bounded_to_basis_points(weight: int) -> None:
    with pytest.raises(ValidationError):
        TrafficAllocation(
            stable=_target(),
            candidate=_target(),
            candidate_weight_basis_points=weight,
        )


def test_create_request_rejects_candidate_weight_without_release() -> None:
    with pytest.raises(ValidationError, match="Candidate weight requires"):
        CreateTrafficRouteRequest(
            idempotency_key="route-create-1",
            agent_name="knowledge-agent",
            environment=DeliveryEnvironment.PRODUCTION,
            stable_release_id=uuid4(),
            candidate_weight_basis_points=500,
            actor="delivery-operator",
            reason="Initialize production traffic",
        )
