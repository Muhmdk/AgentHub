"""Typed contracts for operational incident detection and durable intake."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from packages.contracts.delivery import (
    CanaryRollout,
    DeliveryEnvironment,
    TrafficAllocation,
    TrafficRoute,
)
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


class FindingKind(StrEnum):
    """Deterministic analysis techniques used to construct incident claims."""

    CHANGE_CORRELATION = "change_correlation"
    SPAN_CONTRIBUTION = "span_contribution"
    METRIC_CO_MOVEMENT = "metric_co_movement"
    KNOWN_SIGNATURE = "known_signature"
    COUNTER_EVIDENCE = "counter_evidence"


class RecommendedIncidentAction(StrEnum):
    """Advisory outcomes; none are direct actuation commands."""

    MONITOR = "monitor"
    PAUSE_CANARY = "pause_canary"
    REQUEST_ROLLBACK = "request_rollback"
    ESCALATE = "escalate"


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


class EvidenceCitation(BaseModel):
    """Immutable source pointer required on every investigator claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: UUID
    source_ref: str = Field(min_length=1, max_length=500)
    content_hash: Sha256


class InvestigationClaim(BaseModel):
    """One bounded deterministic claim grounded in stored evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: FindingKind
    statement: str = Field(min_length=3, max_length=500)
    confidence: float = Field(ge=0, le=1)
    citations: list[EvidenceCitation] = Field(min_length=1, max_length=20)


class DeterministicInvestigation(BaseModel):
    """Heuristic findings and counter-evidence without generated inference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: UUID
    generated_at: datetime
    probable_cause: InvestigationClaim | None = None
    findings: list[InvestigationClaim]
    counter_evidence: list[InvestigationClaim]
    missing_evidence: list[EvidenceKind]


class DraftNarrativeClaim(BaseModel):
    """Structured model output referencing only supplied evidence identifiers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    statement: str = Field(min_length=3, max_length=500)
    uncertainty: Literal["low", "medium", "high"]
    citation_ids: list[UUID] = Field(min_length=1, max_length=20)


class InvestigatorDraft(BaseModel):
    """Bounded generated draft before citation and actuation-path validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    probable_cause: DraftNarrativeClaim | None = None
    observations: list[DraftNarrativeClaim] = Field(max_length=20)
    counter_evidence: list[DraftNarrativeClaim] = Field(max_length=20)
    blast_radius: DraftNarrativeClaim | None = None
    recommended_action: RecommendedIncidentAction
    recommendation_rationale: DraftNarrativeClaim


class NarrativeClaim(BaseModel):
    """Validated generated claim with resolved immutable citations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    statement: str = Field(min_length=3, max_length=500)
    uncertainty: Literal["low", "medium", "high"]
    citations: list[EvidenceCitation] = Field(min_length=1, max_length=20)


class InvestigatorRequest(BaseModel):
    """Read-only evidence packet supplied to an optional investigator model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: UUID
    deterministic: DeterministicInvestigation
    timeline: IncidentTimeline
    instructions: Literal[
        "Summarize only supplied evidence; cite every claim; state uncertainty; never actuate."
    ] = "Summarize only supplied evidence; cite every claim; state uncertainty; never actuate."


class IncidentInvestigationReport(BaseModel):
    """Citation-validated optional generated investigation report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: UUID
    probable_cause: NarrativeClaim | None = None
    observations: list[NarrativeClaim]
    counter_evidence: list[NarrativeClaim]
    blast_radius: NarrativeClaim | None = None
    recommended_action: RecommendedIncidentAction
    recommendation_rationale: NarrativeClaim
    missing_evidence: list[EvidenceKind]
    generated_by: str = Field(min_length=2, max_length=200)
    generated_at: datetime


class PrepareRollbackRequest(BaseModel):
    """Operator or automation request for one immutable known-good target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: IdempotencyKey
    incident_id: UUID
    route_id: UUID
    expected_route_revision: int = Field(ge=1)
    canary_rollout_id: UUID | None = None
    expected_canary_revision: int | None = Field(default=None, ge=1)
    target_release_id: UUID
    target_provenance_hash: Sha256
    actor: str = Field(min_length=2, max_length=200)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
    requested_at: datetime

    @model_validator(mode="after")
    def validate_rollback_revisions(self) -> PrepareRollbackRequest:
        if (self.canary_rollout_id is None) != (self.expected_canary_revision is None):
            raise ValueError("Canary rollback identity and revision must be provided together")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("Rollback request timestamps must be timezone-aware")
        return self


