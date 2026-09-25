"""Persist comment thread lifecycle and attach existing comments to threads."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "comment_threads",
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("anchor_type", sa.String(32), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("start_relative_position", postgresql.BYTEA(), nullable=True),
        sa.Column("end_relative_position", postgresql.BYTEA(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="Open"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('Open', 'Resolved', 'Detached')",
            name="ck_comment_threads_status",
        ),
        sa.CheckConstraint(
            "(status = 'Resolved' AND resolved_at IS NOT NULL "
            "AND resolved_by IS NOT NULL) OR (status <> 'Resolved' "
            "AND resolved_at IS NULL AND resolved_by IS NULL)",
            name="ck_comment_threads_resolution",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["core.resources.resource_id"],
            name="fk_comment_threads_resource",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["auth.accounts.account_id"],
            name="fk_comment_threads_creator",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"],
            ["auth.accounts.account_id"],
            name="fk_comment_threads_resolver",
        ),
        sa.PrimaryKeyConstraint("resource_id", "thread_id", name="pk_comment_threads"),
        sa.Index(
            "ix_comment_threads_resource_status",
            "resource_id",
            "status",
        ),
        schema="collab",
    )
    op.execute(
        sa.text(
            "INSERT INTO collab.comment_threads "
            "(thread_id, resource_id, anchor_type, status, created_by, created_at) "
            "SELECT DISTINCT ON (resource_id, thread_id) thread_id, resource_id, "
            "CASE anchor->>'type' "
            "WHEN 'Node' THEN 'Node' WHEN 'NodeAnchor' THEN 'Node' "
            "WHEN 'TextRange' THEN 'TextRange' "
            "WHEN 'TextRangeAnchor' THEN 'TextRange' ELSE 'Resource' END, "
            "'Open', author_account_id, created_at "
            "FROM collab.resource_comments "
            "ORDER BY resource_id, thread_id, created_at ASC, comment_id ASC"
        )
    )
    op.create_foreign_key(
        "fk_comments_thread",
        "resource_comments",
        "comment_threads",
        ["resource_id", "thread_id"],
        ["resource_id", "thread_id"],
        source_schema="collab",
        referent_schema="collab",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_comments_thread", "resource_comments", schema="collab", type_="foreignkey"
    )
    op.drop_table("comment_threads", schema="collab")
