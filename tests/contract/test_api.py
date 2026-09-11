"""HTTP contract tests for the walking-skeleton API."""

import pytest
from fastapi import Query
from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.main import create_app
from packages.contracts.governance import PolicyDecision, PolicyInput, PolicyObligations
from packages.registry.database import Database

_GATEWAY_TOKEN = "gateway-contract-token-with-at-least-32-characters"


class AllowingPolicyEngine:
    async def decide(self, policy_input: PolicyInput) -> PolicyDecision:
        return PolicyDecision(
            schema_version="agenthub.dev/policy-decision/v1",
            allow=True,
            reasons=[f"{policy_input.action.kind}_allowed"],
            policy_bundle_version="contract.v1",
            obligations=PolicyObligations(audit=True),
        )


class DenyingPolicyEngine:
    async def decide(self, policy_input: PolicyInput) -> PolicyDecision:
        del policy_input
        return PolicyDecision(
            schema_version="agenthub.dev/policy-decision/v1",
            allow=False,
            reasons=["tool_not_declared"],
            policy_bundle_version="contract.v1",
            obligations=PolicyObligations(audit=True),
        )


class UnreadyDatabase(Database):
    def __init__(self) -> None:
        pass

    def ping(self) -> bool:
        return False

    def dispose(self) -> None:
        pass


@pytest.fixture
def client() -> TestClient:
    app = create_app(Settings(environment="test", version="0.1.0-test", _env_file=None))
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.contract
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/health/live", {"status": "ok", "service": "agenthub-api"}),
        ("/health/ready", {"status": "ready", "service": "agenthub-api"}),
        (
            "/version",
            {"service": "agenthub-api", "version": "0.1.0-test", "environment": "test"},
        ),
    ],
)
def test_service_endpoints_return_documented_contracts(
    client: TestClient, path: str, expected: dict[str, str]
) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.json() == expected
    assert response.headers["X-Correlation-ID"]


@pytest.mark.contract
def test_readiness_reports_unavailable_database_without_internal_details() -> None:
    app = create_app(Settings(environment="test", _env_file=None), database=UnreadyDatabase())

    with TestClient(app, raise_server_exceptions=False) as local_client:
        response = local_client.get(
            "/health/ready", headers={"X-Correlation-ID": "database-unready"}
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "http_error",
            "message": "Database is not ready",
            "correlation_id": "database-unready",
            "details": [],
        }
    }


@pytest.mark.contract
def test_client_correlation_id_is_propagated(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Correlation-ID": "demo-request-7"})

    assert response.headers["X-Correlation-ID"] == "demo-request-7"


@pytest.mark.contract
def test_not_found_uses_structured_error_envelope(client: TestClient) -> None:
    response = client.get("/does-not-exist", headers={"X-Correlation-ID": "missing-route"})

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Not Found",
            "correlation_id": "missing-route",
            "details": [],
        }
    }


@pytest.mark.contract
def test_validation_errors_do_not_echo_submitted_values() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    @app.get("/validation-probe")
    async def validation_probe(limit: int = Query(ge=1, le=10)) -> dict[str, int]:
        return {"limit": limit}

    with TestClient(app, raise_server_exceptions=False) as local_client:
        response = local_client.get(
            "/validation-probe?limit=sensitive-invalid-value",
            headers={"X-Correlation-ID": "validation-case"},
        )

    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["correlation_id"] == "validation-case"
    assert body["error"]["details"][0]["location"] == "query.limit"
    assert "sensitive-invalid-value" not in response.text


@pytest.mark.contract
def test_unexpected_errors_are_safe(capsys: pytest.CaptureFixture[str]) -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    @app.get("/failure-probe")
    async def failure_probe() -> None:
        raise RuntimeError("sensitive internal detail")

    with TestClient(app, raise_server_exceptions=False) as local_client:
        response = local_client.get("/failure-probe", headers={"X-Correlation-ID": "failure-case"})

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred",
            "correlation_id": "failure-case",
            "details": [],
        }
    }
    assert "sensitive internal detail" not in response.text
    assert "sensitive internal detail" not in capsys.readouterr().err


@pytest.mark.contract
def test_inventory_invocation_returns_answer_and_evidence(client: TestClient) -> None:
    response = client.post(
        "/agents/inventory/invoke",
        json={
            "query": "Which Toronto stores may run low on snow shovels this weekend?",
            "seed": 11,
            "as_of": "2026-09-08",
        },
        headers={"X-Correlation-ID": "inventory-contract"},
    )

    body = response.json()
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "inventory-contract"
    assert "Queen Street may run low" in body["answer"]
    assert body["model"] == "fake/deterministic-v1"
    assert [call["tool_name"] for call in body["tool_calls"]] == [
        "inventory.read",
        "sales.read",
        "promotions.read",
        "weather.read",
    ]
    assert len(body["citations"]) == 6


