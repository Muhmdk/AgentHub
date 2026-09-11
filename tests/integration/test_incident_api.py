"""Incident intake, evidence, investigation, and console API coverage."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.main import create_app
from packages.contracts.delivery import (
    CanaryAction,
    CanaryActionRequest,
    CreateCanaryRequest,
    DeliveryEnvironment,
)
from packages.delivery.canary_repository import CanaryRepository
from packages.delivery.repository import DeliveryRepository
from packages.incidents.faults import TopKRegressionFault
from packages.registry.database import Database
from tests.integration.test_canary_repository import healthy_comparison
from tests.integration.test_delivery_repository import _create_request, _eligible_releases

NOW = datetime(2026, 9, 11, 8, tzinfo=UTC)


@pytest.fixture
def incident_client(registry_database: Database) -> Iterator[TestClient]:
    app = create_app(
        Settings(environment="test", _env_file=None),
        database=registry_database,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_incident_api_builds_source_cited_investigation(
    incident_client: TestClient,
) -> None:
    detected = incident_client.post(
        "/incidents/signals",
        json={
            "signal": {
                "idempotency_key": "incident-api-trigger",
                "trigger_type": "slo_burn",
                "severity": "critical",
                "agent_name": "knowledge-agent",
                "environment": "production",
                "signal_name": "slo.latency.burn_rate",
                "observed_value": 18,
                "threshold": 14.4,
                "observed_at": NOW.isoformat(),
                "source_ref": "telemetry://knowledge-agent/slo/latency",
                "summary": "Latency exhausted the production error budget",
            },
            "actor": "incident-api-test",
        },
    )
    assert detected.status_code == 200
    incident_id = detected.json()["result"]["incident"]["id"]

    evidence = [
        {
            "idempotency_key": "incident-api-config",
            "kind": "config_diff",
            "source_ref": "release://knowledge-agent/config-diff",
            "summary": "Retrieval top-k changed from 5 to 50",
            "occurred_at": (NOW - timedelta(minutes=10)).isoformat(),
            "subject_id": "knowledge-agent-config",
            "attributes": {"changes": {"spec.retrieval.top_k": {"before": 5, "after": 50}}},
        },
        {
            "idempotency_key": "incident-api-retrieval",
            "kind": "metric",
            "source_ref": "telemetry://knowledge-agent/retrieval-duration",
            "summary": "Retrieval latency increased fivefold",
            "occurred_at": (NOW - timedelta(minutes=1)).isoformat(),
            "subject_id": "retrieval.duration_ms",
            "attributes": {
                "baseline": 100,
                "current": 500,
                "delta": 400,
                "change_ratio": 4,
            },
        },
        {
            "idempotency_key": "incident-api-model",
            "kind": "metric",
            "source_ref": "telemetry://knowledge-agent/model-duration",
            "summary": "Model latency remained stable",
            "occurred_at": (NOW - timedelta(minutes=1)).isoformat(),
            "subject_id": "model.duration_ms",
            "attributes": {
                "baseline": 200,
                "current": 202,
                "delta": 2,
                "change_ratio": 0.01,
            },
        },
    ]
    for item in evidence:
        response = incident_client.post(
            f"/incidents/{incident_id}/evidence",
            json=item,
            headers={"X-AgentHub-Actor": "evidence-collector"},
        )
        assert response.status_code == 200

    listing = incident_client.get("/incidents?agent_name=knowledge-agent")
    triggers = incident_client.get(f"/incidents/{incident_id}/triggers")
    stored = incident_client.get(f"/incidents/{incident_id}/evidence")
    timeline = incident_client.get(f"/incidents/{incident_id}/timeline")
    investigation = incident_client.get(f"/incidents/{incident_id}/investigation")

    assert listing.status_code == 200 and len(listing.json()) == 1
    assert triggers.status_code == 200 and len(triggers.json()) == 1
    assert stored.status_code == 200 and len(stored.json()) == 3
    assert timeline.status_code == 200 and len(timeline.json()["entries"]) == 4
    assert investigation.status_code == 200
    analysis = investigation.json()["analysis"]
    assert analysis["probable_cause"]["kind"] == "known_signature"
    assert "retrieval fan-out" in analysis["probable_cause"]["statement"]
    assert all(claim["citations"] for claim in analysis["findings"])


def test_incident_console_and_not_found_contract(incident_client: TestClient) -> None:
    console = incident_client.get("/incidents-console")
    missing = incident_client.get(
        f"/incidents/{uuid4()}", headers={"X-Correlation-ID": "incident-missing"}
    )

    assert console.status_code == 200
    assert "Incident investigation" in console.text
    assert 'fetch("/incidents")' in console.text
    assert "innerHTML" not in console.text
    assert missing.status_code == 404
    assert missing.json()["error"] == {
        "code": "incident_not_found",
        "message": "Incident was not found",
        "correlation_id": "incident-missing",
        "details": [],
    }


def test_incident_rollback_api_derives_policy_facts_server_side(
    incident_client: TestClient,
    registry_database: Database,
) -> None:
    stable_id, candidate_id = _eligible_releases(registry_database)
    routes = DeliveryRepository(registry_database)
    route = routes.create(_create_request(stable_id, candidate_id)).route
    canaries = CanaryRepository(registry_database)
    canary = canaries.create(
        CreateCanaryRequest(
            idempotency_key="incident-api-rollback-canary",
            route_id=route.id,
            expected_route_revision=route.revision,
            actor="delivery-controller",
            reason="Create API rollback test canary",
        )
    ).rollout
    canary = canaries.transition(
        canary.id,
        CanaryActionRequest(
            idempotency_key="incident-api-rollback-start",
            action=CanaryAction.START,
            expected_revision=canary.revision,
            expected_route_revision=route.revision,
            actor="delivery-controller",
            reason="Start API rollback test canary",
            comparison=healthy_comparison(
                route_id=route.id,
                route_revision=route.revision,
                stable_id=stable_id,
                candidate_id=candidate_id,
            ),
            telemetry_healthy=True,
        ),
    )
    route = routes.get(route.id)
    scenario = TopKRegressionFault().build(
        agent_name="knowledge-agent",
        environment=DeliveryEnvironment.PRODUCTION,
        release_id=candidate_id,
        route_id=route.id,
        canary_rollout_id=canary.id,
        observed_at=datetime.now(UTC),
    )
    detected = incident_client.post(
        "/incidents/signals",
        json={
            "signal": scenario.signal.model_dump(mode="json"),
            "actor": "incident-controller",
        },
    ).json()
    incident = detected["result"]["incident"]
    for item in scenario.evidence:
        assert (
            incident_client.post(
                f"/incidents/{incident['id']}/evidence",
                json=item.model_dump(mode="json"),
                headers={"X-AgentHub-Actor": "evidence-collector"},
            ).status_code
            == 200
        )
    intent = {
        "idempotency_key": "incident-api-policy-rollback",
        "expected_incident_revision": incident["revision"],
        "actor": "operator-console",
        "reason": "Restore the persisted known-good stable release",
        "human_approved": False,
    }
    injected_fact = incident_client.post(
        f"/incidents/{incident['id']}/rollback",
        json={**intent, "evidence_count": 999, "guardrail_breached": True},
    )
    rollback = incident_client.post(
        f"/incidents/{incident['id']}/rollback",
        json=intent,
    )

    assert injected_fact.status_code == 422
    assert rollback.status_code == 200
    assert rollback.json()["operation"]["mode"] == "automatic"
    assert rollback.json()["operation"]["status"] == "executed"
    assert routes.get(route.id).allocation.candidate_weight_basis_points == 0
