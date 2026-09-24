"""History (arch 08): named versions (collab.resource_named_versions)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_named_versions",
        sa.Column("version_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("base_journal_seq", sa.BigInteger(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["core.resources.resource_id"],
            name="fk_named_versions_resource",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["auth.accounts.account_id"],
            name="fk_named_versions_account",
        ),
        sa.Index("ix_named_versions_resource", "resource_id"),
        schema="collab",
    )


def downgrade() -> None:
    op.drop_table("resource_named_versions", schema="collab")
