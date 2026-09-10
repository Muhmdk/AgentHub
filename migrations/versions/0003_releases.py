"""Create immutable release lineage and append-only promotion events.

Revision ID: 0003_releases
Revises: 0002_evaluations
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_releases"
down_revision: str | None = "0002_evaluations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "releases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "evaluation_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evaluation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("agent_name", sa.String(length=63), nullable=False),
        sa.Column("agent_version", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("state_revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provenance_hash", sa.String(length=64), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("security", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("gate", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_releases_idempotency_key"),
        sa.UniqueConstraint("provenance_hash", name="uq_releases_provenance_hash"),
        sa.CheckConstraint("state_revision >= 1", name="ck_releases_state_revision"),
        sa.CheckConstraint(
            "state IN ('evaluated', 'approved', 'staged', 'production', 'rejected', 'failed')",
            name="ck_releases_state",
        ),
        sa.CheckConstraint("length(fingerprint) = 64", name="ck_releases_fingerprint"),
        sa.CheckConstraint("length(provenance_hash) = 64", name="ck_releases_provenance_hash"),
    )
    op.create_index("ix_releases_agent_created", "releases", ["agent_version_id", "created_at"])
    op.create_table(
        "release_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "release_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("releases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_state", sa.String(length=16), nullable=True),
        sa.Column("new_state", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("provenance_hash", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_release_events_idempotency_key"),
        sa.CheckConstraint(
            "new_state IN ('evaluated', 'approved', 'staged', 'production', 'rejected', 'failed')",
            name="ck_release_events_new_state",
        ),
        sa.CheckConstraint(
            "previous_state IS NULL OR previous_state IN "
            "('evaluated', 'approved', 'staged', 'production', 'rejected', 'failed')",
            name="ck_release_events_previous_state",
        ),
        sa.CheckConstraint(
            "length(provenance_hash) = 64", name="ck_release_events_provenance_hash"
        ),
    )
    op.create_index(
        "ix_release_events_release_time", "release_events", ["release_id", "occurred_at"]
    )
    op.execute(
        """
        CREATE FUNCTION protect_release_lineage() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'release lineage is immutable';
          END IF;
          IF ROW(
            NEW.agent_version_id, NEW.evaluation_run_id, NEW.agent_name, NEW.agent_version,
            NEW.idempotency_key, NEW.fingerprint, NEW.provenance_hash, NEW.provenance,
            NEW.security, NEW.policy, NEW.gate, NEW.created_by, NEW.created_at
          ) IS DISTINCT FROM ROW(
            OLD.agent_version_id, OLD.evaluation_run_id, OLD.agent_name, OLD.agent_version,
            OLD.idempotency_key, OLD.fingerprint, OLD.provenance_hash, OLD.provenance,
            OLD.security, OLD.policy, OLD.gate, OLD.created_by, OLD.created_at
          ) THEN
            RAISE EXCEPTION 'release lineage is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER releases_lineage_immutable
        BEFORE UPDATE OR DELETE ON releases
        FOR EACH ROW EXECUTE FUNCTION protect_release_lineage()
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_release_event_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'release events are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER release_events_immutable
        BEFORE UPDATE OR DELETE ON release_events
        FOR EACH ROW EXECUTE FUNCTION prevent_release_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS release_events_immutable ON release_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_release_event_mutation")
    op.execute("DROP TRIGGER IF EXISTS releases_lineage_immutable ON releases")
    op.execute("DROP FUNCTION IF EXISTS protect_release_lineage")
    op.drop_index("ix_release_events_release_time", table_name="release_events")
    op.drop_table("release_events")
    op.drop_index("ix_releases_agent_created", table_name="releases")
    op.drop_table("releases")
