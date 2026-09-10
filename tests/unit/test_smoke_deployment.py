"""Tests for the environment-neutral post-deployment smoke flow."""

from collections.abc import Mapping

import pytest

from packages.contracts.runtime import JsonValue
from scripts.smoke_deployment import JsonTransport, SmokeFailure, run_smoke


class FixtureTransport(JsonTransport):
    def __init__(
        self,
        *,
        model: str = "azure-openai/gpt-test",
        evaluation_gate_passed: bool = True,
    ) -> None:
        self.model = model
        self.evaluation_gate_passed = evaluation_gate_passed
        self.calls: list[tuple[str, str]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, JsonValue] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JsonValue:
        self.calls.append((method, path))
        responses: dict[tuple[str, str], JsonValue] = {
            ("GET", "/health/live"): {"status": "ok", "service": "agenthub-api"},
            ("GET", "/health/ready"): {"status": "ready", "service": "agenthub-api"},
            ("GET", "/version"): {
                "service": "agenthub-api",
                "version": "0.3.0",
                "environment": "staging",
            },
            ("POST", "/registry/agents"): {"created": True},
            ("GET", "/registry/agents/inventory-agent"): {"name": "inventory-agent"},
            ("POST", "/agents/inventory/invoke"): {
                "answer": "Queen Street may run low.",
                "model": self.model,
                "citations": [{"source_id": "inventory:1", "title": "Inventory"}],
                "tool_calls": [{"tool_name": "inventory.read"}],
            },
            ("POST", "/agents/knowledge/invoke"): {
                "answer": "Returns are accepted within 30 days.",
                "model": self.model,
                "citations": [{"source_id": "returns:0", "title": "Return policy"}],
                "retrieval": {"result_ids": ["returns:0"]},
            },
            ("POST", "/evaluations/runs"): {
                "run_id": "00000000-0000-0000-0000-000000000010",
                "gate": {"passed": self.evaluation_gate_passed},
                "case_results": [{"status": "completed"}, {"status": "completed"}],
            },
        }
        return responses[(method, path)]


@pytest.mark.unit
def test_smoke_covers_health_registry_agents_and_evaluation() -> None:
    transport = FixtureTransport()
    report = run_smoke(
        transport,
        {"schema_version": "agenthub.dev/v1"},
        expected_model_prefix="azure-openai/",
        environment="azure-smoke",
    )

    assert report.service_version == "0.3.0"
    assert report.environment == "staging"
    assert report.registry_created
    assert report.evaluation_gate_passed
    assert transport.calls == [
        ("GET", "/health/live"),
        ("GET", "/health/ready"),
        ("GET", "/version"),
        ("POST", "/registry/agents"),
        ("GET", "/registry/agents/inventory-agent"),
        ("POST", "/agents/inventory/invoke"),
        ("POST", "/agents/knowledge/invoke"),
        ("POST", "/evaluations/runs"),
    ]


@pytest.mark.unit
def test_smoke_rejects_unexpected_model_provider() -> None:
    with pytest.raises(SmokeFailure, match="unexpected model"):
        run_smoke(
            FixtureTransport(model="fake/deterministic-v1"),
            {"schema_version": "agenthub.dev/v1"},
            expected_model_prefix="azure-openai/",
        )


@pytest.mark.unit
def test_smoke_rejects_failed_evaluation_gate() -> None:
    with pytest.raises(SmokeFailure, match="Evaluation gate did not pass"):
        run_smoke(
            FixtureTransport(evaluation_gate_passed=False),
            {"schema_version": "agenthub.dev/v1"},
        )
