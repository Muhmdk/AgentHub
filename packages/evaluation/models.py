"""SQLAlchemy records for immutable evaluation reports and comparisons."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.registry.database import RegistryBase


class EvaluationRunRecord(RegistryBase):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        CheckConstraint("status IN ('completed', 'failed')", name="ck_evaluation_runs_status"),
        CheckConstraint("length(manifest_hash) = 64", name="ck_evaluation_runs_manifest_hash"),
        CheckConstraint("length(dataset_hash) = 64", name="ck_evaluation_runs_dataset_hash"),
        CheckConstraint("length(suite_hash) = 64", name="ck_evaluation_runs_suite_hash"),
        CheckConstraint(
            "length(gate_profile_hash) = 64", name="ck_evaluation_runs_gate_profile_hash"
        ),
        CheckConstraint("length(replay_key) = 64", name="ck_evaluation_runs_replay_key"),
        CheckConstraint("length(artifact_hash) = 64", name="ck_evaluation_runs_artifact_hash"),
        Index("ix_evaluation_runs_agent_started", "agent_version_id", "started_at"),
        Index("ix_evaluation_runs_suite_started", "suite_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    suite_id: Mapped[str] = mapped_column(String(63), nullable=False)
    suite_version: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(63), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    suite_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    gate_profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    replay_key: Mapped[str] = mapped_column(String(64), nullable=False)
    gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class EvaluationCaseRecord(RegistryBase):
    __tablename__ = "evaluation_case_results"
    __table_args__ = (
        UniqueConstraint("evaluation_run_id", "case_id", name="uq_evaluation_cases_run_case"),
        CheckConstraint(
            "status IN ('completed', 'error', 'timeout', 'cancelled')",
            name="ck_evaluation_cases_status",
        ),
        CheckConstraint("latency_ms >= 0", name="ck_evaluation_cases_latency"),
        CheckConstraint("length(artifact_hash) = 64", name="ck_evaluation_cases_hash"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    evaluation_run_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("evaluation_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    case_id: Mapped[str] = mapped_column(String(63), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    metrics: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class EvaluationMetricRecord(RegistryBase):
    __tablename__ = "evaluation_metrics"
    __table_args__ = (
        UniqueConstraint("evaluation_run_id", "name", name="uq_evaluation_metrics_run_name"),
        CheckConstraint("case_count >= 0", name="ck_evaluation_metrics_case_count"),
        CheckConstraint("error_count >= 0", name="ck_evaluation_metrics_error_count"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    evaluation_run_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("evaluation_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    evaluator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False)


class EvaluationGateRecord(RegistryBase):
    __tablename__ = "evaluation_gate_decisions"
    __table_args__ = (UniqueConstraint("evaluation_run_id", name="uq_evaluation_gate_run"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    evaluation_run_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("evaluation_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    profile_id: Mapped[str] = mapped_column(String(63), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_run_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("evaluation_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
