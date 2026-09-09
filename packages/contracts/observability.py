"""Versioned SLO, burn-rate, and fleet-health API contracts."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.contracts.manifest import SemanticVersion, Slug


class SLOIndicator(StrEnum):
    AVAILABILITY = "availability"
    LATENCY = "latency"
    TOOL_SUCCESS = "tool_success"
    GROUNDEDNESS = "groundedness"
    EVALUATION_PASS_RATE = "evaluation_pass_rate"
    COST = "cost"


class SLOObjective(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_id: Slug
    indicator: SLOIndicator
    target: float = Field(gt=0, le=1)
    window_seconds: int = Field(ge=300, le=2_678_400)
    threshold: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_threshold_for_threshold_indicators(self) -> SLOObjective:
        if self.indicator in {SLOIndicator.LATENCY, SLOIndicator.COST} and self.threshold is None:
            raise ValueError("Latency and cost objectives require a threshold")
        return self


class SLOProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["agenthub.dev/slo-profile/v1"]
    profile_id: Slug
    version: SemanticVersion
    objectives: list[SLOObjective] = Field(min_length=1)


class BurnRateWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    window_seconds: int = Field(gt=0)
    good_events: int = Field(ge=0)
    total_events: int = Field(ge=0)
    error_ratio: float | None = Field(default=None, ge=0, le=1)
    burn_rate: float | None = Field(default=None, ge=0)


class SLOStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_id: Slug
    indicator: SLOIndicator
    target: float
    threshold: float | None
    window_seconds: int
    good_events: int = Field(ge=0)
    total_events: int = Field(ge=0)
    compliance: float | None = Field(default=None, ge=0, le=1)
    error_budget_remaining: float | None = Field(default=None, ge=0, le=1)
    burn_windows: list[BurnRateWindow]
    alert_severity: Literal["critical", "warning"] | None = None


class AgentHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_name: Slug
    agent_version: str
    request_count: int = Field(ge=0)
    availability: float | None = Field(default=None, ge=0, le=1)
    p95_latency_ms: float | None = Field(default=None, ge=0)
    tool_success: float | None = Field(default=None, ge=0, le=1)
    groundedness: float | None = Field(default=None, ge=0, le=1)
    evaluation_pass_rate: float | None = Field(default=None, ge=0, le=1)
    mean_cost_usd: float | None = Field(default=None, ge=0)
    last_trace_id: str | None = None
    slos: list[SLOStatus]


class FleetHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generated_at: str
    profile_id: Slug
    profile_version: SemanticVersion
    agents: list[AgentHealth]
