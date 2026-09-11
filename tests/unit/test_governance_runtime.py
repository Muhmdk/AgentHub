"""Runtime authorization tests at model and tool action boundaries."""

import asyncio

import pytest

from agents.shared.model import DeterministicFakeModel
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
    ToolDefinition,
    ToolObservation,
)
from packages.governance import (
    AuthorizedChatModel,
    AuthorizedTool,
    PolicyAuthorizer,
    PolicyEngineUnavailable,
    RuntimePolicyContext,
    agent_policy_profiles,
    bind_policy_context,
)


class RecordingPolicyEngine:
    def __init__(self, *, allow: bool = True, unavailable: bool = False) -> None:
        self.allow = allow
        self.unavailable = unavailable
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
            obligations=PolicyObligations(audit=True),
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


def _authorizer(engine: RecordingPolicyEngine, environment: str = "test") -> PolicyAuthorizer:
    profile = agent_policy_profiles("fake/deterministic-v1")["inventory-agent"]
    return PolicyAuthorizer(engine, profile, environment)


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
