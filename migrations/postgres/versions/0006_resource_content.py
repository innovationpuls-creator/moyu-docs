"""Resource content: core.resources + collab journal/checkpoints (arch 29 §30/46-48).

Additive only. Permission-owned collab.resource_ownership/core.resource_permissions
are NOT created here (Permission module owns them).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

RESOURCE_TYPES = ("document", "code", "markdown", "text")


def _timestamptz() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS collab")

    op.create_table(
        "resources",
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("folder_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("normalized_name", sa.String(120), nullable=False),
        sa.Column("lifecycle", sa.String(32), nullable=False, server_default="Active"),
        sa.Column(
            "schema_version",
            sa.String(16),
            nullable=False,
            server_default="1.0.0",
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.Column("trashed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"resource_type IN {RESOURCE_TYPES}", name="ck_resources_type"
        ),
        sa.CheckConstraint(
            "lifecycle IN ('Active','Trashed','Purging','Purged')",
            name="ck_resources_lifecycle",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["core.projects.project_id"]),
        sa.ForeignKeyConstraint(["folder_id"], ["core.folders.folder_id"]),
        sa.ForeignKeyConstraint(["created_by"], ["auth.accounts.account_id"]),
        schema="core",
    )
    # Sibling-name uniqueness INCLUDES Trashed/Purged rows (user ruling).
    op.create_index(
        "uq_resources_project_name",
        "resources",
        ["project_id", "normalized_name"],
        unique=True,
        schema="core",
    )

    op.create_table(
        "resource_update_journal",
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("journal_seq", sa.BigInteger(), nullable=False),
        sa.Column("ownership_epoch", sa.BigInteger(), nullable=False),
        sa.Column("update_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("update_hash", sa.String(64), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("durable_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("resource_id", "journal_seq"),
        schema="collab",
        postgresql_partition_by="HASH (resource_id)",
    )
    for idx in range(4):
        op.execute(
            f"CREATE TABLE collab.ruj_p{idx} "
            f"PARTITION OF collab.resource_update_journal "
            f"FOR VALUES WITH (MODULUS 4, REMAINDER {idx})"
        )

    op.create_table(
        "resource_checkpoints",
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checkpoint_seq", sa.BigInteger(), nullable=False),
        sa.Column("base_journal_seq", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("resource_id", "checkpoint_seq"),
        sa.ForeignKeyConstraint(["resource_id"], ["core.resources.resource_id"]),
        schema="collab",
    )


def downgrade() -> None:
    op.drop_table("resource_checkpoints", schema="collab")
    op.execute("DROP TABLE IF EXISTS collab.resource_update_journal CASCADE")
    op.drop_index("uq_resources_project_name", table_name="resources", schema="core")
    op.drop_table("resources", schema="core")
    op.execute("DROP SCHEMA IF EXISTS collab")
