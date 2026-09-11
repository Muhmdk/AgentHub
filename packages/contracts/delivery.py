"""Contracts for atomic stable and candidate traffic routes."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from packages.contracts.manifest import SemanticVersion, Slug
from packages.contracts.observability import CostAttributionReport
from packages.contracts.release import IdempotencyKey, Sha256
from packages.contracts.runtime import AgentRequest, AgentResponse

BasisPoints = Annotated[int, Field(ge=0, le=10_000)]


class DeliveryEnvironment(StrEnum):
    """Traffic environments with durable release routing."""

    STAGING = "staging"
    PRODUCTION = "production"


class RouteLane(StrEnum):
    """The stable or candidate side selected for a request."""

    STABLE = "stable"
    CANDIDATE = "candidate"


class ShadowStatus(StrEnum):
    """Terminal status of an isolated candidate invocation."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class CanaryState(StrEnum):
    """Ordered progressive-delivery stages and terminal outcomes."""

    PENDING = "pending"
    FIVE_PERCENT = "5_percent"
    TWENTY_FIVE_PERCENT = "25_percent"
    FIFTY_PERCENT = "50_percent"
    ONE_HUNDRED_PERCENT = "100_percent"
    PAUSED = "paused"
    ROLLED_BACK = "rolled_back"
    COMPLETED = "completed"


class CanaryAction(StrEnum):
    """Explicit operator or automation action applied to a canary."""

    START = "start"
    PROMOTE = "promote"
    PAUSE = "pause"
    RESUME = "resume"
    ABORT = "abort"


class RequestComplexity(StrEnum):
    """Explainable request class used for model selection."""

    SMALL = "small"
    LARGE = "large"


class RouteTarget(BaseModel):
    """Immutable release identity selected by a route."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    release_id: UUID
    agent_version_id: UUID
    agent_version: SemanticVersion
    provenance_hash: Sha256


class TrafficAllocation(BaseModel):
    """Complete atomic stable/candidate allocation snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stable: RouteTarget
    candidate: RouteTarget | None = None
    candidate_weight_basis_points: BasisPoints = 0

    @model_validator(mode="after")
    def validate_candidate_weight(self) -> TrafficAllocation:
        if self.candidate is None and self.candidate_weight_basis_points != 0:
            raise ValueError("Candidate weight requires a candidate release")
        if self.candidate is not None and self.candidate.release_id == self.stable.release_id:
            raise ValueError("Stable and candidate releases must differ")
        return self


class TrafficRoute(BaseModel):
    """One revisioned route per agent and environment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    agent_name: Slug
    environment: DeliveryEnvironment
    allocation: TrafficAllocation
    revision: int = Field(ge=1)
    created_by: str = Field(min_length=2, max_length=200)
    created_at: datetime
    updated_by: str = Field(min_length=2, max_length=200)
    updated_at: datetime


class CreateTrafficRouteRequest(BaseModel):
    """Idempotent initial stable/candidate allocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: IdempotencyKey
    agent_name: Slug
    environment: DeliveryEnvironment
    stable_release_id: UUID
    candidate_release_id: UUID | None = None
    candidate_weight_basis_points: BasisPoints = 0
    actor: str = Field(min_length=2, max_length=200)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]

    @model_validator(mode="after")
    def validate_candidate_weight(self) -> CreateTrafficRouteRequest:
        if self.candidate_release_id is None and self.candidate_weight_basis_points != 0:
            raise ValueError("Candidate weight requires a candidate release")
        if self.candidate_release_id == self.stable_release_id:
            raise ValueError("Stable and candidate releases must differ")
        return self


class ReplaceTrafficRouteRequest(BaseModel):
    """Full intended route state guarded by optimistic concurrency."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: IdempotencyKey
    expected_revision: int = Field(ge=1)
    stable_release_id: UUID
    candidate_release_id: UUID | None = None
    candidate_weight_basis_points: BasisPoints = 0
    actor: str = Field(min_length=2, max_length=200)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]

    @model_validator(mode="after")
    def validate_candidate_weight(self) -> ReplaceTrafficRouteRequest:
        if self.candidate_release_id is None and self.candidate_weight_basis_points != 0:
            raise ValueError("Candidate weight requires a candidate release")
        if self.candidate_release_id == self.stable_release_id:
            raise ValueError("Stable and candidate releases must differ")
        return self


class TrafficRouteResult(BaseModel):
    """Creation result distinguishing a new route from an idempotent replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    created: bool
    route: TrafficRoute


