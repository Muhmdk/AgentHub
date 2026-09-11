"""Contracts for atomic stable and candidate traffic routes."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from packages.contracts.manifest import SemanticVersion, Slug
from packages.contracts.release import IdempotencyKey, Sha256

BasisPoints = Annotated[int, Field(ge=0, le=10_000)]


class DeliveryEnvironment(StrEnum):
    """Traffic environments with durable release routing."""

    STAGING = "staging"
    PRODUCTION = "production"


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
