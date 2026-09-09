"""Create immutable evaluation run, case, metric, and gate artifacts.

Revision ID: 0002_evaluations
Revises: 0001_registry
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_evaluations"
down_revision: str | None = "0001_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("suite_id", sa.String(length=63), nullable=False),
        sa.Column("suite_version", sa.String(length=64), nullable=False),
        sa.Column("dataset_id", sa.String(length=63), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("dataset_hash", sa.String(length=64), nullable=False),
        sa.Column("suite_hash", sa.String(length=64), nullable=False),
        sa.Column("gate_profile_hash", sa.String(length=64), nullable=False),
        sa.Column("environment", sa.String(length=64), nullable=False),
        sa.Column("provider_settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("replay_key", sa.String(length=64), nullable=False),
        sa.Column("gate_passed", sa.Boolean(), nullable=False),
        sa.Column("artifact_hash", sa.String(length=64), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("status IN ('completed', 'failed')", name="ck_evaluation_runs_status"),
        sa.CheckConstraint("length(manifest_hash) = 64", name="ck_evaluation_runs_manifest_hash"),
        sa.CheckConstraint("length(dataset_hash) = 64", name="ck_evaluation_runs_dataset_hash"),
        sa.CheckConstraint("length(suite_hash) = 64", name="ck_evaluation_runs_suite_hash"),
        sa.CheckConstraint(
            "length(gate_profile_hash) = 64", name="ck_evaluation_runs_gate_profile_hash"
        ),
        sa.CheckConstraint("length(replay_key) = 64", name="ck_evaluation_runs_replay_key"),
        sa.CheckConstraint("length(artifact_hash) = 64", name="ck_evaluation_runs_artifact_hash"),
    )
    op.create_index(
        "ix_evaluation_runs_agent_started",
        "evaluation_runs",
        ["agent_version_id", "started_at"],
    )
    op.create_index(
        "ix_evaluation_runs_suite_started",
        "evaluation_runs",
        ["suite_id", "started_at"],
    )
    op.create_table(
        "evaluation_case_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "evaluation_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evaluation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("case_id", sa.String(length=63), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("artifact_hash", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("evaluation_run_id", "case_id", name="uq_evaluation_cases_run_case"),
        sa.CheckConstraint(
            "status IN ('completed', 'error', 'timeout', 'cancelled')",
            name="ck_evaluation_cases_status",
        ),
        sa.CheckConstraint("latency_ms >= 0", name="ck_evaluation_cases_latency"),
        sa.CheckConstraint("length(artifact_hash) = 64", name="ck_evaluation_cases_hash"),
    )
    op.create_table(
        "evaluation_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "evaluation_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evaluation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("evaluator_version", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("evaluation_run_id", "name", name="uq_evaluation_metrics_run_name"),
        sa.CheckConstraint("case_count >= 0", name="ck_evaluation_metrics_case_count"),
        sa.CheckConstraint("error_count >= 0", name="ck_evaluation_metrics_error_count"),
    )
    op.create_table(
        "evaluation_gate_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "evaluation_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evaluation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("profile_id", sa.String(length=63), nullable=False),
        sa.Column("profile_version", sa.String(length=64), nullable=False),
        sa.Column(
            "baseline_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evaluation_runs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.UniqueConstraint("evaluation_run_id", name="uq_evaluation_gate_run"),
    )
    op.execute(
        """
        CREATE FUNCTION prevent_evaluation_artifact_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'evaluation artifacts are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in (
        "evaluation_runs",
        "evaluation_case_results",
        "evaluation_metrics",
        "evaluation_gate_decisions",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table}_immutable
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION prevent_evaluation_artifact_mutation()
            """
        )


def downgrade() -> None:
    for table in (
        "evaluation_gate_decisions",
        "evaluation_metrics",
        "evaluation_case_results",
        "evaluation_runs",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_evaluation_artifact_mutation")
    op.drop_table("evaluation_gate_decisions")
    op.drop_table("evaluation_metrics")
    op.drop_table("evaluation_case_results")
    op.drop_index("ix_evaluation_runs_suite_started", table_name="evaluation_runs")
    op.drop_index("ix_evaluation_runs_agent_started", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
