"""API and console contracts backed by the migrated PostgreSQL registry."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.main import create_app
from packages.registry.database import Database

ROOT = Path(__file__).parents[2]


def manifest_payload(name: str = "inventory") -> dict[str, object]:
    path = ROOT / "data" / "manifests" / f"{name}-agent-v1.json"
    payload: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return payload


@pytest.fixture
def registry_client(registry_database: Database) -> Iterator[TestClient]:
    app = create_app(
        Settings(
            environment="test",
            database_url=registry_database.engine.url.render_as_string(hide_password=False),
            _env_file=None,
        ),
        database=registry_database,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.contract
@pytest.mark.integration
def test_register_list_get_history_and_audit_contracts(registry_client: TestClient) -> None:
    registered = registry_client.post(
        "/registry/agents",
        json=manifest_payload(),
        headers={
            "X-AgentHub-Actor": "api-user",
            "X-Correlation-ID": "api-registration",
        },
    )
    repeated = registry_client.post(
        "/registry/agents",
        json=manifest_payload(),
        headers={"X-AgentHub-Actor": "api-user"},
    )

    assert registered.status_code == 200
    assert registered.json()["created"] is True
    assert registered.json()["agent_version"]["lifecycle_state"] == "draft"
    assert repeated.status_code == 200
    assert repeated.json()["created"] is False
    assert repeated.json()["agent_version"]["id"] == registered.json()["agent_version"]["id"]

    inventory = registry_client.get("/registry/agents").json()
    agent = registry_client.get("/registry/agents/inventory-agent").json()
    history = registry_client.get("/registry/agents/inventory-agent/versions").json()
    version = registry_client.get("/registry/agents/inventory-agent/versions/1.0.0").json()
    audit = registry_client.get("/registry/agents/inventory-agent/versions/1.0.0/audit").json()

    assert len(inventory) == 1
    assert agent["owner"] == "retail-ai-team"
    assert history == [version]
    assert (
        version["manifest"]["spec"]["source"]["commit_sha"]
        == "a88fb630a9e5aa377feee41fbb542be66ddba2ac"
    )
    assert audit[0]["actor"] == "api-user"
    assert audit[0]["correlation_id"] == "api-registration"
    assert audit[0]["manifest_hash"] == version["manifest_hash"]


@pytest.mark.contract
@pytest.mark.integration
def test_transition_and_conflict_error_contracts(registry_client: TestClient) -> None:
    registry_client.post(
        "/registry/agents",
        json=manifest_payload("shopping"),
        headers={"X-AgentHub-Actor": "api-user"},
    )
    transition = registry_client.post(
        "/registry/agents/shopping-agent/versions/1.0.0/transitions",
        json={
            "target_state": "registered",
            "actor": "release-manager",
            "reason": "Manifest approved",
            "expected_revision": 1,
        },
        headers={"X-Correlation-ID": "api-transition"},
    )
    illegal = registry_client.post(
        "/registry/agents/shopping-agent/versions/1.0.0/transitions",
        json={
            "target_state": "production",
            "actor": "release-manager",
            "expected_revision": 2,
        },
        headers={"X-Correlation-ID": "api-illegal"},
    )

    assert transition.status_code == 200
    assert transition.json()["lifecycle_state"] == "registered"
    assert transition.json()["state_revision"] == 2
    assert illegal.status_code == 409
    assert illegal.json() == {
        "error": {
            "code": "registry_conflict",
            "message": "Transition from registered to production is not permitted",
            "correlation_id": "api-illegal",
            "details": [],
        }
    }


@pytest.mark.contract
@pytest.mark.integration
def test_conflicting_manifest_and_missing_agent_use_stable_errors(
    registry_client: TestClient,
) -> None:
    payload = manifest_payload("knowledge")
    registry_client.post(
        "/registry/agents",
        json=payload,
        headers={"X-AgentHub-Actor": "api-user"},
    )
    spec = payload["spec"]
    assert isinstance(spec, dict)
    source = spec["source"]
    assert isinstance(source, dict)
    source["commit_sha"] = "d" * 40
    conflict = registry_client.post(
        "/registry/agents",
        json=payload,
        headers={
            "X-AgentHub-Actor": "api-user",
            "X-Correlation-ID": "api-conflict",
        },
    )
    missing = registry_client.get(
        "/registry/agents/missing-agent",
        headers={"X-Correlation-ID": "api-missing"},
    )

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "registry_conflict"
    assert "d" * 40 not in conflict.text
    assert missing.status_code == 404
    assert missing.json()["error"] == {
        "code": "registry_not_found",
        "message": "Agent was not found",
        "correlation_id": "api-missing",
        "details": [],
    }


@pytest.mark.contract
@pytest.mark.integration
def test_registry_console_is_backed_by_registry_api(registry_client: TestClient) -> None:
    response = registry_client.get("/registry")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Agent registry" in response.text
    assert 'fetch("/registry/agents")' in response.text
    assert "innerHTML" not in response.text


@pytest.mark.contract
@pytest.mark.integration
def test_evaluation_run_comparison_and_console_contracts(
    registry_client: TestClient,
) -> None:
    registry_client.post(
        "/registry/agents",
        json=manifest_payload("inventory"),
        headers={"X-AgentHub-Actor": "evaluation-api-test"},
    )
    successful = registry_client.post(
        "/evaluations/runs",
        json={
            "agent_name": "inventory-agent",
            "agent_version": "1.0.0",
            "suite_id": "inventory-agent-suite",
            "environment": "integration",
        },
    )
    regressed = registry_client.post(
        "/evaluations/runs",
        json={
            "agent_name": "inventory-agent",
            "agent_version": "1.0.0",
            "suite_id": "inventory-agent-suite",
            "candidate_profile": "regressed",
            "baseline_run_id": successful.json()["run_id"],
            "environment": "integration",
        },
    )

    assert successful.status_code == 200
    assert successful.json()["gate"]["passed"] is True
    assert regressed.status_code == 200
    assert regressed.json()["gate"]["passed"] is False
    assert any(
        not reason["passed"] and reason["code"].endswith("failed")
        for reason in regressed.json()["gate"]["reasons"]
    )

    run_id = regressed.json()["run_id"]
    listing = registry_client.get("/evaluations/runs?agent_name=inventory-agent")
    report = registry_client.get(f"/evaluations/runs/{run_id}")
    comparison = registry_client.get(f"/evaluations/runs/{run_id}/comparison")
    console = registry_client.get("/evaluations")

    assert listing.status_code == 200
    assert len(listing.json()) == 2
    assert report.json()["artifact_hash"] == regressed.json()["artifact_hash"]
    assert comparison.json() == regressed.json()["gate"]
    assert console.status_code == 200
    assert "Evaluation runs" in console.text
    assert 'fetch("/evaluations/runs")' in console.text
    assert "innerHTML" not in console.text