class TrafficRouteEvent(BaseModel):
    """Append-only evidence for one atomic allocation change."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    route_id: UUID
    event_type: str
    actor: str
    reason: str
    idempotency_key: IdempotencyKey
    previous_revision: int | None
    new_revision: int = Field(ge=1)
    previous_allocation: TrafficAllocation | None
    new_allocation: TrafficAllocation
    occurred_at: datetime


class RouteDecision(BaseModel):
    """Explainable deterministic selection without retaining the raw routing key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    route_id: UUID
    route_revision: int = Field(ge=1)
    assignment_hash: Sha256
    cohort_basis_point: int = Field(ge=0, lt=10_000)
    lane: RouteLane
    target: RouteTarget
    reason: str = Field(min_length=3, max_length=300)


class ShadowPairRecord(BaseModel):
    """Redacted, paired production and shadow execution evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    correlation_id: str = Field(min_length=1, max_length=200)
    route_id: UUID
    route_revision: int = Field(ge=1)
    stable_release_id: UUID
    candidate_release_id: UUID
    request_hash: Sha256
    request_redacted: bool
    stable_response: AgentResponse
    candidate_response: AgentResponse | None
    shadow_status: ShadowStatus
    shadow_error_code: str | None = Field(default=None, max_length=100)
    stable_latency_ms: float = Field(ge=0)
    shadow_latency_ms: float = Field(ge=0)
    recorded_at: datetime
    source: Literal["shadow"] = "shadow"

    @model_validator(mode="after")
    def validate_shadow_outcome(self) -> ShadowPairRecord:
        succeeded = self.shadow_status is ShadowStatus.SUCCEEDED
        if succeeded != (self.candidate_response is not None):
            raise ValueError("Only successful shadow records may contain a candidate response")
        if succeeded and self.shadow_error_code is not None:
            raise ValueError("Successful shadow records cannot contain an error code")
        return self


class ResponseAssessment(BaseModel):
    """Pluggable normalized quality and safety judgment for one response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quality: float = Field(ge=0, le=1)
    safety: float = Field(ge=0, le=1)


class MetricDelta(BaseModel):
    """Candidate-minus-stable delta with a 95% confidence interval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    samples: int = Field(ge=0)
    stable_mean: float
    candidate_mean: float
    delta: float
    confidence_low: float
    confidence_high: float
    unit: Literal["score", "milliseconds", "rate", "usd"]
    lower_is_better: bool


class ShadowComparison(BaseModel):
    """Aggregate evidence for one stable/candidate release pairing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    route_id: UUID
    route_revisions: list[int] = Field(min_length=1)
    stable_release_id: UUID
    candidate_release_id: UUID
    sample_count: int = Field(ge=1)
    successful_sample_count: int = Field(ge=0)
    window_start: datetime
    window_end: datetime
    quality: MetricDelta
    safety: MetricDelta
    latency: MetricDelta
    error_rate: MetricDelta
    cost: MetricDelta


class CanaryProgress(BaseModel):
    """Current canary state with enough evidence to resume a paused rollout."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: CanaryState = CanaryState.PENDING
    resume_state: CanaryState | None = None

    @model_validator(mode="after")
    def validate_resume_state(self) -> CanaryProgress:
        resumable = {
            CanaryState.PENDING,
            CanaryState.FIVE_PERCENT,
            CanaryState.TWENTY_FIVE_PERCENT,
            CanaryState.FIFTY_PERCENT,
            CanaryState.ONE_HUNDRED_PERCENT,
        }
        if self.state is CanaryState.PAUSED and self.resume_state not in resumable:
            raise ValueError("Paused canaries require their last active state")
        if self.state is not CanaryState.PAUSED and self.resume_state is not None:
            raise ValueError("Only paused canaries may contain a resume state")
        return self


class CanaryGuardrailPolicy(BaseModel):
    """Minimum evidence and maximum regressions required for promotion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_samples: int = Field(default=100, ge=1)
    min_successful_samples: int = Field(default=95, ge=1)
    min_window_seconds: float = Field(default=300, gt=0)
    max_telemetry_age_seconds: float = Field(default=120, gt=0)
    min_quality_delta: float = Field(default=-0.02, ge=-1, le=1)
    min_safety_delta: float = Field(default=0, ge=-1, le=1)
    max_latency_delta_ms: float = Field(default=100, ge=0)
    max_error_rate_delta: float = Field(default=0.01, ge=0, le=1)
    max_cost_delta_usd: float = Field(default=0.005, ge=0)

    @model_validator(mode="after")
    def validate_sample_thresholds(self) -> CanaryGuardrailPolicy:
        if self.min_successful_samples > self.min_samples:
            raise ValueError("Successful sample requirement cannot exceed total samples")
        return self


class GuardrailCheck(BaseModel):
    """One explainable promotion requirement and its observed result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=2, max_length=100)
    passed: bool
    observed: float | int | bool | None
    operator: Literal[">=", "<=", "present", "healthy"]
    threshold: float | int | bool | None
    reason: str = Field(min_length=3, max_length=300)


class CanaryGateDecision(BaseModel):
    """Complete evidence explaining whether a canary may advance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    checks: list[GuardrailCheck] = Field(min_length=1)
    reasons: list[str]
    evaluated_at: datetime


