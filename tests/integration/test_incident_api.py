"""Incident intake, evidence, investigation, and console API coverage."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.main import create_app
from packages.registry.database import Database

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
