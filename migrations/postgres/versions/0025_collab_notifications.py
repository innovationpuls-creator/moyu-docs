"""Move notifications to their Architecture 29 owner and add stable targets."""

from __future__ import annotations

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS collab")
    op.execute(
        """
        CREATE TABLE collab.notifications (
            notification_id uuid PRIMARY KEY,
            recipient_account_id uuid NOT NULL
                REFERENCES auth.accounts(account_id),
            type varchar(64) NOT NULL,
            target_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
            payload jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            read_at timestamptz NULL,
            source_event_id uuid NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_notifications_recipient_read "
        "ON collab.notifications (recipient_account_id, read_at, created_at DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_notifications_source_event "
        "ON collab.notifications (recipient_account_id, source_event_id, type)"
    )
    op.execute(
        """
        INSERT INTO collab.notifications
            (notification_id, recipient_account_id, type, target_ref, payload,
             created_at, read_at)
        SELECT notification_id, account_id, kind,
            jsonb_strip_nulls(jsonb_build_object(
                'resourceId', payload->'resourceId',
                'threadId', payload->'threadId',
                'commentId', payload->'commentId'
            )),
            payload, created_at, read_at
        FROM core.notifications
        """
    )
    op.execute("DROP TABLE core.notifications")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE core.notifications (
            notification_id uuid PRIMARY KEY,
            account_id uuid NOT NULL REFERENCES auth.accounts(account_id),
            kind varchar(32) NOT NULL,
            payload jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            read_at timestamptz NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_notifications_account_read "
        "ON core.notifications (account_id, read_at)"
    )
    op.execute(
        """
        INSERT INTO core.notifications
            (notification_id, account_id, kind, payload, created_at, read_at)
        SELECT notification_id, recipient_account_id, type, payload, created_at,
            read_at
        FROM collab.notifications
        """
    )
    op.execute("DROP TABLE collab.notifications")
