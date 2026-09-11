"""End-to-end progressive delivery, degradation, and abort coverage."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import text

from packages.contracts.delivery import (
    CanaryAction,
    CanaryActionRequest,
    CanaryState,
    CreateCanaryRequest,
    ShadowComparison,
)
from packages.delivery.canary_repository import CanaryRepository
from packages.delivery.repository import DeliveryBlockedError, DeliveryRepository
from packages.registry.database import Database
from tests.integration.test_canary_repository import _metric, healthy_comparison
from tests.integration.test_delivery_repository import _create_request, _eligible_releases

ROOT = Path(__file__).parents[2]


@pytest.fixture
def delivery_database() -> Iterator[Database]:
    database_url = os.getenv("AGENTHUB_DATABASE_URL")
    if database_url is None:
        pytest.skip("Progressive delivery E2E requires AGENTHUB_DATABASE_URL")
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


def _action(
    *,
    action: CanaryAction,
    rollout_revision: int,
    route_revision: int,
    key: str,
    comparison: ShadowComparison | None = None,
    telemetry_healthy: bool = False,
) -> CanaryActionRequest:
    return CanaryActionRequest(
        idempotency_key=key,
        action=action,
        expected_revision=rollout_revision,
        expected_route_revision=route_revision,
        actor="delivery-controller",
        reason=f"Exercise the {action.value} delivery path",
        comparison=comparison,
        telemetry_healthy=telemetry_healthy,
    )


@pytest.mark.e2e
@pytest.mark.integration
def test_canary_progresses_to_twenty_five_percent_then_aborts_to_stable(
    delivery_database: Database,
) -> None:
    stable_id, candidate_id = _eligible_releases(delivery_database)
    routes = DeliveryRepository(delivery_database)
    route = routes.create(_create_request(stable_id, candidate_id)).route
    canaries = CanaryRepository(delivery_database)
    rollout = canaries.create(
        CreateCanaryRequest(
            idempotency_key="e2e-canary-create",
            route_id=route.id,
            expected_route_revision=route.revision,
            actor="delivery-controller",
            reason="Begin the end-to-end rollout",
        )
    ).rollout

    comparison = healthy_comparison(
        route_id=route.id,
        route_revision=route.revision,
        stable_id=stable_id,
        candidate_id=candidate_id,
    )
    rollout = canaries.transition(
        rollout.id,
        _action(
            action=CanaryAction.START,
            rollout_revision=rollout.revision,
            route_revision=route.revision,
            key="e2e-canary-start",
            comparison=comparison,
            telemetry_healthy=True,
        ),
    )
    assert rollout.progress.state is CanaryState.FIVE_PERCENT
    assert routes.get(route.id).allocation.candidate_weight_basis_points == 500

    comparison = healthy_comparison(
        route_id=route.id,
        route_revision=rollout.route_revision,
        stable_id=stable_id,
        candidate_id=candidate_id,
    )
    rollout = canaries.transition(
        rollout.id,
        _action(
            action=CanaryAction.PROMOTE,
            rollout_revision=rollout.revision,
            route_revision=rollout.route_revision,
            key="e2e-canary-promote-25",
            comparison=comparison,
            telemetry_healthy=True,
        ),
    )
    assert rollout.progress.state is CanaryState.TWENTY_FIVE_PERCENT
    route_at_twenty_five = routes.get(route.id)
    assert route_at_twenty_five.allocation.candidate_weight_basis_points == 2_500

    degraded = healthy_comparison(
        route_id=route.id,
        route_revision=rollout.route_revision,
        stable_id=stable_id,
        candidate_id=candidate_id,
    ).model_copy(update={"safety": _metric(-0.05)})
    with pytest.raises(DeliveryBlockedError, match="Safety regression"):
        canaries.transition(
            rollout.id,
            _action(
                action=CanaryAction.PROMOTE,
                rollout_revision=rollout.revision,
                route_revision=rollout.route_revision,
                key="e2e-canary-block-degraded",
                comparison=degraded,
                telemetry_healthy=True,
            ),
        )
    assert canaries.get(rollout.id) == rollout
    assert routes.get(route.id) == route_at_twenty_five

    rollout = canaries.transition(
        rollout.id,
        _action(
            action=CanaryAction.PAUSE,
            rollout_revision=rollout.revision,
            route_revision=rollout.route_revision,
            key="e2e-canary-pause",
        ),
    )
    assert rollout.progress.state is CanaryState.PAUSED
    rollout = canaries.transition(
        rollout.id,
        _action(
            action=CanaryAction.RESUME,
            rollout_revision=rollout.revision,
            route_revision=rollout.route_revision,
            key="e2e-canary-resume",
        ),
    )
    assert rollout.progress.state is CanaryState.TWENTY_FIVE_PERCENT
    rollout = canaries.transition(
        rollout.id,
        _action(
            action=CanaryAction.ABORT,
            rollout_revision=rollout.revision,
            route_revision=rollout.route_revision,
            key="e2e-canary-abort",
        ),
    )

    rolled_back_route = routes.get(route.id)
    assert rollout.progress.state is CanaryState.ROLLED_BACK
    assert rolled_back_route.allocation.stable.release_id == stable_id
    assert rolled_back_route.allocation.candidate is not None
    assert rolled_back_route.allocation.candidate.release_id == candidate_id
    assert rolled_back_route.allocation.candidate_weight_basis_points == 0
    assert [event.action for event in canaries.events(rollout.id)] == [
        None,
        CanaryAction.START,
        CanaryAction.PROMOTE,
        CanaryAction.PAUSE,
        CanaryAction.RESUME,
        CanaryAction.ABORT,
    ]


@pytest.mark.e2e
@pytest.mark.integration
def test_missing_telemetry_blocks_canary_without_mutating_delivery_state(
    delivery_database: Database,
) -> None:
    stable_id, candidate_id = _eligible_releases(delivery_database)
    routes = DeliveryRepository(delivery_database)
    route = routes.create(_create_request(stable_id, candidate_id)).route
    canaries = CanaryRepository(delivery_database)
    rollout = canaries.create(
        CreateCanaryRequest(
            idempotency_key="e2e-missing-telemetry-create",
            route_id=route.id,
            expected_route_revision=route.revision,
            actor="delivery-controller",
            reason="Prove missing telemetry fails closed",
        )
    ).rollout

    with pytest.raises(DeliveryBlockedError, match="Paired telemetry is missing"):
        canaries.transition(
            rollout.id,
            _action(
                action=CanaryAction.START,
                rollout_revision=rollout.revision,
                route_revision=route.revision,
                key="e2e-missing-telemetry-start",
                telemetry_healthy=False,
            ),
        )

    assert canaries.get(rollout.id) == rollout
    assert routes.get(route.id) == route
    assert len(canaries.events(rollout.id)) == 1
    assert len(routes.events(route.id)) == 1
