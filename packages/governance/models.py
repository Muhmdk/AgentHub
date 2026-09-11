"""SQLAlchemy record for append-only governance decisions."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.registry.database import RegistryBase
from packages.registry.models import utc_now


class GovernanceAuditEventRecord(RegistryBase):
    __tablename__ = "governance_audit_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('policy_decision', 'runtime_enforcement')",
            name="ck_governance_audit_event_type",
        ),
        CheckConstraint(
            "outcome IN ('allow', 'deny', 'policy_unavailable', 'rate_limited', 'budget_exceeded')",
            name="ck_governance_audit_outcome",
        ),
        Index("ix_governance_audit_agent_time", "agent_name", "occurred_at"),
        Index("ix_governance_audit_correlation", "correlation_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    identity: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(63), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(64), nullable=False)
    action_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[str] = mapped_column(String(200), nullable=False)
    policy_bundle_version: Mapped[str] = mapped_column(String(128), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    obligations: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    release_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sanitized_input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
