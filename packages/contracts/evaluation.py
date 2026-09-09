"""Versioned evaluation datasets, suites, results, and release-gate contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from packages.contracts.manifest import SemanticVersion, Slug
from packages.contracts.runtime import AgentRequest, JsonValue, NonEmptyString

MetricName = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$", max_length=80),
]


class ExpectedToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonEmptyString
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class CaseExpectations(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    exact_answer: str | None = None
    answer_contains: list[str] = Field(default_factory=list)
    citation_source_ids: list[str] = Field(default_factory=list)
    expected_tools: list[ExpectedToolCall] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    forbidden_output_patterns: list[str] = Field(default_factory=list)
    max_latency_ms: float = Field(default=3000.0, gt=0)
    max_total_tokens: int = Field(default=1600, ge=0)
    max_cost_usd: float = Field(default=0.025, ge=0)


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: Slug
    category: Literal["quality", "safety", "performance"]
    request: AgentRequest
    expectations: CaseExpectations


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["agenthub.dev/evaluation-dataset/v1"]
    dataset_id: Slug
    version: SemanticVersion
    agent_name: Slug
    cases: list[EvaluationCase] = Field(min_length=1)


class EvaluatorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: MetricName
    version: SemanticVersion
    critical: bool = True
    kind: Literal["deterministic", "model"] = "deterministic"


class EvaluationSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["agenthub.dev/evaluation-suite/v1"]
    suite_id: Slug
    version: SemanticVersion
    dataset_id: Slug
    dataset_version: SemanticVersion
    evaluators: list[EvaluatorSpec] = Field(min_length=1)
    max_concurrency: int = Field(default=4, ge=1, le=32)
    case_timeout_seconds: float = Field(default=5.0, gt=0, le=120)
    gate_profile_id: Slug
    gate_profile_version: SemanticVersion


class MetricDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class RegressionMode(StrEnum):
    ABSOLUTE = "absolute"
    RELATIVE = "relative"


class MetricThreshold(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    direction: MetricDirection
    minimum: float | None = None
    maximum: float | None = None
    max_regression: float | None = Field(default=None, ge=0)
    regression_mode: RegressionMode = RegressionMode.ABSOLUTE

    @model_validator(mode="after")
    def require_limit(self) -> MetricThreshold:
        if self.minimum is None and self.maximum is None and self.max_regression is None:
            raise ValueError("Metric threshold must define an absolute or regression limit")
        return self


class GateProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["agenthub.dev/gate-profile/v1"]
    profile_id: Slug
    version: SemanticVersion
    thresholds: dict[MetricName, MetricThreshold] = Field(min_length=1)


class CaseExecutionStatus(StrEnum):
    COMPLETED = "completed"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class EvaluationRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CaseMetricResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: MetricName
    evaluator_version: SemanticVersion
    value: float | None = None
    error: str | None = None


class EvaluationCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: Slug
    status: CaseExecutionStatus
    input: dict[str, JsonValue]
    output: dict[str, JsonValue] | None
    latency_ms: float = Field(ge=0)
    metrics: list[CaseMetricResult]
    error_code: str | None = None
    error_message: str | None = None
    artifact_hash: str


class MetricAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: MetricName
    evaluator_version: SemanticVersion
    value: float
    case_count: int = Field(ge=0)
    error_count: int = Field(ge=0)


class GateReason(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    passed: bool
    message: str
    metric: MetricName | None = None
    candidate_value: float | None = None
    baseline_value: float | None = None
    threshold: float | None = None


class GateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    profile_id: Slug
    profile_version: SemanticVersion
    baseline_run_id: UUID | None = None
    reasons: list[GateReason]


class EvaluationRunReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    agent_name: Slug
    agent_version: SemanticVersion
    agent_version_id: UUID
    manifest_hash: str
    suite_id: Slug
    suite_version: SemanticVersion
    dataset_id: Slug
    dataset_version: SemanticVersion
    dataset_hash: str
    suite_hash: str
    gate_profile_hash: str
    environment: str
    provider_settings: dict[str, JsonValue]
    started_at: datetime
    completed_at: datetime
    status: EvaluationRunStatus
    replay_key: str
    case_results: list[EvaluationCaseResult]
    metrics: list[MetricAggregate]
    gate: GateDecision
    artifact_hash: str


class EvaluationRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    agent_name: Slug
    agent_version: SemanticVersion
    suite_id: Slug
    suite_version: SemanticVersion
    status: EvaluationRunStatus
    gate_passed: bool
    started_at: datetime
    completed_at: datetime
    artifact_hash: str


class RunEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_name: Slug
    agent_version: SemanticVersion
    suite_id: Slug
    candidate_profile: Literal["default", "regressed"] = "default"
    baseline_run_id: UUID | None = None
    environment: str = Field(default="local", min_length=1, max_length=64)
