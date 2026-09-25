"""Create revokable, expiring anonymous read-only Resource Share Links.

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "share_links",
        sa.Column("share_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("capability", sa.String(16), nullable=False, server_default="Read"),
        sa.Column("status", sa.String(16), nullable=False, server_default="Active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "capability = 'Read'", name="ck_share_links_capability_read_only"
        ),
        sa.CheckConstraint(
            "status IN ('Active', 'Revoked')", name="ck_share_links_status"
        ),
        sa.CheckConstraint(
            "(status = 'Revoked') = (revoked_at IS NOT NULL)",
            name="ck_share_links_revoked_at_matches_status",
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name="ck_share_links_token_hash_sha256"
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"], ["core.resources.resource_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["auth.accounts.account_id"]),
        sa.UniqueConstraint("token_hash", name="uq_share_links_token_hash"),
        schema="core",
    )
    op.create_index(
        "ix_share_links_resource_created",
        "share_links",
        ["resource_id", "created_at"],
        schema="core",
    )
    op.create_index(
        "ix_share_links_expiry",
        "share_links",
        ["expires_at"],
        schema="core",
        postgresql_where=sa.text("status = 'Active' AND expires_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_share_links_expiry", table_name="share_links", schema="core")
    op.drop_index(
        "ix_share_links_resource_created", table_name="share_links", schema="core"
    )
    op.drop_table("share_links", schema="core")
