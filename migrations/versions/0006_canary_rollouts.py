"""Create durable canary rollouts and append-only action events.

Revision ID: 0006_canary_rollouts
Revises: 0005_delivery_routes
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_canary_rollouts"
down_revision: str | None = "0005_delivery_routes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canary_rollouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stable_release_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_release_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("resume_state", sa.String(length=24), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("latest_gate", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("create_idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("create_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["route_id"], ["traffic_routes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stable_release_id"], ["releases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["candidate_release_id"], ["releases.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("create_idempotency_key", name="uq_canary_create_key"),
        sa.UniqueConstraint("route_id", "candidate_release_id", name="uq_canary_route_candidate"),
        sa.CheckConstraint(
            "state IN ('pending', '5_percent', '25_percent', '50_percent', "
            "'100_percent', 'paused', 'rolled_back', 'completed')",
            name="ck_canary_state",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_canary_revision"),
        sa.CheckConstraint("length(create_fingerprint) = 64", name="ck_canary_fingerprint"),
        sa.CheckConstraint(
            "(state = 'paused' AND resume_state IN "
            "('pending', '5_percent', '25_percent', '50_percent', '100_percent')) OR "
            "(state <> 'paused' AND resume_state IS NULL)",
            name="ck_canary_resume_state",
        ),
    )
    op.create_index(
        "uq_canary_active_route",
        "canary_rollouts",
        ["route_id"],
        unique=True,
        postgresql_where=sa.text("state NOT IN ('rolled_back', 'completed')"),
    )
    op.create_table(
        "canary_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("rollout_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=True),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("previous_progress", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_progress", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("previous_revision", sa.Integer(), nullable=True),
        sa.Column("new_revision", sa.Integer(), nullable=False),
        sa.Column("previous_route_revision", sa.Integer(), nullable=False),
        sa.Column("new_route_revision", sa.Integer(), nullable=False),
        sa.Column("gate", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["rollout_id"], ["canary_rollouts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("idempotency_key", name="uq_canary_event_key"),
        sa.CheckConstraint("length(fingerprint) = 64", name="ck_canary_event_fingerprint"),
        sa.CheckConstraint("new_revision >= 1", name="ck_canary_event_revision"),
    )
    op.create_index(
        "ix_canary_events_rollout_time",
        "canary_events",
        ["rollout_id", "occurred_at"],
    )
    op.execute(
        """
        CREATE FUNCTION protect_canary_identity() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'canary rollouts cannot be deleted';
          END IF;
          IF ROW(NEW.id, NEW.route_id, NEW.stable_release_id, NEW.candidate_release_id,
                 NEW.create_idempotency_key, NEW.create_fingerprint, NEW.created_by, NEW.created_at)
             IS DISTINCT FROM
             ROW(OLD.id, OLD.route_id, OLD.stable_release_id, OLD.candidate_release_id,
                 OLD.create_idempotency_key, OLD.create_fingerprint, OLD.created_by, OLD.created_at)
          THEN
            RAISE EXCEPTION 'canary rollout identity is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER canary_rollouts_immutable_identity
        BEFORE UPDATE OR DELETE ON canary_rollouts
        FOR EACH ROW EXECUTE FUNCTION protect_canary_identity()
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_canary_event_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'canary events are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER canary_events_append_only
        BEFORE UPDATE OR DELETE ON canary_events
        FOR EACH ROW EXECUTE FUNCTION prevent_canary_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS canary_events_append_only ON canary_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_canary_event_mutation")
    op.execute("DROP TRIGGER IF EXISTS canary_rollouts_immutable_identity ON canary_rollouts")
    op.execute("DROP FUNCTION IF EXISTS protect_canary_identity")
    op.drop_index("ix_canary_events_rollout_time", table_name="canary_events")
    op.drop_table("canary_events")
    op.drop_index("uq_canary_active_route", table_name="canary_rollouts")
    op.drop_table("canary_rollouts")
