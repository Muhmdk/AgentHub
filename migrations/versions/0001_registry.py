"""Create immutable registry and append-only audit tables.

Revision ID: 0001_registry
Revises: None
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_registry"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LIFECYCLE_STATES = (
    "draft",
    "registered",
    "evaluating",
    "approved",
    "rejected",
    "staged",
    "canary",
    "production",
    "retired",
    "rolled_back",
)


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=63), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("risk_tier", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_agents_name"),
        sa.CheckConstraint(
            "risk_tier IN ('low', 'medium', 'high', 'critical')",
            name="ck_agents_risk_tier",
        ),
    )
    lifecycle_values = ", ".join(f"'{state}'" for state in LIFECYCLE_STATES)
    op.create_table(
        "agent_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_repository", sa.String(length=500), nullable=False),
        sa.Column("source_sha", sa.String(length=40), nullable=False),
        sa.Column("image_reference", sa.String(length=512), nullable=False),
        sa.Column("prompt_id", sa.String(length=63), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("model_provider", sa.String(length=63), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("model_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tool_specs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("retrieval_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("lifecycle_state", sa.String(length=32), nullable=False),
        sa.Column("state_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),
        sa.UniqueConstraint("manifest_hash", name="uq_agent_versions_manifest_hash"),
        sa.CheckConstraint("state_revision >= 1", name="ck_agent_versions_state_revision"),
        sa.CheckConstraint("length(source_sha) = 40", name="ck_agent_versions_source_sha"),
        sa.CheckConstraint("length(manifest_hash) = 64", name="ck_agent_versions_manifest_hash"),
        sa.CheckConstraint(
            f"lifecycle_state IN ({lifecycle_values})", name="ck_agent_versions_lifecycle_state"
        ),
        sa.CheckConstraint(
            "image_reference ~ '@sha256:[0-9a-f]{64}$'",
            name="ck_agent_versions_image_digest",
        ),
    )
    op.create_index(
        "ix_agent_versions_agent_created",
        "agent_versions",
        ["agent_id", "created_at"],
    )
    op.execute(
        """
        CREATE FUNCTION prevent_agent_version_identity_mutation() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'agent versions are immutable';
          END IF;
          IF (to_jsonb(NEW) - ARRAY['lifecycle_state', 'state_revision'])
             IS DISTINCT FROM
             (to_jsonb(OLD) - ARRAY['lifecycle_state', 'state_revision']) THEN
            RAISE EXCEPTION 'agent version metadata is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER agent_versions_immutable_identity
        BEFORE UPDATE OR DELETE ON agent_versions
        FOR EACH ROW EXECUTE FUNCTION prevent_agent_version_identity_mutation()
        """
    )
    op.create_table(
        "registry_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_state", sa.String(length=32), nullable=True),
        sa.Column("new_state", sa.String(length=32), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("length(manifest_hash) = 64", name="ck_audit_manifest_hash"),
        sa.CheckConstraint(f"new_state IN ({lifecycle_values})", name="ck_audit_new_state"),
        sa.CheckConstraint(
            f"previous_state IS NULL OR previous_state IN ({lifecycle_values})",
            name="ck_audit_previous_state",
        ),
    )
    op.create_index(
        "ix_registry_audit_version_time",
        "registry_audit_events",
        ["agent_version_id", "occurred_at"],
    )
    op.execute(
        """
        CREATE FUNCTION prevent_registry_audit_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'registry audit events are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER registry_audit_events_append_only
        BEFORE UPDATE OR DELETE ON registry_audit_events
        FOR EACH ROW EXECUTE FUNCTION prevent_registry_audit_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS registry_audit_events_append_only ON registry_audit_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_registry_audit_mutation")
    op.drop_index("ix_registry_audit_version_time", table_name="registry_audit_events")
    op.drop_table("registry_audit_events")
    op.execute("DROP TRIGGER IF EXISTS agent_versions_immutable_identity ON agent_versions")
    op.execute("DROP FUNCTION IF EXISTS prevent_agent_version_identity_mutation")
    op.drop_index("ix_agent_versions_agent_created", table_name="agent_versions")
    op.drop_table("agent_versions")
    op.drop_table("agents")
