"""Create append-only sanitized governance audit events.

Revision ID: 0004_governance_audit
Revises: 0003_releases
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_governance_audit"
down_revision: str | None = "0003_releases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "governance_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("identity", sa.String(length=128), nullable=False),
        sa.Column("agent_name", sa.String(length=63), nullable=False),
        sa.Column("agent_version", sa.String(length=64), nullable=False),
        sa.Column("action_kind", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=200), nullable=False),
        sa.Column("policy_bundle_version", sa.String(length=128), nullable=False),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("obligations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("release_id", sa.String(length=128), nullable=True),
        sa.Column("sanitized_input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('policy_decision', 'runtime_enforcement')",
            name="ck_governance_audit_event_type",
        ),
        sa.CheckConstraint(
            "outcome IN ('allow', 'deny', 'policy_unavailable', 'rate_limited', 'budget_exceeded')",
            name="ck_governance_audit_outcome",
        ),
    )
    op.create_index(
        "ix_governance_audit_agent_time",
        "governance_audit_events",
        ["agent_name", "occurred_at"],
    )
    op.create_index(
        "ix_governance_audit_correlation",
        "governance_audit_events",
        ["correlation_id"],
    )
    op.execute(
        """
        CREATE FUNCTION prevent_governance_audit_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'governance audit events are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER governance_audit_events_append_only
        BEFORE UPDATE OR DELETE ON governance_audit_events
        FOR EACH ROW EXECUTE FUNCTION prevent_governance_audit_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS governance_audit_events_append_only ON governance_audit_events"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_governance_audit_mutation")
    op.drop_index("ix_governance_audit_correlation", table_name="governance_audit_events")
    op.drop_index("ix_governance_audit_agent_time", table_name="governance_audit_events")
    op.drop_table("governance_audit_events")
