"""Persist actor-scoped idempotency keys for manual task retries."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=True),
        schema="work",
    )
    op.create_check_constraint(
        "ck_tasks_idempotency_actor",
        "tasks",
        "idempotency_key IS NULL OR actor_account_id IS NOT NULL",
        schema="work",
    )
    op.create_index(
        "uq_tasks_actor_idempotency_key",
        "tasks",
        ["actor_account_id", "idempotency_key"],
        unique=True,
        schema="work",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_tasks_actor_idempotency_key", table_name="tasks", schema="work")
    op.drop_constraint(
        "ck_tasks_idempotency_actor", "tasks", schema="work", type_="check"
    )
    op.drop_column("tasks", "idempotency_key", schema="work")
