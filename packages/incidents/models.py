"""SQLAlchemy records for incidents and append-only operational triggers."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.registry.database import RegistryBase
from packages.registry.models import utc_now


class IncidentRecord(RegistryBase):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('detected', 'investigating', 'awaiting_approval', 'rolling_back', "
            "'verifying', 'resolved', 'escalated')",
            name="ck_incident_status",
        ),
        CheckConstraint("severity IN ('warning', 'critical')", name="ck_incident_severity"),
        CheckConstraint("environment IN ('staging', 'production')", name="ck_incident_environment"),
        CheckConstraint("revision >= 1", name="ck_incident_revision"),
        CheckConstraint("length(create_fingerprint) = 64", name="ck_incident_fingerprint"),
        UniqueConstraint("create_idempotency_key", name="uq_incident_create_key"),
        Index("ix_incidents_agent_status_created", "agent_name", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_name: Mapped[str] = mapped_column(String(63), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    release_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("releases.id", ondelete="RESTRICT"), nullable=True
    )
    route_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("traffic_routes.id", ondelete="RESTRICT"), nullable=True
    )
    canary_rollout_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("canary_rollouts.id", ondelete="RESTRICT"), nullable=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    create_idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    create_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class IncidentTriggerRecord(RegistryBase):
    __tablename__ = "incident_triggers"
    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('slo_burn', 'quality_regression', 'error_rate', "
            "'cost_anomaly', 'safety_violation', 'canary_guardrail_failure')",
            name="ck_incident_trigger_type",
        ),
        CheckConstraint("severity IN ('warning', 'critical')", name="ck_incident_trigger_severity"),
        CheckConstraint("operator IN ('<', '>', '>=')", name="ck_incident_trigger_operator"),
        CheckConstraint("length(fingerprint) = 64", name="ck_incident_trigger_fingerprint"),
        UniqueConstraint("idempotency_key", name="uq_incident_trigger_key"),
        Index("ix_incident_triggers_incident_time", "incident_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    incident_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False
    )
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    signal_name: Mapped[str] = mapped_column(String(100), nullable=False)
    observed_value: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    operator: Mapped[str] = mapped_column(String(2), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    release_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("releases.id", ondelete="RESTRICT"), nullable=True
    )
    route_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("traffic_routes.id", ondelete="RESTRICT"), nullable=True
    )
    canary_rollout_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("canary_rollouts.id", ondelete="RESTRICT"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class IncidentEvidenceRecord(RegistryBase):
    __tablename__ = "incident_evidence"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('metric', 'trace', 'sanitized_log', 'deployment', 'config_diff', "
            "'evaluation', 'kubernetes_event', 'policy_decision', 'prior_incident')",
            name="ck_incident_evidence_kind",
        ),
        CheckConstraint("length(content_hash) = 64", name="ck_incident_evidence_content_hash"),
        CheckConstraint("length(fingerprint) = 64", name="ck_incident_evidence_fingerprint"),
        UniqueConstraint("idempotency_key", name="uq_incident_evidence_key"),
        Index("ix_incident_evidence_incident_time", "incident_id", "occurred_at"),
        Index("ix_incident_evidence_content_hash", "content_hash"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    incident_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    attributes: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    collected_by: Mapped[str] = mapped_column(String(200), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class RollbackOperationRecord(RegistryBase):
    __tablename__ = "rollback_operations"
    __table_args__ = (
        CheckConstraint("mode IN ('automatic', 'manual')", name="ck_rollback_mode"),
        CheckConstraint(
            "status IN ('requested', 'executed', 'verifying', 'recovered', 'failed', 'escalated')",
            name="ck_rollback_status",
        ),
        CheckConstraint("attempt_number >= 1", name="ck_rollback_attempt"),
        CheckConstraint("length(command_hash) = 64", name="ck_rollback_command_hash"),
        CheckConstraint("length(fingerprint) = 64", name="ck_rollback_fingerprint"),
        UniqueConstraint("idempotency_key", name="uq_rollback_operation_key"),
        Index("ix_rollback_incident_created", "incident_id", "created_at"),
        Index(
            "uq_rollback_active_incident",
            "incident_id",
            unique=True,
            postgresql_where=text("status IN ('requested', 'executed', 'verifying')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    incident_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False
    )
    route_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("traffic_routes.id", ondelete="RESTRICT"), nullable=False
    )
    canary_rollout_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("canary_rollouts.id", ondelete="RESTRICT"), nullable=True
    )
    target_release_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("releases.id", ondelete="RESTRICT"), nullable=False
    )
    target_provenance_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    route_revision_before: Mapped[int] = mapped_column(Integer, nullable=False)
    route_revision_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verification_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovery_decision: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RollbackEventRecord(RegistryBase):
    __tablename__ = "rollback_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested', 'executed', 'verifying', 'recovered', 'failed', 'escalated')",
            name="ck_rollback_event_status",
        ),
        Index("ix_rollback_events_operation_time", "operation_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    operation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("rollback_operations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
