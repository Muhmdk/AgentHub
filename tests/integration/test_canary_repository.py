"""PostgreSQL coverage for durable canary orchestration."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from apps.api.config import Settings
from apps.api.main import create_app
from packages.contracts.delivery import (
    CanaryAction,
    CanaryActionRequest,
    CanaryState,
    CreateCanaryRequest,
    DeliveryEnvironment,
    MetricDelta,
    ShadowComparison,
)
from packages.delivery.canary_repository import CanaryRepository
from packages.delivery.repository import DeliveryRepository
from packages.registry.database import Database
from tests.integration.test_delivery_repository import _create_request, _eligible_releases


def _metric(
    delta: float,
    *,
    unit: str = "score",
    lower_is_better: bool = False,
) -> MetricDelta:
    return MetricDelta(
        samples=100,
        stable_mean=0.8,
        candidate_mean=0.8 + delta,
        delta=delta,
        confidence_low=delta,
        confidence_high=delta,
        unit=unit,
        lower_is_better=lower_is_better,
    )


def healthy_comparison(
    *,
    route_id: UUID,
    route_revision: int,
    stable_id: UUID,
    candidate_id: UUID,
) -> ShadowComparison:
    now = datetime.now(UTC)
    return ShadowComparison(
        route_id=route_id,
        route_revisions=[route_revision],
        stable_release_id=stable_id,
        candidate_release_id=candidate_id,
        sample_count=100,
        successful_sample_count=100,
        window_start=now - timedelta(minutes=10),
        window_end=now - timedelta(seconds=5),
        quality=_metric(0.01),
        safety=_metric(0.01),
        latency=_metric(10, unit="milliseconds", lower_is_better=True),
        error_rate=_metric(0, unit="rate", lower_is_better=True),
        cost=_metric(0.001, unit="usd", lower_is_better=True),
    )


@pytest.mark.integration
def test_canary_migration_created_rollout_tables(registry_database: Database) -> None:
    tables = set(inspect(registry_database.engine).get_table_names())
    assert {"canary_rollouts", "canary_events"} <= tables


@pytest.mark.integration
def test_canary_create_and_start_are_idempotent_atomic_and_audited(
    registry_database: Database,
) -> None:
    stable_id, candidate_id = _eligible_releases(registry_database)
    routes = DeliveryRepository(registry_database)
    route = routes.create(_create_request(stable_id, candidate_id)).route
    canaries = CanaryRepository(registry_database)
    create = CreateCanaryRequest(
        idempotency_key="canary-create-base",
        route_id=route.id,
        expected_route_revision=route.revision,
        actor="delivery-operator",
        reason="Track the production candidate rollout",
    )

    first = canaries.create(create)
    replay = canaries.create(create)
    comparison = healthy_comparison(
        route_id=route.id,
        route_revision=route.revision,
        stable_id=stable_id,
        candidate_id=candidate_id,
    )
    action = CanaryActionRequest(
        idempotency_key="canary-start-base",
        action=CanaryAction.START,
        expected_revision=1,
        expected_route_revision=1,
        actor="delivery-operator",
        reason="Shadow evidence passed the five percent gate",
        comparison=comparison,
        telemetry_healthy=True,
    )
    started = canaries.transition(first.rollout.id, action)
    action_replay = canaries.transition(first.rollout.id, action)
    updated_route = routes.get(route.id)

    assert first.created is True
    assert replay.created is False
    assert replay.rollout == first.rollout
    assert started.progress.state is CanaryState.FIVE_PERCENT
    assert action_replay == started
    assert updated_route.revision == 2
    assert updated_route.allocation.stable.release_id == stable_id
    assert updated_route.allocation.candidate is not None
    assert updated_route.allocation.candidate.release_id == candidate_id
    assert updated_route.allocation.candidate_weight_basis_points == 500
    assert [event.event_type for event in canaries.events(started.id)] == [
        "canary_created",
        "canary_action",
    ]
    assert routes.get_for_agent("knowledge-agent", DeliveryEnvironment.PRODUCTION) == updated_route


@pytest.mark.contract
@pytest.mark.integration
def test_delivery_api_exposes_routes_canaries_events_and_overview(
    registry_database: Database,
) -> None:
    stable_id, candidate_id = _eligible_releases(registry_database)
    app = create_app(
        Settings(environment="test", _env_file=None),
        database=registry_database,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        route_response = client.post(
            "/delivery/routes",
            json=_create_request(stable_id, candidate_id)
            .model_copy(update={"idempotency_key": "canary-api-route"})
            .model_dump(mode="json"),
        )
        route = route_response.json()["route"]
        canary_response = client.post(
            "/delivery/canaries",
            json={
                "idempotency_key": "canary-api-create",
                "route_id": route["id"],
                "expected_route_revision": route["revision"],
                "actor": "delivery-api-test",
                "reason": "Create rollout through the delivery API",
            },
        )
        rollout = canary_response.json()["rollout"]
        overview = client.get("/delivery/overview")
        route_events = client.get(f"/delivery/routes/{route['id']}/events")
        canary_events = client.get(f"/delivery/canaries/{rollout['id']}/events")

    assert route_response.status_code == 200
    assert canary_response.status_code == 200
    assert overview.status_code == 200
    assert overview.json()["routes"][0]["id"] == route["id"]
    assert overview.json()["canaries"][0]["id"] == rollout["id"]
    assert route_events.json()[0]["event_type"] == "route_created"
    assert canary_events.json()[0]["event_type"] == "canary_created"
