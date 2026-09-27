"""Record the state an AI ChangeSet was proposed against and its apply receipt."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_changesets",
        sa.Column("base_journal_seq", sa.BigInteger(), nullable=True),
        schema="collab",
    )
    op.add_column(
        "ai_changesets",
        sa.Column("applied_journal_seq", sa.BigInteger(), nullable=True),
        schema="collab",
    )


def downgrade() -> None:
    op.drop_column("ai_changesets", "applied_journal_seq", schema="collab")
    op.drop_column("ai_changesets", "base_journal_seq", schema="collab")
