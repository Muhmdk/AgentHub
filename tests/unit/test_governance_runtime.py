"""Runtime authorization tests at model and tool action boundaries."""

import asyncio

import pytest

from agents.shared.model import DeterministicFakeModel, RetryableModelError
from packages.contracts.governance import (
    AuthenticationMethod,
    IdentityKind,
    PolicyDecision,
    PolicyInput,
    PolicyObligations,
    PolicySubject,
)
from packages.contracts.runtime import (
    AgentErrorCode,
    AgentExecutionError,
    ChatMessage,
    Citation,
    JsonValue,
    ModelRequest,
    ModelResponse,
    ToolDefinition,
    ToolObservation,
    Usage,
)
from packages.governance import (
    AuthorizedChatModel,
    AuthorizedTool,
    BudgetLimits,
    BudgetManager,
    InMemoryGovernanceAuditStore,
    LocalPolicyEngine,
    PolicyAuthorizer,
    PolicyEngineUnavailable,
    RuntimePolicyContext,
    agent_policy_profiles,
    bind_policy_context,
)


class RecordingPolicyEngine:
    def __init__(
        self,
        *,
        allow: bool = True,
        unavailable: bool = False,
        obligations: PolicyObligations | None = None,
    ) -> None:
        self.allow = allow
        self.unavailable = unavailable
        self.obligations = obligations or PolicyObligations(audit=True)
        self.inputs: list[PolicyInput] = []

    async def decide(self, policy_input: PolicyInput) -> PolicyDecision:
        self.inputs.append(policy_input)
        if self.unavailable:
            raise PolicyEngineUnavailable("offline")
        return PolicyDecision(
            schema_version="agenthub.dev/policy-decision/v1",
            allow=self.allow,
            reasons=["test_allowed" if self.allow else "test_denied"],
            policy_bundle_version="test.v1",
            obligations=self.obligations,
        )


class ScriptedModel:
    name = "fake/deterministic-v1"

    def __init__(self, outcomes: list[Exception | ModelResponse]) -> None:
        self.outcomes = outcomes
        self.call_count = 0

    async def generate(self, request: ModelRequest) -> ModelResponse:
        del request
        outcome = self.outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class SlowModel:
    name = "fake/deterministic-v1"

    def __init__(self) -> None:
        self.call_count = 0

    async def generate(self, request: ModelRequest) -> ModelResponse:
        del request
        self.call_count += 1
        await asyncio.sleep(1)
        raise AssertionError("timeout should cancel the provider call")


def _response() -> ModelResponse:
    return ModelResponse(
        response_id="model-response-1",
        model="fake/deterministic-v1",
        content="Safe",
        usage=Usage(input_tokens=2, output_tokens=1, estimated_cost_usd=0.01),
    )


class RecordingTool:
    definition = ToolDefinition(name="inventory.read", description="Test inventory read")

    def __init__(self) -> None:
        self.call_count = 0

    async def invoke(self, arguments: dict[str, JsonValue]) -> ToolObservation:
        del arguments
        self.call_count += 1
        return ToolObservation(
            data={"records": []},
            citations=[Citation(source_id="inventory:test", title="Test inventory")],
        )


def _authorizer(
    engine: RecordingPolicyEngine,
    environment: str = "test",
    audit_store: InMemoryGovernanceAuditStore | None = None,
) -> PolicyAuthorizer:
    profile = agent_policy_profiles("fake/deterministic-v1")["inventory-agent"]
    return PolicyAuthorizer(engine, profile, environment, audit_store)


@pytest.mark.unit
def test_tool_is_authorized_immediately_before_target_invocation() -> None:
    engine = RecordingPolicyEngine()
    target = RecordingTool()
    tool = AuthorizedTool(
        target,
        definition=target.definition,
        authorizer=_authorizer(engine),
        required_scopes=["inventory:read"],
    )

    result = asyncio.run(tool.invoke({"city": "Toronto", "sku": "shovel"}))

    assert target.call_count == 1
    assert result.citations[0].source_id == "inventory:test"
    assert engine.inputs[0].action.kind == "tool_execution"
    assert engine.inputs[0].subject.identity == "local/internal"
    assert "Toronto" not in engine.inputs[0].model_dump_json()


@pytest.mark.unit
def test_policy_deny_prevents_tool_side_effect() -> None:
    engine = RecordingPolicyEngine(allow=False)
    target = RecordingTool()
    tool = AuthorizedTool(
        target,
        definition=target.definition,
        authorizer=_authorizer(engine),
        required_scopes=["inventory:read"],
    )

    with pytest.raises(AgentExecutionError) as raised:
        asyncio.run(tool.invoke({"city": "Toronto"}))

    assert raised.value.code == AgentErrorCode.POLICY_DENIED
    assert target.call_count == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("profile_name", "tool_name", "scope"),
    [
        ("knowledge-agent", "inventory.read", "inventory:read"),
        ("shopping-agent", "inventory.read", "inventory:read"),
        ("inventory-agent", "customer.profile", "customer:read"),
    ],
)
def test_undeclared_and_cross_agent_tools_are_denied_at_target_boundary(
    profile_name: str,
    tool_name: str,
    scope: str,
) -> None:
    engine = LocalPolicyEngine()
    profile = agent_policy_profiles("fake/deterministic-v1")[profile_name]
    target = RecordingTool()
    tool = AuthorizedTool(
        target,
        definition=ToolDefinition(name=tool_name, description="Forbidden test tool"),
        authorizer=PolicyAuthorizer(engine, profile, "test"),
        required_scopes=[scope],
    )

    with pytest.raises(AgentExecutionError) as raised:
        asyncio.run(tool.invoke({"customer": "never-store-this"}))

    assert raised.value.code == AgentErrorCode.POLICY_DENIED
    assert target.call_count == 0