class CreateCanaryRequest(BaseModel):
    """Start tracking a zero-weight candidate on an existing route."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: IdempotencyKey
    route_id: UUID
    expected_route_revision: int = Field(ge=1)
    actor: str = Field(min_length=2, max_length=200)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class CanaryActionRequest(BaseModel):
    """Optimistic manual canary action with server-evaluated evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: IdempotencyKey
    action: CanaryAction
    expected_revision: int = Field(ge=1)
    expected_route_revision: int = Field(ge=1)
    actor: str = Field(min_length=2, max_length=200)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
    comparison: ShadowComparison | None = None
    telemetry_healthy: bool = False
    guardrail_policy: CanaryGuardrailPolicy = Field(default_factory=CanaryGuardrailPolicy)


class CanaryRollout(BaseModel):
    """Durable rollout state tied to immutable stable and candidate releases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    route_id: UUID
    stable_release_id: UUID
    candidate_release_id: UUID
    progress: CanaryProgress
    revision: int = Field(ge=1)
    route_revision: int = Field(ge=1)
    latest_gate: CanaryGateDecision | None = None
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


class CanaryResult(BaseModel):
    """Creation result distinguishing a new rollout from an idempotent replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    created: bool
    rollout: CanaryRollout


class CanaryEvent(BaseModel):
    """Append-only audit record for one accepted rollout action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    rollout_id: UUID
    event_type: str
    action: CanaryAction | None
    actor: str
    reason: str
    idempotency_key: IdempotencyKey
    previous_progress: CanaryProgress | None
    new_progress: CanaryProgress
    previous_revision: int | None
    new_revision: int = Field(ge=1)
    previous_route_revision: int
    new_route_revision: int
    gate: CanaryGateDecision | None
    occurred_at: datetime


class ComplexitySignal(BaseModel):
    """One deterministic feature contributing to a complexity score."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=2, max_length=100)
    matched: bool
    weight: int = Field(ge=0, le=10)
    explanation: str = Field(min_length=3, max_length=300)


class ComplexityAssessment(BaseModel):
    """Auditable classifier output with no hidden model judgment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    complexity: RequestComplexity
    score: int = Field(ge=0, le=100)
    threshold: int = Field(ge=1, le=100)
    signals: list[ComplexitySignal] = Field(min_length=1)
    reason: str = Field(min_length=3, max_length=500)


class ModelCostProfile(BaseModel):
    """Policy-approved model quality and token pricing evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=3, max_length=200)
    quality_score: float = Field(ge=0, le=1)
    input_cost_per_million: float = Field(ge=0)
    output_cost_per_million: float = Field(ge=0)


class CostRoutingPolicy(BaseModel):
    """Governed small/large model routing configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    complexity_threshold: int = Field(default=3, ge=1, le=100)
    minimum_quality_score: float = Field(default=0.8, ge=0, le=1)
    small_model: ModelCostProfile
    large_model: ModelCostProfile

    @model_validator(mode="after")
    def validate_distinct_models(self) -> CostRoutingPolicy:
        if self.small_model.model == self.large_model.model:
            raise ValueError("Small and large model profiles must differ")
        return self


class CostRouteDecision(BaseModel):
    """Explainable quality-constrained model choice and estimated spend."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selected_model: str
    selected_quality_score: float = Field(ge=0, le=1)
    classification: ComplexityAssessment
    estimated_input_tokens: int = Field(ge=1)
    requested_output_tokens: int = Field(ge=1)
    estimated_cost_usd: float = Field(ge=0)
    alternative_model: str
    alternative_cost_usd: float = Field(ge=0)
    estimated_savings_usd: float
    reason: str = Field(min_length=3, max_length=500)


class CostRecommendationRequest(BaseModel):
    """Bounded request for an explainable model-cost recommendation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: AgentRequest
    policy: CostRoutingPolicy
    requested_output_tokens: int = Field(default=800, ge=1, le=100_000)


class GuardrailPreviewRequest(BaseModel):
    """Preview promotion policy without mutating rollout state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    comparison: ShadowComparison | None = None
    telemetry_healthy: bool = False
    policy: CanaryGuardrailPolicy = Field(default_factory=CanaryGuardrailPolicy)


class DeliveryOverview(BaseModel):
    """Operator dashboard payload for routes, canaries, guardrails, and spend."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    generated_at: datetime
    routes: list[TrafficRoute]
    canaries: list[CanaryRollout]
    guardrail_policy: CanaryGuardrailPolicy
    costs: CostAttributionReport
