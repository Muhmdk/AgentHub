"""Gateway-level governance failure, budget, timeout, and bypass scenarios."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from agents.shared.model import ChatModel
from agents.shared.providers import ProviderBundle, create_provider_bundle
from apps.api.config import Settings
from apps.api.main import create_app
from packages.contracts.governance import PolicyDecision, PolicyInput, PolicyObligations
from packages.contracts.runtime import ModelRequest, ModelResponse
from packages.governance import InMemoryGovernanceAuditStore, PolicyEngineUnavailable

_SERVICE_TOKEN = "gateway-governance-token-with-at-least-32-characters"
_QUERY = "Can I return an unopened product after 20 days?"


class AllowingEngine:
    async def decide(self, policy_input: PolicyInput) -> PolicyDecision:
        return PolicyDecision(
            schema_version="agenthub.dev/policy-decision/v1",
            allow=True,
            reasons=[f"{policy_input.action.kind}_allowed"],
            policy_bundle_version="gateway-test.v1",
            obligations=PolicyObligations(audit=True),
        )


class UnavailableEngine:
    async def decide(self, policy_input: PolicyInput) -> PolicyDecision:
        del policy_input
        raise PolicyEngineUnavailable("sensitive OPA connection detail")


class SlowModel(ChatModel):
    name = "fake/deterministic-v1"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: ModelRequest) -> ModelResponse:
        del request
        self.calls += 1
        await asyncio.sleep(1)
        raise AssertionError("model timeout must cancel execution")


def _headers(correlation_id: str) -> dict[str, str]:
    return {
        "X-AgentHub-Identity": "local/governance-test",
        "X-Correlation-ID": correlation_id,
    }


def _client(
    *,
    settings: Settings | None = None,
    policy_engine: AllowingEngine | UnavailableEngine | None = None,
    audit_store: InMemoryGovernanceAuditStore | None = None,
) -> TestClient:
    return TestClient(
        create_app(
            settings or Settings(environment="test", _env_file=None),
            policy_engine=policy_engine,
            governance_audit_store=audit_store or InMemoryGovernanceAuditStore(),
        ),
        raise_server_exceptions=False,
    )


@pytest.mark.contract
@pytest.mark.integration
def test_policy_outage_fails_closed_and_is_safely_audited() -> None:
    store = InMemoryGovernanceAuditStore()
    with _client(policy_engine=UnavailableEngine(), audit_store=store) as client:
        response = client.post(
            "/gateway/agents/knowledge-agent/invoke",
            json={"query": _QUERY},
            headers=_headers("gateway-policy-outage"),
        )
        audit = client.get("/governance/audit", params={"outcome": "policy_unavailable"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "policy_unavailable"
    assert "connection" not in response.text
    assert len(audit.json()) == 1
    assert audit.json()[0]["correlation_id"] == "gateway-policy-outage"
    assert "connection" not in audit.text


@pytest.mark.contract
@pytest.mark.integration
def test_gateway_rate_limit_returns_429_and_enforcement_audit() -> None:
    settings = Settings(
        environment="test",
        model_requests_per_minute=1,
        _env_file=None,
    )
    with _client(settings=settings) as client:
        first = client.post(
            "/gateway/agents/knowledge-agent/invoke",
            json={"query": _QUERY},
            headers=_headers("gateway-rate-first"),
        )
        limited = client.post(
            "/gateway/agents/knowledge-agent/invoke",
            json={"query": _QUERY},
            headers=_headers("gateway-rate-second"),
        )
        audit = client.get("/governance/audit", params={"outcome": "rate_limited"})

    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert len(audit.json()) == 1
    assert audit.json()[0]["correlation_id"] == "gateway-rate-second"


@pytest.mark.contract
@pytest.mark.integration
def test_gateway_token_budget_returns_429_before_model_call() -> None:
    settings = Settings(
        environment="test",
        model_tokens_per_minute=10,
        _env_file=None,
    )
    with _client(settings=settings) as client:
        response = client.post(
            "/gateway/agents/knowledge-agent/invoke",
            json={"query": _QUERY},
            headers=_headers("gateway-token-budget"),
        )
        audit = client.get("/governance/audit", params={"outcome": "budget_exceeded"})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "budget_exceeded"
    assert len(audit.json()) == 1
    assert audit.json()[0]["correlation_id"] == "gateway-token-budget"


@pytest.mark.contract
@pytest.mark.integration
def test_gateway_model_timeout_is_bounded_and_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_bundle = create_provider_bundle(Settings(environment="test", _env_file=None))
    slow_model = SlowModel()
    bundle = ProviderBundle(
        model=slow_model,
        retriever=default_bundle.retriever,
        corpus=default_bundle.corpus,
    )
    monkeypatch.setattr("apps.api.main.create_provider_bundle", lambda settings: bundle)
    settings = Settings(
        environment="test",
        model_timeout_seconds=0.001,
        model_max_attempts=2,
        model_retry_backoff_seconds=0,
        _env_file=None,
    )

    with _client(settings=settings, policy_engine=AllowingEngine()) as client:
        response = client.post(
            "/gateway/agents/knowledge-agent/invoke",
            json={"query": _QUERY},
            headers=_headers("gateway-model-timeout"),
        )

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "model_timeout"
    assert slow_model.calls == 2


@pytest.mark.contract
@pytest.mark.integration
def test_production_headers_cannot_bypass_missing_internal_routes() -> None:
    settings = Settings(
        environment="production",
        gateway_service_tokens={"service/runtime": _SERVICE_TOKEN},
        policy_engine_url="http://127.0.0.1:8181/v1/data/agenthub/authz/decision",
        _env_file=None,
    )
    headers = {
        "Authorization": f"Bearer {_SERVICE_TOKEN}",
        "X-AgentHub-Identity": "service/runtime",
    }
    with _client(settings=settings, policy_engine=AllowingEngine()) as client:
        direct = client.post(
            "/agents/knowledge/invoke",
            json={"query": _QUERY},
            headers=headers,
        )
        gateway = client.post(
            "/gateway/agents/knowledge-agent/invoke",
            json={"query": _QUERY},
            headers=headers,
        )

    assert direct.status_code == 404
    assert gateway.status_code == 200
