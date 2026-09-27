"""Persist Realtime mutation identity and provenance on Journal entries."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resource_update_journal",
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="collab",
    )
    op.add_column(
        "resource_update_journal",
        sa.Column("mutation_request_hash", sa.String(64), nullable=True),
        schema="collab",
    )
    op.add_column(
        "resource_update_journal",
        sa.Column("mutation_kind", sa.String(32), nullable=True),
        schema="collab",
    )
    op.add_column(
        "resource_update_journal",
        sa.Column("restore_target_seq", sa.BigInteger(), nullable=True),
        schema="collab",
    )
    op.create_index(
        "uq_resource_journal_operation_id",
        "resource_update_journal",
        ["resource_id", "operation_id"],
        unique=True,
        schema="collab",
        postgresql_where=sa.text("operation_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_resource_journal_operation_id",
        table_name="resource_update_journal",
        schema="collab",
    )
    op.drop_column("resource_update_journal", "restore_target_seq", schema="collab")
    op.drop_column("resource_update_journal", "mutation_kind", schema="collab")
    op.drop_column("resource_update_journal", "mutation_request_hash", schema="collab")
    op.drop_column("resource_update_journal", "operation_id", schema="collab")
