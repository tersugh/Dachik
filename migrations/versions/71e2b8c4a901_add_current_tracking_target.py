"""Add explicit singleton current tracking target.

Revision ID: 71e2b8c4a901
Revises: 15ac772ee7c5
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "71e2b8c4a901"
down_revision: str | None = "15ac772ee7c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "current_tracking_target",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("selected_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_current_tracking_target_singleton"),
        sa.ForeignKeyConstraint(
            ["experiment_id"], ["data_audit_experiments.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("experiment_id"),
    )


def downgrade() -> None:
    op.drop_table("current_tracking_target")
