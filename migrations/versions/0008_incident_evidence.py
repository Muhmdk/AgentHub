"""Create immutable content-addressed incident evidence.

Revision ID: 0008_incident_evidence
Revises: 0007_incidents
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_incident_evidence"
down_revision: str | None = "0007_incidents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incident_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject_id", sa.String(length=200), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("collected_by", sa.String(length=200), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("idempotency_key", name="uq_incident_evidence_key"),
        sa.CheckConstraint(
            "kind IN ('metric', 'trace', 'sanitized_log', 'deployment', 'config_diff', "
            "'evaluation', 'kubernetes_event', 'policy_decision', 'prior_incident')",
            name="ck_incident_evidence_kind",
        ),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_incident_evidence_content_hash"),
        sa.CheckConstraint("length(fingerprint) = 64", name="ck_incident_evidence_fingerprint"),
    )
    op.create_index(
        "ix_incident_evidence_incident_time",
        "incident_evidence",
        ["incident_id", "occurred_at"],
    )
    op.create_index(
        "ix_incident_evidence_content_hash",
        "incident_evidence",
        ["content_hash"],
    )
    op.execute(
        """
        CREATE FUNCTION prevent_incident_evidence_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'incident evidence is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER incident_evidence_append_only
        BEFORE UPDATE OR DELETE ON incident_evidence
        FOR EACH ROW EXECUTE FUNCTION prevent_incident_evidence_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS incident_evidence_append_only ON incident_evidence")
    op.execute("DROP FUNCTION IF EXISTS prevent_incident_evidence_mutation")
    op.drop_index("ix_incident_evidence_content_hash", table_name="incident_evidence")
    op.drop_index("ix_incident_evidence_incident_time", table_name="incident_evidence")
    op.drop_table("incident_evidence")
