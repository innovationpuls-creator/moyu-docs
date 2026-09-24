"""Webhook subscriptions (arch 10 §register): workspace-scoped delivery URLs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_subscriptions",
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("secret_key_hex", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="Active"),
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
            ["workspace_id"],
            ["core.workspaces.workspace_id"],
            name="fk_webhook_subscription_workspace",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('Active', 'Disabled')", name="ck_webhook_subscriptions_status"
        ),
        sa.UniqueConstraint(
            "workspace_id", "url", name="uq_webhook_subscription_workspace_url"
        ),
        schema="core",
    )
    op.create_index(
        "ix_webhook_subscriptions_workspace",
        "webhook_subscriptions",
        ["workspace_id"],
        schema="core",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_subscriptions_workspace",
        table_name="webhook_subscriptions",
        schema="core",
    )
    op.drop_table("webhook_subscriptions", schema="core")