class RollbackCommand(BaseModel):
    """Validated control-plane command with no generated actuation surface."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command_hash: Sha256
    request: PrepareRollbackRequest
    agent_name: Slug
    environment: DeliveryEnvironment
    previous_allocation: TrafficAllocation
    target_allocation: TrafficAllocation


class RollbackExecution(BaseModel):
    """Audited route and optional canary result after command execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command: RollbackCommand
    route: TrafficRoute
    canary: CanaryRollout | None = None
    executed_at: datetime


class RollbackMode(StrEnum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"


class RollbackStatus(StrEnum):
    REQUESTED = "requested"
    EXECUTED = "executed"
    VERIFYING = "verifying"
    RECOVERED = "recovered"
    FAILED = "failed"
    ESCALATED = "escalated"


class RecoveryOutcome(StrEnum):
    """Bounded result of post-rollback recovery verification."""

    PENDING = "pending"
    RECOVERED = "recovered"
    ESCALATED = "escalated"


class RecoveryPolicy(BaseModel):
    """Fixed-window health requirements evaluated after rollback execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_window_seconds: int = Field(default=300, ge=60, le=3600)
    min_observations: int = Field(default=5, ge=1, le=10_000)
    min_availability: float = Field(default=0.99, ge=0, le=1)
    max_error_rate: float = Field(default=0.01, ge=0, le=1)
    max_p95_latency_ms: float = Field(default=1000, gt=0, allow_inf_nan=False)


class RecoveryObservation(BaseModel):
    """Sanitized aggregate telemetry spanning a post-rollback window."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    window_start: datetime
    window_end: datetime
    observation_count: int = Field(ge=0)
    availability: float = Field(ge=0, le=1, allow_inf_nan=False)
    error_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    p95_latency_ms: float = Field(ge=0, allow_inf_nan=False)
    guardrail_healthy: bool
    telemetry_complete: bool
    source_refs: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_observation_window(self) -> RecoveryObservation:
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.window_start, self.window_end)
        ):
            raise ValueError("Recovery observation timestamps must be timezone-aware")
        if self.window_end <= self.window_start:
            raise ValueError("Recovery observation window must end after it starts")
        return self


class RecoveryCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=2, max_length=100)
    passed: bool
    reason: str = Field(min_length=3, max_length=300)


class RecoveryDecision(BaseModel):
    """Explainable recovery result persisted with the rollback operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: RecoveryOutcome
    checks: list[RecoveryCheck]
    reasons: list[str]
    source_refs: list[str]
    evaluated_at: datetime


class RollbackPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min_evidence_items: int = Field(default=3, ge=1, le=1000)
    cooldown_seconds: int = Field(default=900, ge=0, le=86_400)
    max_attempts: int = Field(default=3, ge=1, le=10)


class RollbackPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    canary_active: bool
    guardrail_breached: bool
    evidence_count: int = Field(ge=0)
    concurrent_rollout: bool = False
    ambiguous_cause: bool = False
    includes_data_migration: bool = False
    high_risk: bool = False
    human_approved: bool = False
    previous_attempts: int = Field(default=0, ge=0)
    last_attempt_at: datetime | None = None
    evaluated_at: datetime


class RollbackPolicyCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=2, max_length=100)
    passed: bool
    reason: str = Field(min_length=3, max_length=300)


class RollbackPolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    automatic: bool
    requires_approval: bool
    checks: list[RollbackPolicyCheck]
    reasons: list[str]
    evaluated_at: datetime


class RollbackOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    incident_id: UUID
    route_id: UUID
    canary_rollout_id: UUID | None = None
    target_release_id: UUID
    target_provenance_hash: Sha256
    command_hash: Sha256
    mode: RollbackMode
    status: RollbackStatus
    attempt_number: int = Field(ge=1)
    decision: RollbackPolicyDecision
    idempotency_key: IdempotencyKey
    actor: str
    reason: str
    route_revision_before: int = Field(ge=1)
    route_revision_after: int | None = Field(default=None, ge=1)
    verification_deadline: datetime | None = None
    recovery_decision: RecoveryDecision | None = None
    created_at: datetime
    updated_at: datetime


class RollbackReservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    created: bool
    operation: RollbackOperation


class CoordinatedRollbackResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    replayed: bool
    operation: RollbackOperation
    execution: RollbackExecution | None = None


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
