"""Search (arch 11 §7/§8): resource name + body tsvector index."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_search_index",
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("searchable_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("lifecycle", sa.String(32), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "body_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple', name || ' ' || COALESCE(searchable_text, ''))",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["core.resources.resource_id"],
            name="fk_search_index_resource",
        ),
        sa.Index("ix_search_index_workspace", "workspace_id"),
        sa.Index(
            "ix_search_index_tsv",
            "body_tsv",
            postgresql_using="gin",
        ),
        schema="collab",
    )


def downgrade() -> None:
    op.drop_table("resource_search_index", schema="collab")
