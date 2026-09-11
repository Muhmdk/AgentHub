"""OPA transport and local policy adapter tests."""

import asyncio
import json
from types import TracebackType
from typing import Self
from urllib.request import Request

import pytest

from packages.contracts.governance import (
    ModelInvocationAction,
    PolicyAgent,
    PolicyInput,
    PolicyModelGrant,
    PolicyRequestContext,
    PolicySubject,
)
from packages.governance import OPAHttpPolicyEngine, PolicyEngineUnavailable


def _policy_input() -> PolicyInput:
    return PolicyInput(
        schema_version="agenthub.dev/policy-input/v1",
        subject=PolicySubject(
            identity="service/runtime",
            kind="service",
            authentication_method="bearer",
        ),
        agent=PolicyAgent(
            name="inventory-agent",
            version="1.0.0",
            owner="retail-ai-team",
            risk_tier="medium",
            model=PolicyModelGrant(provider="fake", model="deterministic-v1"),
        ),
        action=ModelInvocationAction(
            kind="model_invocation",
            provider="fake",
            model="deterministic-v1",
            requested_input_tokens=10,
            requested_output_tokens=100,
            data_classes=["internal"],
            external_provider=False,
        ),
        context=PolicyRequestContext(
            environment="test",
            correlation_id="opa-client-test",
            occurred_at="2026-09-10T15:00:00Z",
        ),
    )


class FixtureResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception_type, exception, traceback

    def read(self) -> bytes:
        return self._body


@pytest.mark.unit
def test_opa_client_posts_versioned_input_and_parses_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[Request] = []
    response = FixtureResponse(
        {
            "result": {
                "schema_version": "agenthub.dev/policy-decision/v1",
                "allow": True,
                "reasons": ["model_invocation_allowed"],
                "policy_bundle_version": "phase08.1",
                "obligations": {"audit": True},
            }
        }
    )

    def urlopen_fixture(request: Request, timeout: float) -> FixtureResponse:
        assert timeout == 2.0
        requests.append(request)
        return response

    monkeypatch.setattr("packages.governance.engine.urlopen", urlopen_fixture)
    engine = OPAHttpPolicyEngine(
        "http://127.0.0.1:8181/v1/data/agenthub/authz/decision",
        2.0,
    )

    decision = asyncio.run(engine.decide(_policy_input()))

    assert decision.allow
    assert decision.policy_bundle_version == "phase08.1"
    request_data = requests[0].data
    assert isinstance(request_data, bytes)
    submitted = json.loads(request_data)
    assert submitted["input"]["context"]["correlation_id"] == "opa-client-test"


@pytest.mark.unit
def test_opa_client_treats_undefined_decision_as_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def urlopen_fixture(request: Request, timeout: float) -> FixtureResponse:
        del request, timeout
        return FixtureResponse({})

    monkeypatch.setattr("packages.governance.engine.urlopen", urlopen_fixture)
    engine = OPAHttpPolicyEngine(
        "http://127.0.0.1:8181/v1/data/agenthub/authz/decision",
        2.0,
    )

    with pytest.raises(PolicyEngineUnavailable, match="Policy engine is unavailable"):
        asyncio.run(engine.decide(_policy_input()))


@pytest.mark.unit
def test_opa_client_rejects_unbounded_or_non_http_configuration() -> None:
    with pytest.raises(ValueError, match="HTTP or HTTPS"):
        OPAHttpPolicyEngine("file:///tmp/policy", 2.0)
    with pytest.raises(ValueError, match="no more than 30"):
        OPAHttpPolicyEngine("http://127.0.0.1:8181", 31.0)
