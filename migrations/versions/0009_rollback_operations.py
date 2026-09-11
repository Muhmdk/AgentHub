"""Create durable rollback operations and audit events.

Revision ID: 0009_rollback_operations
Revises: 0008_incident_evidence
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_rollback_operations"
down_revision: str | None = "0008_incident_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    statuses = "'requested', 'executed', 'verifying', 'recovered', 'failed', 'escalated'"
    op.create_table(
        "rollback_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canary_rollout_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_release_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_provenance_hash", sa.String(length=64), nullable=False),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("decision", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("route_revision_before", sa.Integer(), nullable=False),
        sa.Column("route_revision_after", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["route_id"], ["traffic_routes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["canary_rollout_id"], ["canary_rollouts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_release_id"], ["releases.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("idempotency_key", name="uq_rollback_operation_key"),
        sa.CheckConstraint("mode IN ('automatic', 'manual')", name="ck_rollback_mode"),
        sa.CheckConstraint(f"status IN ({statuses})", name="ck_rollback_status"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_rollback_attempt"),
        sa.CheckConstraint("length(command_hash) = 64", name="ck_rollback_command_hash"),
        sa.CheckConstraint("length(fingerprint) = 64", name="ck_rollback_fingerprint"),
    )
    op.create_index(
        "ix_rollback_incident_created",
        "rollback_operations",
        ["incident_id", "created_at"],
    )
    op.create_index(
        "uq_rollback_active_incident",
        "rollback_operations",
        ["incident_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('requested', 'executed', 'verifying')"),
    )
    op.create_table(
        "rollback_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["operation_id"], ["rollback_operations.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(f"status IN ({statuses})", name="ck_rollback_event_status"),
    )
    op.create_index(
        "ix_rollback_events_operation_time",
        "rollback_events",
        ["operation_id", "occurred_at"],
    )
    op.execute(
        """
        CREATE FUNCTION protect_rollback_operation_identity() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'rollback operations cannot be deleted'; END IF;
          IF ROW(NEW.id, NEW.incident_id, NEW.route_id, NEW.canary_rollout_id,
                 NEW.target_release_id, NEW.target_provenance_hash, NEW.command_hash,
                 NEW.idempotency_key, NEW.fingerprint, NEW.actor, NEW.created_at)
             IS DISTINCT FROM
             ROW(OLD.id, OLD.incident_id, OLD.route_id, OLD.canary_rollout_id,
                 OLD.target_release_id, OLD.target_provenance_hash, OLD.command_hash,
                 OLD.idempotency_key, OLD.fingerprint, OLD.actor, OLD.created_at)
          THEN RAISE EXCEPTION 'rollback operation identity is immutable'; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER rollback_operations_immutable_identity
        BEFORE UPDATE OR DELETE ON rollback_operations
        FOR EACH ROW EXECUTE FUNCTION protect_rollback_operation_identity()
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_rollback_event_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'rollback events are append-only'; END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER rollback_events_append_only
        BEFORE UPDATE OR DELETE ON rollback_events
        FOR EACH ROW EXECUTE FUNCTION prevent_rollback_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS rollback_events_append_only ON rollback_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_rollback_event_mutation")
    op.execute(
        "DROP TRIGGER IF EXISTS rollback_operations_immutable_identity ON rollback_operations"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_rollback_operation_identity")
    op.drop_index("ix_rollback_events_operation_time", table_name="rollback_events")
    op.drop_table("rollback_events")
    op.drop_index("uq_rollback_active_incident", table_name="rollback_operations")
    op.drop_index("ix_rollback_incident_created", table_name="rollback_operations")
    op.drop_table("rollback_operations")
