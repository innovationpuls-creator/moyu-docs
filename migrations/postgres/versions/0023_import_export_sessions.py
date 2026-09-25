"""Persist Import / Export Session identities and retention boundaries.

Revision ID: 0023
Revises: 0022
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_sessions",
        sa.Column("import_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stage", sa.String(32), nullable=False, server_default="Created"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("plan_ref", sa.Text(), nullable=True),
        sa.Column("result_ref", sa.Text(), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["core.workspaces.workspace_id"]),
        sa.ForeignKeyConstraint(["project_id"], ["core.projects.project_id"]),
        sa.ForeignKeyConstraint(["created_by"], ["auth.accounts.account_id"]),
        sa.ForeignKeyConstraint(["task_id"], ["work.tasks.task_id"]),
        sa.CheckConstraint(
            "stage IN ('Created','Uploading','Inspecting','Validating',"
            "'ReadyForReview','Importing','Completed','Expired')",
            name="ck_import_sessions_stage",
        ),
        schema="work",
    )
    op.create_index(
        "uq_import_sessions_task",
        "import_sessions",
        ["task_id"],
        unique=True,
        schema="work",
        postgresql_where=sa.text("task_id IS NOT NULL"),
    )
    op.create_index(
        "ix_import_sessions_expiry",
        "import_sessions",
        ["expires_at", "stage"],
        schema="work",
    )

    op.create_table(
        "export_sessions",
        sa.Column("export_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("format", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False, server_default="Created"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("result_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["core.workspaces.workspace_id"]),
        sa.ForeignKeyConstraint(["created_by"], ["auth.accounts.account_id"]),
        sa.ForeignKeyConstraint(["task_id"], ["work.tasks.task_id"]),
        sa.CheckConstraint(
            "stage IN ('Created','Preparing','Exporting',"
            "'Packaging','Ready','Expired')",
            name="ck_export_sessions_stage",
        ),
        sa.UniqueConstraint("task_id", name="uq_export_sessions_task"),
        schema="work",
    )
    op.create_index(
        "ix_export_sessions_expiry",
        "export_sessions",
        ["expires_at", "stage"],
        schema="work",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_export_sessions_expiry", table_name="export_sessions", schema="work"
    )
    op.drop_table("export_sessions", schema="work")
    op.drop_index(
        "ix_import_sessions_expiry", table_name="import_sessions", schema="work"
    )
    op.drop_index(
        "uq_import_sessions_task", table_name="import_sessions", schema="work"
    )
    op.drop_table("import_sessions", schema="work")
