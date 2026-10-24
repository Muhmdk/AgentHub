"""Benchmark fixture expectations match the real deterministic gateway response."""

import pytest
from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.main import create_app
from packages.governance import InMemoryGovernanceAuditStore
from scripts.measure_agents import SCENARIOS


@pytest.mark.contract
def test_agent_benchmark_scenarios_match_real_gateway() -> None:
    app = create_app(
        Settings(
            environment="test",
            model_provider="fake",
            retrieval_provider="local",
            _env_file=None,
        ),
        governance_audit_store=InMemoryGovernanceAuditStore(),
    )
    with TestClient(app) as client:
        for agent, query, expected in SCENARIOS:
            response = client.post(
                f"/gateway/agents/{agent}/invoke",
                json={"query": query, "seed": 6},
                headers={"X-AgentHub-Identity": "local/benchmark"},
            )
            assert response.status_code == 200, agent
            body = response.json()
            assert expected.casefold() in body["answer"].casefold(), agent
            assert body["citations"], agent
