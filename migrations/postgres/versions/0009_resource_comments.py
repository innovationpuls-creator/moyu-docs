"""Comments (arch 17 §5/§8): flat threads over PostgreSQL (never Yjs)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_comments",
        sa.Column("comment_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("anchor", postgresql.JSONB(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["core.resources.resource_id"],
            name="fk_comments_resource",
        ),
        sa.ForeignKeyConstraint(
            ["author_account_id"],
            ["auth.accounts.account_id"],
            name="fk_comments_account",
        ),
        sa.Index("ix_comments_resource_created", "resource_id", "created_at"),
        schema="collab",
    )


def downgrade() -> None:
    op.drop_table("resource_comments", schema="collab")
