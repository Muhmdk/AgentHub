"""Sticky, deterministic weighted selection for stable and candidate traffic."""

import hashlib

from packages.contracts.delivery import RouteDecision, RouteLane, TrafficRoute


class DeterministicRouter:
    """Assign a stable request or subject key to one of 10,000 route buckets."""

    _HASH_NAMESPACE = "agenthub.delivery.route.v1"

    @classmethod
    def select(cls, route: TrafficRoute, assignment_key: str) -> RouteDecision:
        """Select a target without randomness or storage of the caller's raw key."""
        if not assignment_key or not assignment_key.strip():
            raise ValueError("A non-empty stable request or subject key is required")
        if len(assignment_key) > 500:
            raise ValueError("The routing key must not exceed 500 characters")

        digest = hashlib.sha256(
            f"{cls._HASH_NAMESPACE}:{route.id}:{assignment_key}".encode()
        ).hexdigest()
        bucket = int(digest[:16], 16) % 10_000
        allocation = route.allocation
        candidate_selected = (
            allocation.candidate is not None and bucket < allocation.candidate_weight_basis_points
        )
        if candidate_selected:
            lane = RouteLane.CANDIDATE
            target = allocation.candidate
            reason = (
                f"Candidate selected because cohort bucket {bucket} is below "
                f"weight {allocation.candidate_weight_basis_points}"
            )
        else:
            lane = RouteLane.STABLE
            target = allocation.stable
            reason = (
                f"Stable selected because cohort bucket {bucket} is outside "
                f"candidate weight {allocation.candidate_weight_basis_points}"
            )

        return RouteDecision(
            route_id=route.id,
            route_revision=route.revision,
            assignment_hash=digest,
            cohort_basis_point=bucket,
            lane=lane,
            target=target,
            reason=reason,
        )
