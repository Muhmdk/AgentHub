"""Contract tests for documents exchanged with OPA/Rego."""

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from packages.contracts.governance import (
    ApprovalEvidence,
    AuthenticationMethod,
    DataClass,
    DeploymentEnvironment,
    IdentityKind,
    ModelInvocationAction,
    OPAQuery,
    OPAResponse,
    PolicyAction,
    PolicyAgent,
    PolicyDecision,
    PolicyInput,
    PolicyModelGrant,
    PolicyObligations,
    PolicyRequestContext,
    PolicySubject,
    PolicyToolGrant,
    PromotionAction,
    RegistrationAction,
    ToolAccess,
    ToolExecutionAction,
)
from packages.contracts.manifest import RiskTier

NOW = datetime(2026, 9, 10, 15, 0, tzinfo=UTC)


def _subject() -> PolicySubject:
    return PolicySubject(
        identity="service/gateway",
        kind=IdentityKind.SERVICE,
        authentication_method=AuthenticationMethod.WORKLOAD_IDENTITY,
        roles=["runtime-invoker"],
    )


def _agent() -> PolicyAgent:
    return PolicyAgent(
        name="inventory-agent",
        version="1.0.0",
        owner="retail-ai-team",
        risk_tier=RiskTier.MEDIUM,
        tools=[
            PolicyToolGrant(
                name="inventory.read",
                scopes=["inventory:read"],
                access=ToolAccess.READ,
            )
        ],
        model=PolicyModelGrant(provider="fake", model="deterministic-v1"),
    )


def _input(action: PolicyAction) -> PolicyInput:
    return PolicyInput(
        schema_version="agenthub.dev/policy-input/v1",
        subject=_subject(),
        agent=_agent(),
        action=action,
        context=PolicyRequestContext(
            environment=DeploymentEnvironment.STAGING,
            correlation_id="request-123",
            occurred_at=NOW,
            release_id="release-42",
        ),
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "action",
    [
        RegistrationAction(
            kind="registration",
            manifest_hash="a" * 64,
            source_sha="b" * 40,
        ),
        PromotionAction(
            kind="promotion",
            target_environment=DeploymentEnvironment.PRODUCTION,
            evaluation_passed=True,
            security_passed=True,
            approvals=[ApprovalEvidence(approver="human/operator-one", approved_at=NOW)],
        ),
        ModelInvocationAction(
            kind="model_invocation",
            provider="azure-openai",
            model="gpt-deployment",
            requested_input_tokens=800,
            requested_output_tokens=400,
            data_classes=[DataClass.INTERNAL, DataClass.PII],
            external_provider=True,
        ),
        ToolExecutionAction(
            kind="tool_execution",
            tool_name="inventory.read",
            required_scopes=["inventory:read"],
            access=ToolAccess.READ,
            arguments_hash="c" * 64,
        ),
    ],
    ids=["registration", "promotion", "model", "tool"],
)
def test_all_decision_points_round_trip_through_opa_input(action: PolicyAction) -> None:
    policy_input = _input(action)

    query = OPAQuery.model_validate_json(OPAQuery(input=policy_input).model_dump_json())

    assert query.input.action.kind == action.kind
    assert query.input.subject.identity == "service/gateway"
    assert query.input.context.occurred_at == NOW


@pytest.mark.unit
def test_action_union_rejects_unknown_decision_point() -> None:
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        TypeAdapter(PolicyAction).validate_python({"kind": "prompt_authorization"})


@pytest.mark.unit
def test_policy_documents_reject_unknown_fields_and_naive_times() -> None:
    payload = _input(
        RegistrationAction(
            kind="registration",
            manifest_hash="a" * 64,
            source_sha="b" * 40,
        )
    ).model_dump(mode="json")
    payload["untrusted"] = True
    payload["context"]["occurred_at"] = "2026-09-10T15:00:00"

    with pytest.raises(ValidationError) as raised:
        PolicyInput.model_validate(payload)

    locations = {error["loc"] for error in raised.value.errors()}
    assert ("untrusted",) in locations
    assert ("context", "occurred_at") in locations


@pytest.mark.unit
def test_generated_policy_schema_is_discriminated_and_closed() -> None:
    schema = PolicyInput.model_json_schema()

    assert schema["additionalProperties"] is False
    assert schema["properties"]["action"]["discriminator"]["propertyName"] == "kind"
    assert set(schema["properties"]) == {
        "schema_version",
        "subject",
        "agent",
        "action",
        "context",
    }


@pytest.mark.unit
def test_opa_response_requires_versioned_explainable_decision() -> None:
    response = OPAResponse(
        result=PolicyDecision(
            schema_version="agenthub.dev/policy-decision/v1",
            allow=True,
            reasons=["declared_tool_allowed"],
            policy_bundle_version="2026.09.10+sha.abc123",
            obligations=PolicyObligations(
                audit=True,
                redact_pii=True,
                max_input_tokens=2_000,
                max_output_tokens=800,
                timeout_ms=5_000,
                rate_limit_per_minute=60,
            ),
        )
    )

    parsed = OPAResponse.model_validate_json(response.model_dump_json())

    assert parsed.result.allow
    assert parsed.result.reasons == ["declared_tool_allowed"]
    assert parsed.result.obligations.redact_pii


@pytest.mark.unit
def test_undefined_or_unexplained_opa_decision_is_invalid() -> None:
    with pytest.raises(ValidationError):
        OPAResponse.model_validate({})
    with pytest.raises(ValidationError):
        PolicyDecision(
            schema_version="agenthub.dev/policy-decision/v1",
            allow=False,
            reasons=[],
            policy_bundle_version="v1",
        )
