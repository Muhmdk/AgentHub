"""SQLAlchemy records for immutable registry versions and append-only audits."""

from datetime import UTC, datetime
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

from packages.contracts.registry import LifecycleState
from packages.registry.database import RegistryBase


def utc_now() -> datetime:
    return datetime.now(UTC)


class AgentRecord(RegistryBase):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("name", name="uq_agents_name"),
        CheckConstraint(
            "risk_tier IN ('low', 'medium', 'high', 'critical')",
            name="ck_agents_risk_tier",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(63), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    owner: Mapped[str] = mapped_column(String(200), nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class AgentVersionRecord(RegistryBase):
    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),
        UniqueConstraint("manifest_hash", name="uq_agent_versions_manifest_hash"),
        CheckConstraint("state_revision >= 1", name="ck_agent_versions_state_revision"),
        CheckConstraint("length(source_sha) = 40", name="ck_agent_versions_source_sha"),
        CheckConstraint("length(manifest_hash) = 64", name="ck_agent_versions_manifest_hash"),
        CheckConstraint(
            "lifecycle_state IN ('draft', 'registered', 'evaluating', 'approved', "
            "'rejected', 'staged', 'canary', 'production', 'retired', 'rolled_back')",
            name="ck_agent_versions_lifecycle_state",
        ),
        CheckConstraint(
            "image_reference ~ '@sha256:[0-9a-f]{64}$'",
            name="ck_agent_versions_image_digest",
        ),
        Index("ix_agent_versions_agent_created", "agent_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_repository: Mapped[str] = mapped_column(String(500), nullable=False)
    source_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    image_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    prompt_id: Mapped[str] = mapped_column(String(63), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(63), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    tool_specs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    retrieval_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    lifecycle_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=LifecycleState.DRAFT.value
    )
    state_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class AuditEventRecord(RegistryBase):
    __tablename__ = "registry_audit_events"
    __table_args__ = (
        CheckConstraint("length(manifest_hash) = 64", name="ck_audit_manifest_hash"),
        CheckConstraint(
            "new_state IN ('draft', 'registered', 'evaluating', 'approved', 'rejected', "
            "'staged', 'canary', 'production', 'retired', 'rolled_back')",
            name="ck_audit_new_state",
        ),
        CheckConstraint(
            "previous_state IS NULL OR previous_state IN ('draft', 'registered', "
            "'evaluating', 'approved', 'rejected', 'staged', 'canary', 'production', "
            "'retired', 'rolled_back')",
            name="ck_audit_previous_state",
        ),
        Index("ix_registry_audit_version_time", "agent_version_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    previous_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_state: Mapped[str] = mapped_column(String(32), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
