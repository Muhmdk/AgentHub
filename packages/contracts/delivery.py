"""Contracts for atomic stable and candidate traffic routes."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from packages.contracts.manifest import SemanticVersion, Slug
from packages.contracts.release import IdempotencyKey, Sha256
from packages.contracts.runtime import AgentResponse

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
