"""HTTP contract tests for the walking-skeleton API."""

import pytest
from fastapi import Query
from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.main import create_app


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
