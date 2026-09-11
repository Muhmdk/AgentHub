"""Versioned policy input and decision contracts shared with OPA/Rego."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from packages.contracts.manifest import RiskTier, SemanticVersion, Slug
from packages.contracts.release import Sha256

PolicyString = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
Identity = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=2,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    ),
]
ReasonCode = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$"),
]
PolicyBundleVersion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]*$",
    ),
]


class DeploymentEnvironment(StrEnum):
    """Environment values policy may distinguish."""

    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class IdentityKind(StrEnum):
    """Caller class used for separation-of-duty rules."""

    HUMAN = "human"
    SERVICE = "service"


class AuthenticationMethod(StrEnum):
    """Evidence that established the policy subject."""

    LOCAL_EXPLICIT = "local-explicit"
    BEARER = "bearer"
    WORKLOAD_IDENTITY = "workload-identity"


class DataClass(StrEnum):
    """Supported information sensitivity classes."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PII = "pii"


class ToolAccess(StrEnum):
    """Side-effect class for a requested or declared tool."""

    READ = "read"
    WRITE = "write"


class PolicySubject(BaseModel):
    """Authenticated caller supplied by the gateway or control plane."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: Identity
    kind: IdentityKind
    authentication_method: AuthenticationMethod
    roles: list[PolicyString] = Field(default_factory=list, max_length=20)


class PolicyToolGrant(BaseModel):
    """Tool and scopes declared by an immutable agent version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: PolicyString
    scopes: list[PolicyString] = Field(default_factory=list, max_length=50)
    access: ToolAccess


class PolicyModelGrant(BaseModel):
    """Provider/model pair declared by an immutable agent version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: PolicyString
    model: PolicyString


class PolicyAgent(BaseModel):
    """Immutable agent facts made available to every decision point."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Slug
    version: SemanticVersion
    owner: PolicyString
    risk_tier: RiskTier
    tools: list[PolicyToolGrant] = Field(default_factory=list, max_length=50)
    model: PolicyModelGrant


class PolicyRequestContext(BaseModel):
    """Request attribution and environment supplied independently of the action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    environment: DeploymentEnvironment
    correlation_id: Identity
    occurred_at: AwareDatetime
    release_id: Identity | None = None


class RegistrationAction(BaseModel):
    """Authorize registering one immutable manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["registration"]
    manifest_hash: Sha256
    source_sha: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class ApprovalEvidence(BaseModel):
    """One independently attributable human approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approver: Identity
    approved_at: AwareDatetime


class PromotionAction(BaseModel):
    """Authorize moving an evaluated release to an environment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["promotion"]
    target_environment: Literal[
        DeploymentEnvironment.STAGING,
        DeploymentEnvironment.PRODUCTION,
    ]
    evaluation_passed: bool
    security_passed: bool
    approvals: list[ApprovalEvidence] = Field(default_factory=list, max_length=10)


class ModelInvocationAction(BaseModel):
    """Authorize one provider call immediately before invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["model_invocation"]
    provider: PolicyString
    model: PolicyString
    requested_input_tokens: int = Field(ge=0, le=1_000_000)
    requested_output_tokens: int = Field(ge=1, le=100_000)
    data_classes: list[DataClass] = Field(default_factory=list, max_length=10)
    external_provider: bool


class ToolExecutionAction(BaseModel):
    """Authorize one tool call immediately before execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["tool_execution"]
    tool_name: PolicyString
    required_scopes: list[PolicyString] = Field(default_factory=list, max_length=50)
    access: ToolAccess
    arguments_hash: Sha256


PolicyAction = Annotated[
    RegistrationAction | PromotionAction | ModelInvocationAction | ToolExecutionAction,
    Field(discriminator="kind"),
]


class PolicyInput(BaseModel):
    """Complete deterministic document sent in the OPA `input` field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["agenthub.dev/policy-input/v1"]
    subject: PolicySubject
    agent: PolicyAgent
    action: PolicyAction
    context: PolicyRequestContext


class PolicyObligations(BaseModel):
    """Mandatory controls attached to an allow decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audit: bool = True
    redact_pii: bool = False
    max_input_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    max_output_tokens: int | None = Field(default=None, ge=1, le=100_000)
    timeout_ms: int | None = Field(default=None, ge=1, le=120_000)
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=100_000)


class PolicyDecision(BaseModel):
    """Stable allow/deny response produced by the active policy bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["agenthub.dev/policy-decision/v1"]
    allow: bool
    reasons: list[ReasonCode] = Field(min_length=1, max_length=50)
    policy_bundle_version: PolicyBundleVersion
    obligations: PolicyObligations = Field(default_factory=PolicyObligations)


class OPAQuery(BaseModel):
    """OPA data API request envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input: PolicyInput


class OPAResponse(BaseModel):
    """OPA data API response; an undefined result is invalid and fails closed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    result: PolicyDecision
