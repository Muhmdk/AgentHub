"""Typed contracts for operational incident detection and durable intake."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from packages.contracts.delivery import DeliveryEnvironment
from packages.contracts.manifest import Slug
from packages.contracts.release import IdempotencyKey, Sha256
from packages.contracts.runtime import JsonValue

SignalName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=2,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_.-]+$",
    ),
]


class IncidentTriggerType(StrEnum):
    """Operational conditions capable of opening an incident."""

    SLO_BURN = "slo_burn"
    QUALITY_REGRESSION = "quality_regression"
    ERROR_RATE = "error_rate"
    COST_ANOMALY = "cost_anomaly"
    SAFETY_VIOLATION = "safety_violation"
    CANARY_GUARDRAIL_FAILURE = "canary_guardrail_failure"


class IncidentSeverity(StrEnum):
    """Bounded severities accepted by the incident control plane."""

    WARNING = "warning"
    CRITICAL = "critical"


class IncidentStatus(StrEnum):
    """Incident lifecycle states used across investigation and recovery."""

    DETECTED = "detected"
    INVESTIGATING = "investigating"
    AWAITING_APPROVAL = "awaiting_approval"
    ROLLING_BACK = "rolling_back"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class EvidenceKind(StrEnum):
    """Bounded evidence sources accepted by the incident investigator."""

    METRIC = "metric"
    TRACE = "trace"
    SANITIZED_LOG = "sanitized_log"
    DEPLOYMENT = "deployment"
    CONFIG_DIFF = "config_diff"
    EVALUATION = "evaluation"
    KUBERNETES_EVENT = "kubernetes_event"
    POLICY_DECISION = "policy_decision"
    PRIOR_INCIDENT = "prior_incident"


class IncidentSignal(BaseModel):
    """Sanitized operational measurement evaluated by deterministic rules."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: IdempotencyKey
    trigger_type: IncidentTriggerType
    severity: IncidentSeverity
    agent_name: Slug
    environment: DeliveryEnvironment
    signal_name: SignalName
    observed_value: float = Field(allow_inf_nan=False)
    threshold: float = Field(allow_inf_nan=False)
    observed_at: datetime
    source_ref: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
    release_id: UUID | None = None
    route_id: UUID | None = None
    canary_rollout_id: UUID | None = None

    @model_validator(mode="after")
    def validate_incident_signal(self) -> IncidentSignal:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("Incident signal timestamps must be timezone-aware")
        if (
            self.trigger_type is IncidentTriggerType.CANARY_GUARDRAIL_FAILURE
            and self.canary_rollout_id is None
        ):
            raise ValueError("Canary guardrail signals require a rollout identifier")
        return self


class TriggerEvaluation(BaseModel):
    """Explainable deterministic decision for one operational signal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    breached: bool
    operator: Literal["<", ">", ">="]
    observed_value: float = Field(allow_inf_nan=False)
    threshold: float = Field(allow_inf_nan=False)
    reason: str = Field(min_length=3, max_length=300)


class IncidentTrigger(BaseModel):
    """Append-only trigger evidence attached to an incident."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    incident_id: UUID
    trigger_type: IncidentTriggerType
    severity: IncidentSeverity
    signal_name: SignalName
    observed_value: float
    threshold: float
    operator: Literal["<", ">", ">="]
    source_ref: str
    summary: str
    release_id: UUID | None = None
    route_id: UUID | None = None
    canary_rollout_id: UUID | None = None
    idempotency_key: IdempotencyKey
    fingerprint: Sha256
    occurred_at: datetime
    recorded_at: datetime


class Incident(BaseModel):
    """Durable incident opened from one breached operational signal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    agent_name: Slug
    environment: DeliveryEnvironment
    title: str = Field(min_length=3, max_length=300)
    status: IncidentStatus
    severity: IncidentSeverity
    release_id: UUID | None = None
    route_id: UUID | None = None
    canary_rollout_id: UUID | None = None
    revision: int = Field(ge=1)
    trigger_count: int = Field(ge=1)
    created_by: str = Field(min_length=2, max_length=200)
    detected_at: datetime
    created_at: datetime
    updated_at: datetime


class IncidentResult(BaseModel):
    """Idempotent incident creation result with its originating trigger."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    created: bool
    incident: Incident
    trigger: IncidentTrigger


class EvidenceInput(BaseModel):
    """Sanitized source item ready for content-addressed persistence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: IdempotencyKey
    kind: EvidenceKind
    source_ref: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
    occurred_at: datetime
    subject_id: str | None = Field(default=None, min_length=1, max_length=200)
    attributes: dict[str, JsonValue] = Field(default_factory=dict, max_length=100)

    @model_validator(mode="after")
    def validate_evidence_time(self) -> EvidenceInput:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("Evidence timestamps must be timezone-aware")
        return self


class IncidentEvidence(BaseModel):
    """Immutable incident evidence with a canonical content hash."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    incident_id: UUID
    kind: EvidenceKind
    source_ref: str
    summary: str
    occurred_at: datetime
    subject_id: str | None = None
    attributes: dict[str, JsonValue]
    content_hash: Sha256
    idempotency_key: IdempotencyKey
    collected_by: str = Field(min_length=2, max_length=200)
    collected_at: datetime


class EvidenceCollectionResult(BaseModel):
    """Idempotent result for one evidence item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    created: bool
    evidence: IncidentEvidence


class TimelineEntry(BaseModel):
    """One source-linked, content-addressed event on an incident timeline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: UUID
    category: Literal["trigger", "evidence"]
    kind: str = Field(min_length=2, max_length=100)
    source_ref: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=3, max_length=500)
    occurred_at: datetime
    normalized_at: datetime
    recorded_at: datetime
    content_hash: Sha256
    subject_id: str | None = Field(default=None, min_length=1, max_length=200)
    clock_skew_seconds: float = Field(default=0, ge=0)


class IncidentTimeline(BaseModel):
    """Deterministic time ordering with explicit evidence-quality warnings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: UUID
    generated_at: datetime
    entries: list[TimelineEntry]
    missing_sources: list[EvidenceKind]
    warnings: list[str]
    clock_skew_detected: bool


class IncidentDetection(BaseModel):
    """A non-breach decision or a persisted incident result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    detected: bool
    evaluation: TriggerEvaluation
    result: IncidentResult | None = None

    @model_validator(mode="after")
    def validate_result_presence(self) -> IncidentDetection:
        if self.detected != (self.result is not None):
            raise ValueError("Detected signals require exactly one persisted incident result")
        if self.detected != self.evaluation.breached:
            raise ValueError("Detection and trigger evaluation must agree")
        return self


class ObserveIncidentSignalRequest(BaseModel):
    """Authenticated request to evaluate and persist an operational signal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal: IncidentSignal
    actor: str = Field(min_length=2, max_length=200)
