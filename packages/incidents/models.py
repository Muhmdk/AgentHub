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
)
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
