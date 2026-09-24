"""Add Workspace lifecycle purge timestamps and eligibility index."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("purge_eligible_at", sa.DateTime(timezone=True)),
        schema="core",
    )
    op.add_column(
        "workspaces",
        sa.Column("purge_executed_at", sa.DateTime(timezone=True)),
        schema="core",
    )
    op.create_index(
        "ix_workspaces_purge_eligibility",
        "workspaces",
        ["status", "purge_eligible_at", "workspace_id"],
        schema="core",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspaces_purge_eligibility", table_name="workspaces", schema="core"
    )
    op.drop_column("workspaces", "purge_executed_at", schema="core")
    op.drop_column("workspaces", "purge_eligible_at", schema="core")
