"""Public contracts for registry versions, lifecycle changes, and audit events."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from packages.contracts.manifest import AgentManifest, RiskTier, SemanticVersion, Slug
from packages.contracts.runtime import JsonValue


class LifecycleState(StrEnum):
    DRAFT = "draft"
    REGISTERED = "registered"
    EVALUATING = "evaluating"
    APPROVED = "approved"
    REJECTED = "rejected"
    STAGED = "staged"
    CANARY = "canary"
    PRODUCTION = "production"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"


Actor = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]


class AgentVersionView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    agent_id: UUID
    version: SemanticVersion
    manifest_hash: str
    manifest: AgentManifest
    lifecycle_state: LifecycleState
    state_revision: int = Field(ge=1)
    created_at: datetime


class RegistrationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    created: bool
    agent_version: AgentVersionView


class AgentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    name: Slug
    display_name: str
    owner: str
    risk_tier: RiskTier
    latest_version: SemanticVersion
    lifecycle_state: LifecycleState
    created_at: datetime


class LifecycleTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_state: LifecycleState
    actor: Actor
    reason: str | None = Field(default=None, min_length=3, max_length=500)
    expected_revision: int = Field(ge=1)


class AuditEventView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    agent_version_id: UUID
    event_type: str
    actor: Actor
    occurred_at: datetime
    previous_state: LifecycleState | None
    new_state: LifecycleState
    correlation_id: str
    manifest_hash: str
    details: dict[str, JsonValue]
