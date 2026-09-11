"""Deterministic PII detection and pre-provider redaction tests."""

import asyncio

import pytest

from packages.contracts.governance import (
    AuthenticationMethod,
    DataClass,
    IdentityKind,
    ModelInvocationAction,
    PolicyDecision,
    PolicyInput,
    PolicyObligations,
    PolicySubject,
)
from packages.contracts.runtime import (
    AgentErrorCode,
    AgentExecutionError,
    ChatMessage,
    ModelRequest,
    ModelResponse,
    Usage,
)
from packages.governance import (
    AuthorizedChatModel,
    LocalPolicyEngine,
    PIIKind,
    PolicyAuthorizer,
    RuntimePolicyContext,
    agent_policy_profiles,
    bind_policy_context,
    detect_pii,
    redact_model_request,
    redact_text,
)


class CapturingExternalModel:
    name = "azure-openai/gpt-test"

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(
            response_id="external-test-1",
            model=self.name,
            content=request.messages[-1].content,
            usage=Usage(input_tokens=20, output_tokens=10),
        )


class CapturingLocalPolicyEngine(LocalPolicyEngine):
    def __init__(self) -> None:
        self.inputs: list[PolicyInput] = []

    async def decide(self, policy_input: PolicyInput) -> PolicyDecision:
        self.inputs.append(policy_input)
        return await super().decide(policy_input)


class MissingRedactionPolicyEngine:
    async def decide(self, policy_input: PolicyInput) -> PolicyDecision:
        del policy_input
        return PolicyDecision(
            schema_version="agenthub.dev/policy-decision/v1",
            allow=True,
            reasons=["model_invocation_allowed"],
            policy_bundle_version="unsafe-test.v1",
            obligations=PolicyObligations(audit=True, redact_pii=False),
        )


def _external_model(
    engine: LocalPolicyEngine | MissingRedactionPolicyEngine,
) -> tuple[AuthorizedChatModel, CapturingExternalModel]:
    profile = agent_policy_profiles("azure-openai/gpt-test")["knowledge-agent"]
    target = CapturingExternalModel()
    return (
        AuthorizedChatModel(target, PolicyAuthorizer(engine, profile, "staging")),
        target,
    )


def _context() -> RuntimePolicyContext:
    return RuntimePolicyContext(
        subject=PolicySubject(
            identity="service/runtime",
            kind=IdentityKind.SERVICE,
            authentication_method=AuthenticationMethod.BEARER,
        ),
        correlation_id="privacy-test-1",
        release_id="release-42",
    )


@pytest.mark.unit
def test_supported_pii_is_detected_without_retaining_values() -> None:
    text = (
        "Email alex@example.test, call 416-555-0123, use card 4111 1111 1111 1111, "
        "or SIN 046 454 286."
    )

    findings = detect_pii(text)

    assert {finding.kind for finding in findings} == {
        PIIKind.EMAIL,
        PIIKind.PHONE,
        PIIKind.PAYMENT_CARD,
        PIIKind.CANADIAN_SIN,
    }
    assert "alex@example.test" not in repr(findings)


@pytest.mark.unit
def test_redaction_is_deterministic_typed_and_avoids_invalid_candidates() -> None:
    original = "Contact alex@example.test at 416 555 0123; invalid card 4111 1111 1111 1112."

    redacted = redact_text(original)

    assert redacted == (
        "Contact [REDACTED:EMAIL] at [REDACTED:PHONE]; invalid card 4111 1111 1111 1112."
    )
    assert redact_text(redacted) == redacted


@pytest.mark.unit
def test_model_request_redaction_preserves_non_content_parameters() -> None:
    request = ModelRequest(
        messages=[ChatMessage(role="user", content="Email alex@example.test")],
        temperature=0.2,
        max_tokens=321,
        seed=9,
    )

    redacted = redact_model_request(request)

    assert redacted.messages[0].content == "Email [REDACTED:EMAIL]"
    assert redacted.temperature == 0.2
    assert redacted.max_tokens == 321
    assert redacted.seed == 9
    assert request.messages[0].content == "Email alex@example.test"


@pytest.mark.unit
def test_external_provider_receives_only_redacted_content() -> None:
    engine = CapturingLocalPolicyEngine()
    model, target = _external_model(engine)
    request = ModelRequest(
        messages=[ChatMessage(role="user", content="Reply to alex@example.test")]
    )

    with bind_policy_context(_context()):
        response = asyncio.run(model.generate(request))

    assert response.content == "Reply to [REDACTED:EMAIL]"
    assert target.requests[0].messages[0].content == "Reply to [REDACTED:EMAIL]"
    policy_input = engine.inputs[0]
    assert isinstance(policy_input.action, ModelInvocationAction)
    assert DataClass.PII in policy_input.action.data_classes
    assert "alex@example.test" not in policy_input.model_dump_json()


@pytest.mark.unit
def test_external_pii_fails_closed_without_redaction_obligation() -> None:
    model, target = _external_model(MissingRedactionPolicyEngine())
    request = ModelRequest(
        messages=[ChatMessage(role="user", content="Reply to alex@example.test")]
    )

    with bind_policy_context(_context()), pytest.raises(AgentExecutionError) as raised:
        asyncio.run(model.generate(request))

    assert raised.value.code == AgentErrorCode.POLICY_DENIED
    assert target.requests == []
