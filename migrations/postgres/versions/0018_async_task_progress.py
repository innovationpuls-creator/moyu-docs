"""Persist queryable task progress and task update timestamps."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("progress_message_code", sa.String(120), nullable=True),
        schema="work",
    )
    op.add_column(
        "tasks",
        sa.Column("progress_current", sa.BigInteger(), nullable=True),
        schema="work",
    )
    op.add_column(
        "tasks",
        sa.Column("progress_total", sa.BigInteger(), nullable=True),
        schema="work",
    )
    op.add_column(
        "tasks",
        sa.Column("progress_percentage", sa.Numeric(5, 2), nullable=True),
        schema="work",
    )
    op.add_column(
        "tasks",
        sa.Column(
            "progress_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="work",
    )
    op.create_check_constraint(
        "ck_tasks_progress_nonnegative",
        "tasks",
        "(progress_current IS NULL OR progress_current >= 0) AND "
        "(progress_total IS NULL OR progress_total >= 0) AND "
        "(progress_percentage IS NULL OR "
        "(progress_percentage >= 0 AND progress_percentage <= 100)) AND "
        "(progress_current IS NULL OR progress_total IS NULL OR "
        "progress_current <= progress_total) AND "
        "(progress_percentage IS NULL OR "
        "(progress_current IS NOT NULL AND progress_total IS NOT NULL "
        "AND progress_total > 0))",
        schema="work",
    )
    op.create_index(
        "ix_tasks_actor_created",
        "tasks",
        ["actor_account_id", "created_at"],
        schema="work",
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_actor_created", table_name="tasks", schema="work")
    op.drop_constraint(
        "ck_tasks_progress_nonnegative", "tasks", schema="work", type_="check"
    )
    op.drop_column("tasks", "progress_updated_at", schema="work")
    op.drop_column("tasks", "progress_percentage", schema="work")
    op.drop_column("tasks", "progress_total", schema="work")
    op.drop_column("tasks", "progress_current", schema="work")
    op.drop_column("tasks", "progress_message_code", schema="work")
