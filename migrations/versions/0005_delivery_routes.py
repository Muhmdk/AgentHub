"""Create atomic traffic routes and append-only route events.

Revision ID: 0005_delivery_routes
Revises: 0004_governance_audit
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_delivery_routes"
down_revision: str | None = "0004_governance_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "traffic_routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_name", sa.String(length=63), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("stable_release_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_release_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_weight_basis_points", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("create_idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("create_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["stable_release_id"], ["releases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["candidate_release_id"], ["releases.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("agent_name", "environment", name="uq_traffic_route_agent_environment"),
        sa.UniqueConstraint("create_idempotency_key", name="uq_traffic_route_create_key"),
        sa.CheckConstraint("environment IN ('staging', 'production')", name="ck_route_environment"),
        sa.CheckConstraint("revision >= 1", name="ck_route_revision"),
        sa.CheckConstraint(
            "candidate_weight_basis_points BETWEEN 0 AND 10000",
            name="ck_route_candidate_weight",
        ),
        sa.CheckConstraint(
            "candidate_release_id IS NOT NULL OR candidate_weight_basis_points = 0",
            name="ck_route_candidate_presence",
        ),
        sa.CheckConstraint(
            "candidate_release_id IS NULL OR candidate_release_id <> stable_release_id",
            name="ck_route_distinct_targets",
        ),
        sa.CheckConstraint("length(create_fingerprint) = 64", name="ck_route_create_fingerprint"),
    )
    op.create_index("ix_traffic_routes_stable_release", "traffic_routes", ["stable_release_id"])
    op.create_index(
        "ix_traffic_routes_candidate_release", "traffic_routes", ["candidate_release_id"]
    )
    op.create_table(
        "traffic_route_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("previous_revision", sa.Integer(), nullable=True),
        sa.Column("new_revision", sa.Integer(), nullable=False),
        sa.Column("previous_allocation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_allocation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["route_id"], ["traffic_routes.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("idempotency_key", name="uq_traffic_route_event_key"),
        sa.CheckConstraint("new_revision >= 1", name="ck_route_event_new_revision"),
        sa.CheckConstraint(
            "previous_revision IS NULL OR previous_revision >= 1",
            name="ck_route_event_previous_revision",
        ),
        sa.CheckConstraint("length(fingerprint) = 64", name="ck_route_event_fingerprint"),
    )
    op.create_index(
        "ix_traffic_route_events_route_time",
        "traffic_route_events",
        ["route_id", "occurred_at"],
    )
    op.execute(
        """
        CREATE FUNCTION protect_traffic_route_identity() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'traffic routes cannot be deleted';
          END IF;
          IF ROW(NEW.id, NEW.agent_name, NEW.environment, NEW.create_idempotency_key,
                 NEW.create_fingerprint, NEW.created_by, NEW.created_at)
             IS DISTINCT FROM
             ROW(OLD.id, OLD.agent_name, OLD.environment, OLD.create_idempotency_key,
                 OLD.create_fingerprint, OLD.created_by, OLD.created_at) THEN
            RAISE EXCEPTION 'traffic route identity is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER traffic_routes_immutable_identity
        BEFORE UPDATE OR DELETE ON traffic_routes
        FOR EACH ROW EXECUTE FUNCTION protect_traffic_route_identity()
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_traffic_route_event_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'traffic route events are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER traffic_route_events_append_only
        BEFORE UPDATE OR DELETE ON traffic_route_events
        FOR EACH ROW EXECUTE FUNCTION prevent_traffic_route_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS traffic_route_events_append_only ON traffic_route_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_traffic_route_event_mutation")
    op.execute("DROP TRIGGER IF EXISTS traffic_routes_immutable_identity ON traffic_routes")
    op.execute("DROP FUNCTION IF EXISTS protect_traffic_route_identity")
    op.drop_index("ix_traffic_route_events_route_time", table_name="traffic_route_events")
    op.drop_table("traffic_route_events")
    op.drop_index("ix_traffic_routes_candidate_release", table_name="traffic_routes")
    op.drop_index("ix_traffic_routes_stable_release", table_name="traffic_routes")
    op.drop_table("traffic_routes")
