"""Preserve user-facing names for Resource Assets.

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resource_assets",
        sa.Column(
            "original_name",
            sa.String(255),
            nullable=False,
            server_default="attachment",
        ),
        schema="collab",
    )


def downgrade() -> None:
    op.drop_column("resource_assets", "original_name", schema="collab")
