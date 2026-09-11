"""Persist rollback recovery windows and decisions.

Revision ID: 0010_recovery_verification
Revises: 0009_rollback_operations
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_recovery_verification"
down_revision: str | None = "0009_rollback_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rollback_operations",
        sa.Column("verification_deadline", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rollback_operations",
        sa.Column(
            "recovery_decision",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("rollback_operations", "recovery_decision")
    op.drop_column("rollback_operations", "verification_deadline")
