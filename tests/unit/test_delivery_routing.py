"""Deterministic and distribution tests for weighted delivery routing."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from packages.contracts.delivery import (
    DeliveryEnvironment,
    RouteLane,
    RouteTarget,
    TrafficAllocation,
    TrafficRoute,
)
from packages.delivery.routing import DeterministicRouter

ROUTE_ID = UUID("a88eea69-a632-4fd7-a2ec-49690f9be064")


def _target(release_number: int, version: str) -> RouteTarget:
    return RouteTarget(
        release_id=UUID(int=release_number),
        agent_version_id=UUID(int=release_number + 10),
        agent_version=version,
        provenance_hash=f"{release_number:x}" * 64,
    )


def _route(weight: int, *, revision: int = 1, candidate: bool = True) -> TrafficRoute:
    now = datetime(2026, 9, 10, tzinfo=UTC)
    return TrafficRoute(
        id=ROUTE_ID,
        agent_name="knowledge-agent",
        environment=DeliveryEnvironment.PRODUCTION,
        allocation=TrafficAllocation(
            stable=_target(1, "1.0.0"),
            candidate=_target(2, "2.0.0") if candidate else None,
            candidate_weight_basis_points=weight,
        ),
        revision=revision,
        created_by="delivery-operator",
        created_at=now,
        updated_by="delivery-operator",
        updated_at=now,
    )


def test_same_key_is_sticky_and_raw_key_is_not_retained() -> None:
    route = _route(2_500)

    first = DeterministicRouter.select(route, "subject-481")
    replay = DeterministicRouter.select(route, "subject-481")

    assert replay == first
    assert len(first.assignment_hash) == 64
    assert "subject-481" not in first.model_dump_json()
    assert first.target in {route.allocation.stable, route.allocation.candidate}


def test_bucket_is_stable_across_route_revisions_and_cohort_growth_is_monotonic() -> None:
    initial = DeterministicRouter.select(_route(500), "customer-9001")
    expanded = DeterministicRouter.select(_route(2_500, revision=2), "customer-9001")

    assert expanded.cohort_basis_point == initial.cohort_basis_point
    assert expanded.assignment_hash == initial.assignment_hash
    if initial.lane is RouteLane.CANDIDATE:
        assert expanded.lane is RouteLane.CANDIDATE


def test_candidate_distribution_tracks_basis_point_weight() -> None:
    route = _route(2_500)
    decisions = [DeterministicRouter.select(route, f"subject-{index}") for index in range(20_000)]
    candidate_count = sum(decision.lane is RouteLane.CANDIDATE for decision in decisions)

    assert candidate_count / len(decisions) == pytest.approx(0.25, abs=0.015)


def test_zero_weight_or_missing_candidate_always_selects_stable() -> None:
    zero_weight = _route(0)
    stable_only = _route(0, candidate=False)

    for key in ("request-a", "request-b", "request-c"):
        assert DeterministicRouter.select(zero_weight, key).lane is RouteLane.STABLE
        assert DeterministicRouter.select(stable_only, key).lane is RouteLane.STABLE


def test_full_weight_always_selects_candidate() -> None:
    route = _route(10_000)

    for index in range(100):
        assert DeterministicRouter.select(route, f"request-{index}").lane is RouteLane.CANDIDATE


@pytest.mark.parametrize("key", ["", "   ", "x" * 501])
def test_invalid_assignment_keys_are_rejected(key: str) -> None:
    with pytest.raises(ValueError, match=r"key|required"):
        DeterministicRouter.select(_route(500), key)
