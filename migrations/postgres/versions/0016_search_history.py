"""Search history (arch 11 §user): per-account typed queries, de-duplicated."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_history",
        sa.Column("history_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["auth.accounts.account_id"],
            name="fk_search_history_account",
        ),
        sa.UniqueConstraint(
            "account_id", "query", name="uq_search_history_account_query"
        ),
        sa.Index("ix_search_history_account_created", "account_id", "created_at"),
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("search_history", schema="core")
