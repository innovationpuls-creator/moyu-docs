"""Create Workspace, Project, and Folder metadata tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def _timestamp() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS core")

    op.create_table(
        "workspaces",
        sa.Column("workspace_id", _uuid(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="Active"),
        sa.Column(
            "created_by",
            _uuid(),
            sa.ForeignKey("auth.accounts.account_id"),
            nullable=False,
        ),
        sa.Column(
            "created_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deletion_requested_at", _timestamp()),
        sa.CheckConstraint(
            "status IN ('Active', 'DeletionPending', 'Deleted')",
            name="ck_workspaces_status",
        ),
        schema="core",
    )

    op.create_table(
        "projects",
        sa.Column("project_id", _uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            _uuid(),
            sa.ForeignKey("core.workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("normalized_name", sa.String(120), nullable=False),
        sa.Column("lifecycle", sa.String(32), nullable=False, server_default="Active"),
        sa.Column(
            "created_by",
            _uuid(),
            sa.ForeignKey("auth.accounts.account_id"),
            nullable=False,
        ),
        sa.Column(
            "created_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("archived_at", _timestamp()),
        sa.Column("trashed_at", _timestamp()),
        sa.CheckConstraint(
            "lifecycle IN ('Active', 'Archived', 'Trashed', 'Purging', 'Purged')",
            name="ck_projects_lifecycle",
        ),
        sa.UniqueConstraint(
            "workspace_id", "normalized_name", name="uq_projects_workspace_name"
        ),
        schema="core",
    )
    op.create_index(
        "ix_projects_workspace_id", "projects", ["workspace_id"], schema="core"
    )

    op.create_table(
        "folders",
        sa.Column("folder_id", _uuid(), primary_key=True),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("parent_folder_id", _uuid()),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("normalized_name", sa.String(120), nullable=False),
        sa.Column("lifecycle", sa.String(32), nullable=False, server_default="Active"),
        sa.Column(
            "created_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", _timestamp(), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "lifecycle IN ('Active', 'Trashed', 'Deleted')",
            name="ck_folders_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["core.projects.project_id"], name="fk_folders_project"
        ),
        sa.ForeignKeyConstraint(
            ["parent_folder_id", "project_id"],
            ["core.folders.folder_id", "core.folders.project_id"],
            name="fk_folders_parent_same_project",
        ),
        sa.UniqueConstraint("folder_id", "project_id", name="uq_folders_id_project"),
        schema="core",
    )
    op.create_index(
        "uq_folders_project_root_name",
        "folders",
        ["project_id", "normalized_name"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("parent_folder_id IS NULL"),
    )
    op.create_index(
        "uq_folders_parent_name",
        "folders",
        ["project_id", "parent_folder_id", "normalized_name"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("parent_folder_id IS NOT NULL"),
    )
    op.create_index("ix_folders_project_id", "folders", ["project_id"], schema="core")
    op.create_index(
        "ix_folders_parent_folder_id",
        "folders",
        ["parent_folder_id"],
        schema="core",
    )


def downgrade() -> None:
    op.drop_index("ix_folders_parent_folder_id", table_name="folders", schema="core")
    op.drop_index("ix_folders_project_id", table_name="folders", schema="core")
    op.drop_index("uq_folders_parent_name", table_name="folders", schema="core")
    op.drop_index("uq_folders_project_root_name", table_name="folders", schema="core")
    op.drop_table("folders", schema="core")
    op.drop_index("ix_projects_workspace_id", table_name="projects", schema="core")
    op.drop_table("projects", schema="core")
    op.drop_table("workspaces", schema="core")