@pytest.mark.contract
def test_gateway_requires_an_explicit_caller_identity(client: TestClient) -> None:
    response = client.post(
        "/gateway/agents/inventory-agent/invoke",
        json={"query": "Which Toronto stores may run low on snow shovels this weekend?"},
        headers={"X-Correlation-ID": "gateway-no-identity"},
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {
        "error": {
            "code": "authentication_required",
            "message": "Gateway authentication required",
            "correlation_id": "gateway-no-identity",
            "details": [],
        }
    }


@pytest.mark.contract
def test_gateway_invokes_agent_for_explicit_local_identity(client: TestClient) -> None:
    response = client.post(
        "/gateway/agents/knowledge-agent/invoke",
        json={"query": "Can I return an unopened product after 20 days?", "seed": 4},
        headers={
            "X-AgentHub-Identity": "local/contract-test",
            "X-Correlation-ID": "gateway-local",
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"].startswith("Unopened products may be returned within 30 days")
    assert response.json()["retrieval"]["corpus_version"] == "v1"


@pytest.mark.contract
def test_gateway_rejects_unknown_agent_after_authentication(client: TestClient) -> None:
    response = client.post(
        "/gateway/agents/unknown-agent/invoke",
        json={"query": "Do something"},
        headers={"X-AgentHub-Identity": "local/contract-test"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Agent is not available"


@pytest.mark.contract
def test_runtime_policy_deny_returns_stable_gateway_error() -> None:
    app = create_app(
        Settings(environment="test", _env_file=None),
        policy_engine=DenyingPolicyEngine(),
    )

    with TestClient(app, raise_server_exceptions=False) as denied_client:
        response = denied_client.post(
            "/gateway/agents/inventory-agent/invoke",
            json={"query": "Which Toronto stores may run low on snow shovels this weekend?"},
            headers={
                "X-AgentHub-Identity": "local/contract-test",
                "X-Correlation-ID": "policy-deny-contract",
            },
        )

    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "policy_denied",
            "message": "Action denied by policy",
            "correlation_id": "policy-deny-contract",
            "details": [],
        }
    }


@pytest.mark.contract
def test_production_exposes_only_authenticated_gateway_invocation() -> None:
    app = create_app(
        Settings(
            environment="production",
            gateway_service_tokens={"service/runtime": _GATEWAY_TOKEN},
            policy_engine_url="http://127.0.0.1:8181/v1/data/agenthub/authz/decision",
            _env_file=None,
        ),
        policy_engine=AllowingPolicyEngine(),
    )

    with TestClient(app, raise_server_exceptions=False) as production_client:
        direct = production_client.post(
            "/agents/inventory/invoke",
            json={"query": "Which Toronto stores may run low on snow shovels this weekend?"},
        )
        denied = production_client.post(
            "/gateway/agents/inventory-agent/invoke",
            json={"query": "Which Toronto stores may run low on snow shovels this weekend?"},
            headers={"X-AgentHub-Identity": "local/contract-test"},
        )
        allowed = production_client.post(
            "/gateway/agents/inventory-agent/invoke",
            json={"query": "Which Toronto stores may run low on snow shovels this weekend?"},
            headers={
                "Authorization": f"Bearer {_GATEWAY_TOKEN}",
                "X-AgentHub-Identity": "service/runtime",
            },
        )

    assert direct.status_code == 404
    assert denied.status_code == 401
    assert allowed.status_code == 200


@pytest.mark.contract
def test_inventory_invocation_rejects_unsupported_question(client: TestClient) -> None:
    unknown = "sensitive-unknown-place"
    response = client.post(
        "/agents/inventory/invoke",
        json={"query": f"Will shovels run low in {unknown}?"},
        headers={"X-Correlation-ID": "inventory-invalid"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_request",
            "message": "Ask about a supported city and product",
            "correlation_id": "inventory-invalid",
            "details": [],
        }
    }
    assert unknown not in response.text


@pytest.mark.contract
def test_knowledge_invocation_returns_grounded_policy_answer(client: TestClient) -> None:
    response = client.post(
        "/agents/knowledge/invoke",
        json={"query": "Can I return an unopened product after 20 days?", "seed": 4},
        headers={"X-Correlation-ID": "knowledge-contract"},
    )

    body = response.json()
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "knowledge-contract"
    assert body["answer"].startswith("Unopened products may be returned within 30 days")
    assert body["citations"][0]["source_id"] in body["retrieval"]["result_ids"]
    assert body["retrieval"]["corpus_version"] == "v1"


@pytest.mark.contract
def test_knowledge_invocation_abstains_without_evidence(client: TestClient) -> None:
    response = client.post(
        "/agents/knowledge/invoke",
        json={"query": "What is the warranty for a lunar telescope?"},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "Insufficient evidence in the current policy corpus."
    assert response.json()["citations"] == []


@pytest.mark.contract
def test_shopping_invocation_recommends_only_retrieved_product(client: TestClient) -> None:
    response = client.post(
        "/agents/shopping/invoke",
        json={"query": "Recommend a snow shovel under $50", "seed": 5},
        headers={"X-Correlation-ID": "shopping-contract"},
    )

    body = response.json()
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "shopping-contract"
    assert body["answer"].startswith("I recommend NorthPeak Aluminum Snow Shovel at $39.99")
    assert body["tool_calls"][0]["tool_name"] == "product.search"
    assert body["citations"][0]["source_id"] in body["retrieval"]["result_ids"]


@pytest.mark.contract
def test_shopping_invocation_abstains_when_budget_excludes_results(
    client: TestClient,
) -> None:
    response = client.post(
        "/agents/shopping/invoke",
        json={"query": "Recommend a snow shovel under $10"},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "Insufficient product evidence for a recommendation."
    assert response.json()["citations"] == []