@pytest.mark.unit
def test_gateway_identity_is_propagated_to_model_authorization() -> None:
    engine = RecordingPolicyEngine()
    target = DeterministicFakeModel()
    model = AuthorizedChatModel(target, _authorizer(engine))
    context = RuntimePolicyContext(
        subject=PolicySubject(
            identity="service/runtime",
            kind=IdentityKind.SERVICE,
            authentication_method=AuthenticationMethod.BEARER,
            roles=["gateway-invoker"],
        ),
        correlation_id="runtime-policy-1",
        release_id="release-42",
    )

    with bind_policy_context(context):
        response = asyncio.run(
            model.generate(
                ModelRequest(messages=[ChatMessage(role="user", content="FINAL_ANSWER:\nSafe")])
            )
        )

    policy_input = engine.inputs[0]
    assert response.content == "Safe"
    assert policy_input.subject.identity == "service/runtime"
    assert policy_input.context.correlation_id == "runtime-policy-1"
    assert policy_input.context.release_id == "release-42"
    assert policy_input.action.kind == "model_invocation"


@pytest.mark.unit
def test_policy_outage_fails_closed_before_model_invocation() -> None:
    engine = RecordingPolicyEngine(unavailable=True)
    model = AuthorizedChatModel(DeterministicFakeModel(), _authorizer(engine))

    with pytest.raises(AgentExecutionError) as raised:
        asyncio.run(
            model.generate(ModelRequest(messages=[ChatMessage(role="user", content="Hello")]))
        )

    assert raised.value.code == AgentErrorCode.POLICY_UNAVAILABLE


@pytest.mark.unit
def test_deployed_action_without_request_identity_fails_closed() -> None:
    engine = RecordingPolicyEngine()
    model = AuthorizedChatModel(DeterministicFakeModel(), _authorizer(engine, "production"))

    with pytest.raises(AgentExecutionError) as raised:
        asyncio.run(
            model.generate(ModelRequest(messages=[ChatMessage(role="user", content="Hello")]))
        )

    assert raised.value.code == AgentErrorCode.POLICY_DENIED
    assert engine.inputs == []


@pytest.mark.unit
def test_rate_limit_stops_provider_call_with_stable_error() -> None:
    engine = RecordingPolicyEngine()
    target = ScriptedModel([_response()])
    model = AuthorizedChatModel(
        target,
        _authorizer(engine),
        budget_manager=BudgetManager(),
        budget_limits=BudgetLimits(
            requests_per_minute=1,
            tokens_per_minute=10_000,
            cost_per_hour_usd=1,
        ),
    )
    request = ModelRequest(messages=[ChatMessage(role="user", content="Hello")])

    asyncio.run(model.generate(request))
    with pytest.raises(AgentExecutionError) as raised:
        asyncio.run(model.generate(request))

    assert raised.value.code == AgentErrorCode.RATE_LIMITED
    assert target.call_count == 1


@pytest.mark.unit
def test_token_budget_stops_provider_before_execution() -> None:
    target = ScriptedModel([_response()])
    model = AuthorizedChatModel(
        target,
        _authorizer(RecordingPolicyEngine()),
        budget_limits=BudgetLimits(
            requests_per_minute=10,
            tokens_per_minute=10,
            cost_per_hour_usd=1,
        ),
    )

    with pytest.raises(AgentExecutionError) as raised:
        asyncio.run(
            model.generate(
                ModelRequest(
                    messages=[ChatMessage(role="user", content="Hello")],
                    max_tokens=10,
                )
            )
        )

    assert raised.value.code == AgentErrorCode.BUDGET_EXCEEDED
    assert target.call_count == 0


@pytest.mark.unit
def test_retryable_provider_failure_succeeds_within_bound() -> None:
    target = ScriptedModel([RetryableModelError("transient"), _response()])
    model = AuthorizedChatModel(
        target,
        _authorizer(RecordingPolicyEngine()),
        retry_backoff_seconds=0,
    )

    response = asyncio.run(
        model.generate(ModelRequest(messages=[ChatMessage(role="user", content="Hello")]))
    )

    assert response.content == "Safe"
    assert target.call_count == 2


@pytest.mark.unit
def test_timeout_obligation_has_bounded_retries_and_stable_error() -> None:
    target = SlowModel()
    engine = RecordingPolicyEngine(obligations=PolicyObligations(audit=True, timeout_ms=1))
    model = AuthorizedChatModel(
        target,
        _authorizer(engine),
        max_attempts=2,
        retry_backoff_seconds=0,
    )

    with pytest.raises(AgentExecutionError) as raised:
        asyncio.run(
            model.generate(ModelRequest(messages=[ChatMessage(role="user", content="Hello")]))
        )

    assert raised.value.code == AgentErrorCode.MODEL_TIMEOUT
    assert target.call_count == 2


@pytest.mark.unit
def test_non_retryable_provider_failure_is_not_retried() -> None:
    target = ScriptedModel([RuntimeError("permanent")])
    model = AuthorizedChatModel(target, _authorizer(RecordingPolicyEngine()))

    with pytest.raises(RuntimeError, match="permanent"):
        asyncio.run(
            model.generate(ModelRequest(messages=[ChatMessage(role="user", content="Hello")]))
        )

    assert target.call_count == 1
