"""Governance audit attribution and sensitive-field tests."""

import asyncio

import pytest

from agents.shared.model import DeterministicFakeModel
from packages.contracts.governance import (
    GovernanceAuditEvent,
    GovernanceAuditEventType,
    GovernanceAuditOutcome,
    PolicyDecision,
    PolicyInput,
    PolicyObligations,
)
from packages.contracts.runtime import (
    AgentErrorCode,
    AgentExecutionError,
    ChatMessage,
    ModelRequest,
    ModelResponse,
)
from packages.governance import (
    AuthorizedChatModel,
    BudgetLimits,
    InMemoryGovernanceAuditStore,
    PolicyAuthorizer,
    agent_policy_profiles,
)


class DecisionEngine:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow

    async def decide(self, policy_input: PolicyInput) -> PolicyDecision:
        return PolicyDecision(
            schema_version="agenthub.dev/policy-decision/v1",
            allow=self.allow,
            reasons=["model_invocation_allowed" if self.allow else "model_not_declared"],
            policy_bundle_version="audit-test.v1",
            obligations=PolicyObligations(audit=True),
        )


class FailingAuditStore:
    def append(self, event: GovernanceAuditEvent) -> None:
        del event
        raise RuntimeError("sensitive database failure")

    def list_events(
        self,
        *,
        agent_name: str | None = None,
        outcome: GovernanceAuditOutcome | None = None,
        limit: int = 100,
    ) -> list[GovernanceAuditEvent]:
        del agent_name, outcome, limit
        return []


def _model(
    store: InMemoryGovernanceAuditStore,
    *,
    allow: bool = True,
    requests_per_minute: int = 120,
) -> AuthorizedChatModel:
    profile = agent_policy_profiles("fake/deterministic-v1")["inventory-agent"]
    authorizer = PolicyAuthorizer(DecisionEngine(allow), profile, "test", store)
    return AuthorizedChatModel(
        DeterministicFakeModel(),
        authorizer,
        budget_limits=BudgetLimits(
            requests_per_minute=requests_per_minute,
            tokens_per_minute=100_000,
            cost_per_hour_usd=10,
        ),
    )


@pytest.mark.unit
def test_allow_event_is_attributed_and_excludes_model_content() -> None:
    store = InMemoryGovernanceAuditStore()
    model = _model(store)
    sensitive = "Email private.person@example.test with account 4111111111111111"

    asyncio.run(
        model.generate(ModelRequest(messages=[ChatMessage(role="user", content=sensitive)]))
    )

    event = store.list_events()[0]
    serialized = event.model_dump_json()
    assert event.event_type == GovernanceAuditEventType.POLICY_DECISION
    assert event.outcome == GovernanceAuditOutcome.ALLOW
    assert event.allowed is True
    assert event.identity == "local/internal"
    assert event.agent_name == "inventory-agent"
    assert event.agent_version == "1.0.0"
    assert event.action_kind == "model_invocation"
    assert event.target == "fake/deterministic-v1"
    assert event.policy_bundle_version == "audit-test.v1"
    assert event.correlation_id == "local-internal"
    assert sensitive not in serialized
    assert "private.person@example.test" not in serialized
    assert "4111111111111111" not in serialized


@pytest.mark.unit
def test_policy_deny_is_persisted_before_safe_error() -> None:
    store = InMemoryGovernanceAuditStore()

    with pytest.raises(AgentExecutionError) as raised:
        asyncio.run(
            _model(store, allow=False).generate(
                ModelRequest(messages=[ChatMessage(role="user", content="Never persist me")])
            )
        )

    event = store.list_events()[0]
    assert raised.value.code == AgentErrorCode.POLICY_DENIED
    assert event.outcome == GovernanceAuditOutcome.DENY
    assert event.allowed is False
    assert event.reasons == ["model_not_declared"]
    assert "Never persist me" not in event.model_dump_json()


@pytest.mark.unit
def test_rate_limit_violation_appends_enforcement_event() -> None:
    store = InMemoryGovernanceAuditStore()
    model = _model(store, requests_per_minute=1)
    request = ModelRequest(messages=[ChatMessage(role="user", content="Hello")])
    asyncio.run(model.generate(request))

    with pytest.raises(AgentExecutionError) as raised:
        asyncio.run(model.generate(request))

    events = store.list_events()
    assert raised.value.code == AgentErrorCode.RATE_LIMITED
    assert events[0].event_type == GovernanceAuditEventType.RUNTIME_ENFORCEMENT
    assert events[0].outcome == GovernanceAuditOutcome.RATE_LIMITED
    assert events[0].allowed is False
    assert events[0].reasons == ["model_rate_limit_exceeded"]
    assert [event.outcome for event in events[1:]] == [
        GovernanceAuditOutcome.ALLOW,
        GovernanceAuditOutcome.ALLOW,
    ]


@pytest.mark.unit
def test_audit_filters_are_bounded_and_stable() -> None:
    store = InMemoryGovernanceAuditStore()
    asyncio.run(
        _model(store).generate(ModelRequest(messages=[ChatMessage(role="user", content="Hello")]))
    )

    assert len(store.list_events(agent_name="inventory-agent", limit=1)) == 1
    assert store.list_events(agent_name="other-agent") == []
    assert len(store.list_events(outcome=GovernanceAuditOutcome.ALLOW)) == 1


@pytest.mark.unit
def test_required_audit_failure_stops_model_execution_with_safe_error() -> None:
    class CountingModel(DeterministicFakeModel):
        def __init__(self) -> None:
            self.called = False

        async def generate(self, request: ModelRequest) -> ModelResponse:
            self.called = True
            return await super().generate(request)

    profile = agent_policy_profiles("fake/deterministic-v1")["inventory-agent"]
    target = CountingModel()
    model = AuthorizedChatModel(
        target,
        PolicyAuthorizer(DecisionEngine(), profile, "test", FailingAuditStore()),
    )

    with pytest.raises(AgentExecutionError) as raised:
        asyncio.run(
            model.generate(
                ModelRequest(messages=[ChatMessage(role="user", content="Never execute")])
            )
        )

    assert raised.value.code == AgentErrorCode.POLICY_UNAVAILABLE
    assert raised.value.message == "Governance audit is unavailable"
    assert "database" not in str(raised.value)
    assert target.called is False
