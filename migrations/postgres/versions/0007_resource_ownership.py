"""Permission-owned collab.resource_ownership (arch 29 §44)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS collab")
    op.create_table(
        "resource_ownership",
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("epoch", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
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
            name="fk_resource_ownership_resource",
        ),
        sa.ForeignKeyConstraint(
            ["owner_account_id"],
            ["auth.accounts.account_id"],
            name="fk_resource_ownership_account",
        ),
        schema="collab",
    )


def downgrade() -> None:
    op.drop_table("resource_ownership", schema="collab")
