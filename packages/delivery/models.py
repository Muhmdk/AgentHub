"""SQLAlchemy records for atomic routes and append-only route events."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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


class TrafficRouteRecord(RegistryBase):
    __tablename__ = "traffic_routes"
    __table_args__ = (
        UniqueConstraint("agent_name", "environment", name="uq_traffic_route_agent_environment"),
        UniqueConstraint("create_idempotency_key", name="uq_traffic_route_create_key"),
        CheckConstraint("environment IN ('staging', 'production')", name="ck_route_environment"),
        CheckConstraint("revision >= 1", name="ck_route_revision"),
        CheckConstraint(
            "candidate_weight_basis_points BETWEEN 0 AND 10000",
            name="ck_route_candidate_weight",
        ),
        CheckConstraint(
            "candidate_release_id IS NOT NULL OR candidate_weight_basis_points = 0",
            name="ck_route_candidate_presence",
        ),
        CheckConstraint(
            "candidate_release_id IS NULL OR candidate_release_id <> stable_release_id",
            name="ck_route_distinct_targets",
        ),
        CheckConstraint("length(create_fingerprint) = 64", name="ck_route_create_fingerprint"),
        Index("ix_traffic_routes_stable_release", "stable_release_id"),
        Index("ix_traffic_routes_candidate_release", "candidate_release_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_name: Mapped[str] = mapped_column(String(63), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    stable_release_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("releases.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_release_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("releases.id", ondelete="RESTRICT"), nullable=True
    )
    candidate_weight_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    create_idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    create_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class TrafficRouteEventRecord(RegistryBase):
    __tablename__ = "traffic_route_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_traffic_route_event_key"),
        CheckConstraint("new_revision >= 1", name="ck_route_event_new_revision"),
        CheckConstraint(
            "previous_revision IS NULL OR previous_revision >= 1",
            name="ck_route_event_previous_revision",
        ),
        CheckConstraint("length(fingerprint) = 64", name="ck_route_event_fingerprint"),
        Index("ix_traffic_route_events_route_time", "route_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    route_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("traffic_routes.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_allocation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    new_allocation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class CanaryRolloutRecord(RegistryBase):
    __tablename__ = "canary_rollouts"
    __table_args__ = (
        UniqueConstraint("create_idempotency_key", name="uq_canary_create_key"),
        UniqueConstraint("route_id", "candidate_release_id", name="uq_canary_route_candidate"),
        CheckConstraint(
            "state IN ('pending', '5_percent', '25_percent', '50_percent', "
            "'100_percent', 'paused', 'rolled_back', 'completed')",
            name="ck_canary_state",
        ),
        CheckConstraint("revision >= 1", name="ck_canary_revision"),
        CheckConstraint("length(create_fingerprint) = 64", name="ck_canary_fingerprint"),
        CheckConstraint(
            "(state = 'paused' AND resume_state IN "
            "('pending', '5_percent', '25_percent', '50_percent', '100_percent')) OR "
            "(state <> 'paused' AND resume_state IS NULL)",
            name="ck_canary_resume_state",
        ),
        Index(
            "uq_canary_active_route",
            "route_id",
            unique=True,
            postgresql_where=text("state NOT IN ('rolled_back', 'completed')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    route_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("traffic_routes.id", ondelete="RESTRICT"), nullable=False
    )
    stable_release_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("releases.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_release_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("releases.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    resume_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_gate: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    create_idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    create_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class CanaryEventRecord(RegistryBase):
    __tablename__ = "canary_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_canary_event_key"),
        CheckConstraint("length(fingerprint) = 64", name="ck_canary_event_fingerprint"),
        CheckConstraint("new_revision >= 1", name="ck_canary_event_revision"),
        Index("ix_canary_events_rollout_time", "rollout_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    rollout_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("canary_rollouts.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_progress: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    new_progress: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    previous_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_route_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    new_route_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    gate: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
