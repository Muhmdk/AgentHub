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
