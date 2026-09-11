"""Create durable incidents and append-only operational triggers.

Revision ID: 0007_incidents
Revises: 0006_canary_rollouts
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_incidents"
down_revision: str | None = "0006_canary_rollouts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_name", sa.String(length=63), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("release_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("canary_rollout_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("create_idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("create_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["releases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["route_id"], ["traffic_routes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["canary_rollout_id"], ["canary_rollouts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("create_idempotency_key", name="uq_incident_create_key"),
        sa.CheckConstraint(
            "status IN ('detected', 'investigating', 'awaiting_approval', 'rolling_back', "
            "'verifying', 'resolved', 'escalated')",
            name="ck_incident_status",
        ),
        sa.CheckConstraint("severity IN ('warning', 'critical')", name="ck_incident_severity"),
        sa.CheckConstraint(
            "environment IN ('staging', 'production')", name="ck_incident_environment"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_incident_revision"),
        sa.CheckConstraint("length(create_fingerprint) = 64", name="ck_incident_fingerprint"),
    )
    op.create_index(
        "ix_incidents_agent_status_created",
        "incidents",
        ["agent_name", "status", "created_at"],
    )
    op.create_table(
        "incident_triggers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("signal_name", sa.String(length=100), nullable=False),
        sa.Column("observed_value", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("operator", sa.String(length=2), nullable=False),
        sa.Column("source_ref", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("release_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("canary_rollout_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["release_id"], ["releases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["route_id"], ["traffic_routes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["canary_rollout_id"], ["canary_rollouts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("idempotency_key", name="uq_incident_trigger_key"),
        sa.CheckConstraint(
            "trigger_type IN ('slo_burn', 'quality_regression', 'error_rate', "
            "'cost_anomaly', 'safety_violation', 'canary_guardrail_failure')",
            name="ck_incident_trigger_type",
        ),
        sa.CheckConstraint(
            "severity IN ('warning', 'critical')", name="ck_incident_trigger_severity"
        ),
        sa.CheckConstraint("operator IN ('<', '>', '>=')", name="ck_incident_trigger_operator"),
        sa.CheckConstraint("length(fingerprint) = 64", name="ck_incident_trigger_fingerprint"),
    )
    op.create_index(
        "ix_incident_triggers_incident_time",
        "incident_triggers",
        ["incident_id", "occurred_at"],
    )
    op.execute(
        """
        CREATE FUNCTION protect_incident_identity() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'incidents cannot be deleted';
          END IF;
          IF ROW(NEW.id, NEW.agent_name, NEW.environment, NEW.release_id, NEW.route_id,
                 NEW.canary_rollout_id, NEW.create_idempotency_key, NEW.create_fingerprint,
                 NEW.created_by, NEW.detected_at, NEW.created_at)
             IS DISTINCT FROM
             ROW(OLD.id, OLD.agent_name, OLD.environment, OLD.release_id, OLD.route_id,
                 OLD.canary_rollout_id, OLD.create_idempotency_key, OLD.create_fingerprint,
                 OLD.created_by, OLD.detected_at, OLD.created_at)
          THEN
            RAISE EXCEPTION 'incident identity is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER incidents_immutable_identity
        BEFORE UPDATE OR DELETE ON incidents
        FOR EACH ROW EXECUTE FUNCTION protect_incident_identity()
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_incident_trigger_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'incident triggers are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER incident_triggers_append_only
        BEFORE UPDATE OR DELETE ON incident_triggers
        FOR EACH ROW EXECUTE FUNCTION prevent_incident_trigger_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS incident_triggers_append_only ON incident_triggers")
    op.execute("DROP FUNCTION IF EXISTS prevent_incident_trigger_mutation")
    op.execute("DROP TRIGGER IF EXISTS incidents_immutable_identity ON incidents")
    op.execute("DROP FUNCTION IF EXISTS protect_incident_identity")
    op.drop_index("ix_incident_triggers_incident_time", table_name="incident_triggers")
    op.drop_table("incident_triggers")
    op.drop_index("ix_incidents_agent_status_created", table_name="incidents")
    op.drop_table("incidents")
