"""SQLAlchemy records for release lineage and append-only promotion events."""

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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.registry.database import RegistryBase
from packages.registry.models import utc_now


class ReleaseRecord(RegistryBase):
    __tablename__ = "releases"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_releases_idempotency_key"),
        UniqueConstraint("provenance_hash", name="uq_releases_provenance_hash"),
        CheckConstraint("state_revision >= 1", name="ck_releases_state_revision"),
        CheckConstraint(
            "state IN ('evaluated', 'approved', 'staged', 'production', 'rejected', 'failed')",
            name="ck_releases_state",
        ),
        CheckConstraint("length(fingerprint) = 64", name="ck_releases_fingerprint"),
        CheckConstraint("length(provenance_hash) = 64", name="ck_releases_provenance_hash"),
        Index("ix_releases_agent_created", "agent_version_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    evaluation_run_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("evaluation_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    agent_name: Mapped[str] = mapped_column(String(63), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    state_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    security: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    gate: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ReleaseEventRecord(RegistryBase):
    __tablename__ = "release_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_release_events_idempotency_key"),
        CheckConstraint("length(provenance_hash) = 64", name="ck_release_events_provenance_hash"),
        CheckConstraint(
            "new_state IN ('evaluated', 'approved', 'staged', 'production', 'rejected', 'failed')",
            name="ck_release_events_new_state",
        ),
        CheckConstraint(
            "previous_state IS NULL OR previous_state IN "
            "('evaluated', 'approved', 'staged', 'production', 'rejected', 'failed')",
            name="ck_release_events_previous_state",
        ),
        Index("ix_release_events_release_time", "release_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("releases.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    previous_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_state: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    provenance_hash: Mapped[str] = mapped_column(String(64), nullable=False)
